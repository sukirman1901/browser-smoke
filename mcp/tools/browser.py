from __future__ import annotations

import asyncio
import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from tools.image_diff import compare_png
from tools.payload import (
    cap_append,
    format_snapshot_lines,
    matches_url,
    safe_artifact_name,
    wrap_init_script,
)

SNAPSHOT_JS = """
({full, start}) => {
  const implicit = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return "link";
    if (tag === "button") return "button";
    if (tag === "input") {
      const t = (el.getAttribute("type") || "text").toLowerCase();
      if (t === "submit" || t === "button") return "button";
      if (t === "checkbox") return "checkbox";
      if (t === "radio") return "radio";
      return "textbox";
    }
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    return el.getAttribute("role") || tag;
  };
  document.querySelectorAll("[data-bs-ref]").forEach((el) => el.removeAttribute("data-bs-ref"));
  const selector = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="textbox"], [role="checkbox"], [tabindex]:not([tabindex="-1"])';
  const items = [];
  let n = start;
  document.querySelectorAll(selector).forEach((el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    if (!full && (rect.bottom < 0 || rect.top > window.innerHeight)) return;
    const role = el.getAttribute("role") || implicit(el);
    const name = (
      el.getAttribute("aria-label") ||
      el.getAttribute("placeholder") ||
      el.getAttribute("alt") ||
      (el.value && String(el.value)) ||
      (el.textContent || "")
    ).trim().replace(/\\s+/g, " ").slice(0, 60);
    el.setAttribute("data-bs-ref", String(n));
    items.push({
      ref: n,
      role,
      name,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type") || undefined,
      href: el.getAttribute("href") || undefined,
    });
    n += 1;
  });
  return {items, next: n};
}
"""


@dataclass
class BrowserSession:
    browser: Optional[Browser] = None
    context: Optional[BrowserContext] = None
    page: Optional[Page] = None
    _pw: Optional[object] = field(default=None)
    _console_logs: list[dict] = field(default_factory=list)
    _page_errors: list[dict] = field(default_factory=list)
    _network_logs: list[dict] = field(default_factory=list)
    _network_capturing: bool = False
    _capture_patterns: list[str] = field(default_factory=list)
    _blocked_patterns: list = field(default_factory=list)
    _pages: list[Page] = field(default_factory=list)
    _offscreen_page: Optional[Page] = field(default=None)
    _refs: dict[str, dict[str, str]] = field(default_factory=dict)
    _shot_n: int = 0
    _dialog_action: str = "dismiss"
    _dialog_prompt: str = ""
    _last_dialog: Optional[dict] = None
    _listened_pages: set[int] = field(default_factory=set)
    _block_route_installed: bool = False
    name: str = "default"
    persist: bool = False
    _cdp_port: Optional[int] = None
    _chrome_pid: Optional[int] = None

    def _bind_io(self):
        if self.context is None:
            return
        self.context.on("page", self._on_new_page)
        self.context.on("response", self._on_net_response)
        self._pages = list(self.context.pages)
        self._listened_pages.clear()
        self._block_route_installed = False
        for page in self._pages:
            self._setup_page_listeners(page)

    async def start(
        self,
        headless: bool = False,
        channel: str = "",
        user_data_dir: str = "",
        persist: bool = False,
    ):
        from tools.persist import (
            cdp_alive,
            read_state,
            session_cdp_port,
            spawn_chromium,
            write_state,
        )

        self.persist = persist
        self._pw = await async_playwright().start()
        os.makedirs(os.path.join(os.getcwd(), "artifacts", "downloads"), exist_ok=True)
        if persist:
            port = session_cdp_port(self.name)
            profile = os.path.abspath(user_data_dir) if user_data_dir else os.path.abspath(
                os.path.join(".browser-smoke", "profiles", self.name)
            )
            os.makedirs(profile, exist_ok=True)
            state = read_state(self.name)
            pid = int(state.get("pid") or 0)
            if not cdp_alive(port):
                exe = self._pw.chromium.executable_path
                pid = spawn_chromium(exe, port, profile, headless=headless)
            self._cdp_port = port
            self._chrome_pid = pid
            write_state(self.name, {"port": port, "pid": pid, "user_data_dir": profile})
            self.browser = await self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            self.context = self.browser.contexts[0] if self.browser.contexts else await self.browser.new_context()
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            self._bind_io()
            return
        context_kwargs: dict[str, Any] = {
            "viewport": {"width": 1280, "height": 720},
            "accept_downloads": True,
        }
        launch_kwargs: dict[str, Any] = {"headless": headless}
        if channel:
            launch_kwargs["channel"] = channel
        if user_data_dir:
            path = os.path.abspath(user_data_dir)
            os.makedirs(path, exist_ok=True)
            self.context = await self._pw.chromium.launch_persistent_context(
                path, **launch_kwargs, **context_kwargs
            )
            self.browser = None
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        else:
            self.browser = await self._pw.chromium.launch(**launch_kwargs)
            self.context = await self.browser.new_context(**context_kwargs)
            self.page = await self.context.new_page()
        self._bind_io()

    async def ensure_started(
        self,
        headless: bool = False,
        channel: str = "",
        user_data_dir: str = "",
        persist: bool = False,
    ):
        if self.page is None:
            await self.start(
                headless=headless,
                channel=channel,
                user_data_dir=user_data_dir,
                persist=persist or self.persist,
            )

    def _need_page(self) -> dict | None:
        if self.page is None:
            return {"status": "error", "message": "No page open. Call browser_open first."}
        return None

    def _need_context(self) -> dict | None:
        if self.context is None:
            return {"status": "error", "message": "No browser session. Call browser_open first."}
        return None

    def _setup_page_listeners(self, page: Page):
        key = id(page)
        if key in self._listened_pages:
            return
        self._listened_pages.add(key)
        page.on("console", lambda msg: cap_append(self._console_logs, {
            "type": msg.type, "text": msg.text, "url": msg.location.get("url", ""),
        }))
        page.on("pageerror", lambda err: cap_append(self._page_errors, {
            "message": str(err), "url": page.url,
        }))
        page.on("dialog", self._on_dialog)

    async def _on_dialog(self, dialog):
        self._last_dialog = {
            "type": dialog.type,
            "message": str(dialog.message)[:240],
        }
        action = self._dialog_action
        prompt = self._dialog_prompt
        self._dialog_action = "dismiss"
        self._dialog_prompt = ""
        if action == "accept":
            await dialog.accept(prompt)
        else:
            await dialog.dismiss()

    def _target(self, selector: str) -> dict[str, str] | str:
        if selector.startswith("@") and selector[1:].isdigit():
            mapped = self._refs.get(selector[1:])
            if not mapped:
                raise ValueError(f"Unknown ref {selector}. Call browser_snapshot first.")
            return mapped
        return selector

    async def _locator(self, selector: str):
        is_ref = selector.startswith("@") and selector[1:].isdigit()
        target = self._target(selector)
        if isinstance(target, str):
            loc = self.page.locator(target).first
        else:
            frame = target.get("frame") or ""
            loc = (
                self.page.frame_locator(frame).locator(target["sel"])
                if frame
                else self.page.locator(target["sel"])
            ).first
        if is_ref and await loc.count() == 0:
            raise ValueError(f"Expired ref {selector}. Call browser_snapshot again.")
        return loc

    def _on_new_page(self, page: Page):
        if page not in self._pages:
            self._pages.append(page)
        self._setup_page_listeners(page)

    async def start_network_capture(self, patterns: list[str] | None = None):
        err = self._need_context()
        if err:
            return err
        self._network_logs.clear()
        self._network_capturing = True
        self._capture_patterns = patterns or ["**/*"]
        return {"status": "ok", "message": "Network capture started"}

    def _on_net_response(self, response):
        if not self._network_capturing:
            return
        url = response.url
        if not matches_url(url, self._capture_patterns):
            return
        try:
            cap_append(self._network_logs, {
                "method": response.request.method,
                "url": url,
                "status": response.status,
                "resource_type": response.request.resource_type,
            })
        except Exception:
            return

    async def _block_route(self, route):
        if matches_url(route.request.url, self._blocked_patterns):
            await route.abort()
            return
        await route.continue_()

    async def stop_network_capture(self):
        self._network_capturing = False
        return {"status": "ok", "captured": len(self._network_logs)}

    def get_network_logs(self):
        return list(self._network_logs)

    async def block_resources(self, patterns: list[str]):
        err = self._need_context()
        if err:
            return err
        if self._block_route_installed:
            try:
                await self.context.unroute("**/*", self._block_route)
            except Exception:
                pass
            self._block_route_installed = False
        self._blocked_patterns = patterns
        if not patterns:
            return {"status": "ok", "message": "All resources unblocked"}
        await self.context.route("**/*", self._block_route)
        self._block_route_installed = True
        return {"status": "ok", "blocked_patterns": patterns}

    async def _shot_fields(self, screenshot: bool, screenshot_base64: bool) -> dict:
        if not screenshot and not screenshot_base64:
            return {}
        if self.page is None:
            return {"status": "error", "message": "No page open"}
        png = await self.page.screenshot(type="png", full_page=False)
        artifacts = os.path.join(os.getcwd(), "artifacts", "shots")
        os.makedirs(artifacts, exist_ok=True)
        self._shot_n += 1
        path = os.path.join(artifacts, f"{self._shot_n:04d}.png")
        with open(path, "wb") as f:
            f.write(png)
        out = {"screenshot_path": path}
        if screenshot_base64:
            out["screenshot"] = base64.b64encode(png).decode()
        return out

    async def open(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        screenshot: bool = False,
        screenshot_base64: bool = False,
    ) -> dict:
        if not self.page:
            await self.ensure_started()
        try:
            allowed = {"load", "domcontentloaded", "networkidle", "commit"}
            until = wait_until if wait_until in allowed else "domcontentloaded"
            response = await self.page.goto(url, wait_until=until, timeout=30000)
            title = await self.page.title()
            result = {
                "status": "ok",
                "title": title,
                "url": self.page.url,
                "status_code": response.status if response else None,
            }
            result.update(await self._shot_fields(screenshot, screenshot_base64))
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def extract_dom(self) -> list[dict] | dict:
        err = self._need_page()
        if err:
            return err
        return await self.page.evaluate("""
            () => {
                const interactives = ['button', 'a', 'input', 'select', 'textarea', '[role="button"]', '[tabindex]'];
                const items = [];
                document.querySelectorAll(interactives.join(',')).forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) return;
                    const tag = el.tagName.toLowerCase();
                    const text = el.textContent?.trim() || el.getAttribute('aria-label') || '';
                    const selector = buildSelector(el);
                    const inputType = el.getAttribute('type') || '';
                    items.push({
                        tag,
                        text: text.substring(0, 60),
                        selector,
                        type: tag === 'input' ? inputType : tag,
                        visible: rect.top < window.innerHeight && rect.bottom > 0,
                        enabled: !el.disabled,
                    });
                });
                return items;

                function buildSelector(el) {
                    if (el.id) return '#' + CSS.escape(el.id);
                    if (el.getAttribute('data-testid')) return '[data-testid="' + el.getAttribute('data-testid') + '"]';
                    const tag = el.tagName.toLowerCase();
                    const text = el.textContent?.trim().substring(0, 50);
                    if (text && ['button', 'a'].includes(tag)) return tag + ':has-text("' + text.replace(/"/g, '\\\\"') + '")';
                    const parent = el.parentElement?.closest('[id]');
                    if (parent) return '#' + CSS.escape(parent.id) + ' ' + tag + ':nth-child(' + (Array.from(parent.children).indexOf(el) + 1) + ')';
                    return tag + ':nth-child(' + (Array.from(el.parentElement?.children || []).indexOf(el) + 1) + ')';
                }
            }
        """)

    async def snapshot(self, scope: str = "viewport") -> dict:
        err = self._need_page()
        if err:
            return err
        full = scope == "page"
        self._refs = {}
        items: list[dict] = []
        payload = await self.page.evaluate(SNAPSHOT_JS, {"full": full, "start": 1})
        n = payload["next"]
        for item in payload["items"]:
            self._refs[str(item["ref"])] = {"sel": f'[data-bs-ref="{item["ref"]}"]', "frame": ""}
            items.append(item)
        count = await self.page.locator("iframe").count()
        for i in range(count):
            handle = await self.page.locator("iframe").nth(i).element_handle()
            if handle is None:
                continue
            content = await handle.content_frame()
            if content is None:
                continue
            try:
                payload = await content.evaluate(SNAPSHOT_JS, {"full": full, "start": n})
            except Exception:
                continue
            n = payload["next"]
            frame_sel = f"iframe >> nth={i}"
            for item in payload["items"]:
                item["iframe"] = True
                self._refs[str(item["ref"])] = {
                    "sel": f'[data-bs-ref="{item["ref"]}"]',
                    "frame": frame_sel,
                }
                items.append(item)
        return {
            "status": "ok",
            "url": self.page.url,
            "count": len(items),
            "snapshot": format_snapshot_lines(items),
        }

    def _arm_dialog(self, dialog: str, prompt: str = "") -> dict | None:
        if not dialog:
            return None
        if dialog not in ("accept", "dismiss"):
            return {"status": "error", "message": "dialog must be accept or dismiss"}
        self._dialog_action = dialog
        self._dialog_prompt = prompt
        return None

    async def _adopt_page(self, page: Page) -> None:
        self._on_new_page(page)
        self.page = page
        try:
            await page.bring_to_front()
        except Exception:
            pass

    async def click(
        self,
        selector: str,
        *,
        screenshot: bool = False,
        screenshot_base64: bool = False,
        timeout: int = 5000,
        dialog: str = "",
        prompt: str = "",
        popup: bool = False,
    ) -> dict:
        err = self._need_page()
        if err:
            return err
        armed = self._arm_dialog(dialog, prompt)
        if armed:
            return armed
        self._last_dialog = None
        wait_ms = timeout if timeout > 0 else 5000
        if popup:
            wait_ms = max(wait_ms, 15000)
        try:
            loc = await self._locator(selector)
            if popup:
                async with self.page.expect_popup(timeout=wait_ms) as pending:
                    await loc.click(timeout=min(wait_ms, 15000))
                new_page = await pending.value
                await self._adopt_page(new_page)
                try:
                    await new_page.wait_for_load_state("domcontentloaded", timeout=wait_ms)
                except Exception:
                    pass
                result = {
                    "status": "ok",
                    "popup": True,
                    "url": new_page.url,
                    "title": await new_page.title(),
                    "hint": "Call browser_snapshot again. browser_switch_tab to return.",
                }
            else:
                await loc.click(timeout=wait_ms)
                result = {"status": "ok", "url": self.page.url}
            if self._last_dialog:
                result["dialog"] = self._last_dialog
                self._last_dialog = None
            result.update(await self._shot_fields(screenshot, screenshot_base64))
            return result
        except Exception as e:
            msg = str(e)
            if popup and "Timeout" in msg:
                msg = f"No popup opened. {msg}"
            err = {"status": "error", "message": msg}
            err.update(await self._shot_fields(screenshot, screenshot_base64))
            return err

    async def type_text(
        self,
        selector: str,
        text: str,
        *,
        screenshot: bool = False,
        screenshot_base64: bool = False,
        timeout: int = 5000,
    ) -> dict:
        err = self._need_page()
        if err:
            return err
        try:
            await (await self._locator(selector)).fill(text, timeout=timeout)
            result = {"status": "ok"}
            result.update(await self._shot_fields(screenshot, screenshot_base64))
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def screenshot(self, *, screenshot_base64: bool = False) -> dict:
        err = self._need_page()
        if err:
            return err
        fields = await self._shot_fields(True, screenshot_base64)
        return {"status": "ok", **fields}

    async def highlight(
        self,
        selector: str,
        color: str = "red",
        duration: int = 2000,
        *,
        screenshot: bool = False,
        screenshot_base64: bool = False,
    ) -> dict:
        err = self._need_page()
        if err:
            return err
        try:
            loc = await self._locator(selector)
            found = await loc.evaluate(
                """(el, {color, duration}) => {
                    const orig = {
                        outline: el.style.outline,
                        outlineOffset: el.style.outlineOffset,
                    };
                    el.style.outline = '3px solid ' + color;
                    el.style.outlineOffset = '2px';
                    setTimeout(() => {
                        el.style.outline = orig.outline;
                        el.style.outlineOffset = orig.outlineOffset;
                    }, duration);
                    return {found: true, tag: el.tagName};
                }""",
                {"color": color, "duration": duration},
            )
            result = {"status": "ok", **(found or {})}
            result.update(await self._shot_fields(screenshot, screenshot_base64))
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def screenshot_diff(
        self,
        name: str,
        threshold: float = 0.01,
        *,
        screenshot_base64: bool = False,
    ) -> dict:
        err = self._need_page()
        if err:
            return err
        baseline_dir = os.path.join(os.getcwd(), "artifacts", "baselines")
        os.makedirs(baseline_dir, exist_ok=True)
        name = safe_artifact_name(name, "baseline")
        baseline_path = os.path.join(baseline_dir, f"{name}.png")
        current_png = await self.page.screenshot(type="png")

        if not os.path.exists(baseline_path):
            with open(baseline_path, "wb") as f:
                f.write(current_png)
            return {
                "status": "baseline_created",
                "name": name,
                "path": baseline_path,
            }

        with open(baseline_path, "rb") as f:
            baseline_png = f.read()

        compared = compare_png(baseline_png, current_png, threshold=threshold)
        if compared.get("status") == "error":
            current_path = os.path.join(baseline_dir, f"{name}.current.png")
            with open(current_path, "wb") as f:
                f.write(current_png)
            compared["name"] = name
            compared["current_path"] = current_path
            compared["baseline_path"] = baseline_path
            return compared

        result = {
            "status": compared["status"],
            "name": name,
            "diff_pixels": compared["diff_pixels"],
            "total_pixels": compared["total_pixels"],
            "threshold": compared["threshold"],
            "baseline_hash": compared["baseline_hash"],
            "current_hash": compared["current_hash"],
        }
        if compared["diff_png"]:
            diff_path = os.path.join(baseline_dir, f"{name}.diff.png")
            with open(diff_path, "wb") as f:
                f.write(compared["diff_png"])
            result["diff_path"] = diff_path
            if screenshot_base64:
                result["diff_screenshot"] = base64.b64encode(compared["diff_png"]).decode()
        return result

    async def scroll(
        self,
        x: int = 0,
        y: int = 200,
        *,
        screenshot: bool = False,
        screenshot_base64: bool = False,
    ) -> dict:
        err = self._need_page()
        if err:
            return err
        await self.page.evaluate("([dx, dy]) => window.scrollBy(dx, dy)", [x, y])
        result = {"status": "ok"}
        result.update(await self._shot_fields(screenshot, screenshot_base64))
        return result

    async def wait(
        self,
        state: str = "load",
        selector: str = "",
        url: str = "",
        js: str = "",
        timeout: int = 10000,
    ) -> dict:
        err = self._need_page()
        if err:
            return err
        try:
            if js:
                await self.page.wait_for_function(js, timeout=timeout)
            elif selector:
                wait_state = state if state in ("visible", "hidden", "attached", "detached") else "visible"
                await (await self._locator(selector)).wait_for(state=wait_state, timeout=timeout)
            elif url:
                await self.page.wait_for_url(url, timeout=timeout)
            else:
                load_state = state if state in ("load", "domcontentloaded", "networkidle") else "load"
                await self.page.wait_for_load_state(load_state, timeout=timeout)
            return {"status": "ok", "url": self.page.url}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def execute(self, js_code: str) -> dict:
        err = self._need_page()
        if err:
            return err
        try:
            result = await self.page.evaluate(js_code)
            return {"status": "ok", "result": result}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def inject_script(self, script: str, url_pattern: str = "*"):
        err = self._need_context()
        if err:
            return err
        await self.context.add_init_script(script=wrap_init_script(script, url_pattern))
        return {"status": "ok", "message": "Script will run on matching new pages"}

    async def offscreen(self, action: str, url: str = "", js: str = "") -> dict:
        err = self._need_context()
        if err:
            return err
        if action == "open":
            self._offscreen_page = await self.context.new_page()
            if url:
                await self._offscreen_page.goto(url, wait_until="domcontentloaded")
            return {"status": "ok", "url": url or "blank", "offscreen": True}
        if action == "exec":
            if not self._offscreen_page:
                return {"status": "error", "message": "No offscreen page. Call action=open first."}
            result = await self._offscreen_page.evaluate(js)
            return {"status": "ok", "result": result}
        if action == "close":
            if self._offscreen_page:
                await self._offscreen_page.close()
                self._offscreen_page = None
            return {"status": "ok", "message": "Offscreen page closed"}
        return {"status": "error", "message": f"unknown action: {action}"}

    async def open_tab(self, url: str, *, wait_until: str = "domcontentloaded") -> dict:
        err = self._need_context()
        if err:
            return err
        try:
            page = await self.context.new_page()
            allowed = {"load", "domcontentloaded", "networkidle", "commit"}
            until = wait_until if wait_until in allowed else "domcontentloaded"
            response = await page.goto(url, wait_until=until, timeout=30000)
            title = await page.title()
            await self._adopt_page(page)
            return {
                "status": "ok",
                "title": title,
                "url": page.url,
                "status_code": response.status if response else None,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_tabs(self) -> list[dict]:
        tabs = []
        for i, p in enumerate(self._pages):
            try:
                title = await p.title()
                tabs.append({"index": i, "title": title, "url": p.url, "active": p == self.page})
            except Exception:
                tabs.append({"index": i, "title": "[closed]", "url": "", "active": False})
        return tabs

    async def switch_tab(self, index: int) -> dict:
        err = self._need_context()
        if err:
            return err
        if index < 0 or index >= len(self._pages):
            return {"status": "error", "message": f"tab {index} out of range (0-{len(self._pages) - 1})"}
        page = self._pages[index]
        if page.is_closed():
            return {"status": "error", "message": f"tab {index} is closed"}
        await self._adopt_page(page)
        return {"status": "ok", "index": index, "url": page.url, "title": await page.title()}

    def get_console(self) -> list[dict]:
        return list(self._console_logs)

    def get_errors(self) -> list[dict]:
        return list(self._page_errors)

    async def get_cookies(self, include_values: bool = False) -> dict:
        err = self._need_context()
        if err:
            return err
        cookies = await self.context.cookies()
        if include_values:
            return {"cookies": cookies, "count": len(cookies)}
        slim = [{"name": c.get("name"), "domain": c.get("domain"), "path": c.get("path")} for c in cookies]
        return {"cookies": slim, "count": len(slim)}

    async def set_cookie(self, name: str, value: str, domain: str = "", path: str = "/") -> dict:
        err = self._need_context()
        if err:
            return err
        cookie: dict[str, Any] = {"name": name, "value": value, "path": path}
        if domain:
            cookie["domain"] = domain
        elif self.page:
            cookie["url"] = self.page.url
        else:
            return {"status": "error", "message": "domain or an open page is required"}
        await self.context.add_cookies([cookie])
        return {"status": "ok", "cookie": {"name": name, "domain": domain or None, "path": path}}

    async def clear_cookies(self) -> dict:
        err = self._need_context()
        if err:
            return err
        await self.context.clear_cookies()
        return {"status": "ok", "message": "All cookies cleared"}

    async def storage(self, mode: str, storage: str = "local", key: str = "", value: str = "") -> dict:
        err = self._need_page()
        if err:
            return err
        store = "localStorage" if storage == "local" else "sessionStorage"
        if mode == "all":
            result = await self.page.evaluate(f"JSON.parse(JSON.stringify({store}))")
            return {"storage": storage, "data": result}
        if mode == "get":
            result = await self.page.evaluate(f"{store}.getItem({key!r})")
            return {"storage": storage, "key": key, "value": result}
        if mode == "set":
            await self.page.evaluate(f"{store}.setItem({key!r}, {value!r})")
            return {"storage": storage, "key": key, "value": value, "status": "set"}
        if mode == "clear":
            await self.page.evaluate(f"{store}.clear()")
            return {"storage": storage, "status": "cleared"}
        return {"status": "error", "message": f"unknown mode: {mode}"}

    async def handle_dialog(self, action: str = "accept", prompt: str = "") -> dict:
        armed = self._arm_dialog(action, prompt)
        if armed:
            return armed
        return {"status": "ok", "next_dialog": action}

    async def drag(self, source: str, target: str, *, timeout: int = 5000) -> dict:
        err = self._need_page()
        if err:
            return err
        try:
            src = await self._locator(source)
            dst = await self._locator(target)
            await src.drag_to(dst, timeout=timeout)
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def paste(self, selector: str, text: str) -> dict:
        err = self._need_page()
        if err:
            return err
        try:
            loc = await self._locator(selector)
            await loc.focus()
            await self.page.keyboard.insert_text(text)
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def set_files(self, selector: str, paths: str) -> dict:
        err = self._need_page()
        if err:
            return err
        files = [p.strip() for p in paths.split(",") if p.strip()]
        if not files:
            return {"status": "error", "message": "no file paths"}
        missing = [p for p in files if not os.path.exists(p)]
        if missing:
            return {"status": "error", "message": f"missing files: {missing}"}
        await (await self._locator(selector)).set_input_files(files)
        return {"status": "ok", "files": [os.path.basename(p) for p in files]}

    async def click_download(self, selector: str, save_as: str = "", timeout: int = 30000) -> dict:
        err = self._need_page()
        if err:
            return err
        dest_dir = os.path.join(os.getcwd(), "artifacts", "downloads")
        os.makedirs(dest_dir, exist_ok=True)
        async with self.page.expect_download(timeout=timeout) as pending:
            await (await self._locator(selector)).click(timeout=min(timeout, 15000))
        download = await pending.value
        filename = save_as or download.suggested_filename
        path = os.path.join(dest_dir, safe_artifact_name(filename, "download"))
        await download.save_as(path)
        return {"status": "ok", "path": path, "filename": os.path.basename(path)}

    async def select_option(self, selector: str, value: str = "", label: str = "", index: int = -1) -> dict:
        err = self._need_page()
        if err:
            return err
        loc = await self._locator(selector)
        if value:
            await loc.select_option(value=value)
        elif label:
            await loc.select_option(label=label)
        elif index >= 0:
            await loc.select_option(index=index)
        else:
            return {"status": "error", "message": "provide value, label, or index"}
        return {"status": "ok"}

    async def press(self, selector: str, key: str) -> dict:
        err = self._need_page()
        if err:
            return err
        await (await self._locator(selector)).press(key)
        return {"status": "ok", "key": key}

    async def hover(self, selector: str) -> dict:
        err = self._need_page()
        if err:
            return err
        await (await self._locator(selector)).hover()
        return {"status": "ok"}

    async def reload(self, wait_until: str = "domcontentloaded") -> dict:
        err = self._need_page()
        if err:
            return err
        allowed = {"load", "domcontentloaded", "networkidle", "commit"}
        until = wait_until if wait_until in allowed else "domcontentloaded"
        await self.page.reload(wait_until=until)
        return {"status": "ok", "url": self.page.url, "title": await self.page.title()}

    async def run_actions(self, actions: list[dict], *, screenshot: bool = False) -> dict:
        results = []
        for raw in actions:
            action = (raw.get("action") or raw.get("tool") or "").replace("browser_", "")
            try:
                result = await self._run_one(action, raw)
            except Exception as e:
                result = {"status": "error", "message": str(e)}
            results.append({"action": action, **result})
            if result.get("status") == "error":
                return {"status": "error", "failed_at": action, "results": results}
        out = {"status": "ok", "results": results}
        out.update(await self._shot_fields(screenshot, False))
        return out

    async def _run_one(self, action: str, raw: dict) -> dict:
        if action == "open":
            await self.ensure_started()
            return await self.open(raw["url"], wait_until=raw.get("wait_until", "domcontentloaded"))
        if action == "click":
            return await self.click(
                raw["selector"],
                dialog=raw.get("dialog", ""),
                prompt=raw.get("prompt", ""),
                popup=bool(raw.get("popup")),
                timeout=int(raw.get("timeout", 15000 if raw.get("popup") else 5000)),
            )
        if action == "type":
            return await self.type_text(raw["selector"], raw.get("text", ""))
        if action == "paste":
            return await self.paste(raw["selector"], raw.get("text", ""))
        if action == "drag":
            return await self.drag(raw.get("source") or raw["selector"], raw["target"])
        if action == "scroll":
            return await self.scroll(int(raw.get("x", 0)), int(raw.get("y", 200)))
        if action == "wait":
            return await self.wait(
                state=raw.get("state", "load"),
                selector=raw.get("selector", ""),
                url=raw.get("url", ""),
                js=raw.get("js") or raw.get("js_code") or "",
                timeout=int(raw.get("timeout", 10000)),
            )
        if action in ("switch_tab", "tab"):
            return await self.switch_tab(int(raw["index"]))
        if action == "execute":
            return await self.execute(raw.get("js") or raw.get("js_code") or "")
        if action == "snapshot":
            return await self.snapshot(raw.get("scope", "viewport"))
        if action == "screenshot":
            return await self.screenshot()
        if action == "reload":
            return await self.reload(raw.get("wait_until", "domcontentloaded"))
        if action == "press":
            return await self.press(raw["selector"], raw.get("key", "Enter"))
        if action == "hover":
            return await self.hover(raw["selector"])
        if action == "select":
            return await self.select_option(
                raw["selector"],
                value=raw.get("value", ""),
                label=raw.get("label", ""),
                index=int(raw.get("index", -1)),
            )
        if action in ("set_files", "upload"):
            return await self.set_files(raw["selector"], raw.get("paths") or raw.get("files") or "")
        if action == "download":
            return await self.click_download(raw["selector"], raw.get("save_as", ""))
        if action == "dialog":
            return await self.handle_dialog(raw.get("handle") or "accept", raw.get("prompt", ""))
        if action in ("extract_dom", "extract"):
            from tools.dom_extractor import classify_inputs
            from tools.payload import compact_classified
            elements = await self.extract_dom()
            if isinstance(elements, dict) and elements.get("status") == "error":
                return elements
            return {"status": "ok", **compact_classified(classify_inputs(elements))}
        return {"status": "error", "message": f"unknown action: {action}"}

    async def _script_rpc(self, method: str, params: dict) -> dict:
        if method == "open":
            if self.page is None:
                await self.ensure_started()
            return await self.open(params["url"], wait_until=params.get("wait_until", "domcontentloaded"))
        if method == "click":
            return await self.click(
                params["selector"],
                dialog=params.get("dialog", ""),
                prompt=params.get("prompt", ""),
                popup=bool(params.get("popup")),
            )
        if method == "type":
            return await self.type_text(params["selector"], params.get("text", ""))
        if method == "snapshot":
            return await self.snapshot(params.get("scope", "viewport"))
        if method == "wait":
            return await self.wait(
                state=params.get("state", "load"),
                selector=params.get("selector", ""),
                url=params.get("url", ""),
                js=params.get("js") or params.get("js_code") or "",
                timeout=int(params.get("timeout", 10000)),
            )
        if method == "execute":
            return await self.execute(params.get("js_code") or params.get("js") or "")
        if method == "press":
            return await self.press(params["selector"], params.get("key", "Enter"))
        if method == "hover":
            return await self.hover(params["selector"])
        if method == "scroll":
            return await self.scroll(int(params.get("x", 0)), int(params.get("y", 200)))
        if method == "reload":
            return await self.reload(params.get("wait_until", "domcontentloaded"))
        if method == "paste":
            return await self.paste(params["selector"], params.get("text", ""))
        if method == "drag":
            return await self.drag(params.get("source") or params["selector"], params["target"])
        return {"status": "error", "message": f"unknown helper: {method}"}

    async def run_script(self, js_code: str, timeout: int = 60000) -> dict:
        if not (js_code or "").strip():
            return {"status": "error", "message": "js_code is empty"}
        if self.page is None:
            await self.ensure_started()
        host = Path(__file__).resolve().parents[1] / "script-host.mjs"
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(host),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdin and proc.stdout
        proc.stdin.write((json.dumps({"type": "script", "code": js_code}) + "\n").encode())
        await proc.stdin.drain()
        logs: list[str] = []
        loop = asyncio.get_event_loop()
        deadline = loop.time() + max(timeout, 1000) / 1000
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    proc.kill()
                    return {"status": "error", "message": "script timeout", "logs": logs[-20:]}
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
                if not line:
                    err_out = await proc.stderr.read()
                    return {
                        "status": "error",
                        "message": (err_out.decode()[:500] if err_out else "script host exited"),
                        "logs": logs[-20:],
                    }
                msg = json.loads(line)
                kind = msg.get("type")
                if kind == "log":
                    logs.append(msg.get("text") or "")
                elif kind == "rpc":
                    try:
                        result = await self._script_rpc(msg.get("method") or "", msg.get("params") or {})
                        proc.stdin.write(
                            (json.dumps({"type": "ok", "id": msg["id"], "result": result}) + "\n").encode()
                        )
                    except Exception as e:
                        proc.stdin.write(
                            (json.dumps({"type": "err", "id": msg["id"], "message": str(e)}) + "\n").encode()
                        )
                    await proc.stdin.drain()
                elif kind == "done":
                    return {"status": "ok", "result": msg.get("result"), "logs": (msg.get("logs") or logs)[-20:]}
                elif kind == "error":
                    return {
                        "status": "error",
                        "message": msg.get("message") or "script error",
                        "logs": (msg.get("logs") or logs)[-20:],
                    }
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    async def close(self, shutdown: bool = True):
        from tools.persist import clear_state, kill_pid

        if self.persist and not shutdown:
            if self._pw:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
            self.browser = None
            self.context = None
            self.page = None
            self._pw = None
            self._pages.clear()
            self._refs.clear()
            self._listened_pages.clear()
            return

        try:
            if self._offscreen_page:
                await self._offscreen_page.close()
        except Exception:
            pass
        self._offscreen_page = None
        if self.context and not self.persist:
            try:
                await self.context.close()
            except Exception:
                pass
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        if self.persist and shutdown:
            kill_pid(self._chrome_pid or 0)
            clear_state(self.name)
        self.browser = None
        self.context = None
        self.page = None
        self._pw = None
        self._console_logs.clear()
        self._page_errors.clear()
        self._network_logs.clear()
        self._network_capturing = False
        self._blocked_patterns = []
        self._pages.clear()
        self._refs.clear()
        self._shot_n = 0
        self._dialog_action = "dismiss"
        self._dialog_prompt = ""
        self._last_dialog = None
        self._listened_pages.clear()
        self._block_route_installed = False
        self._cdp_port = None
        self._chrome_pid = None
        self.persist = False


from tools.registry import SessionRegistry

registry = SessionRegistry(lambda name="default": BrowserSession(name=name))


async def get_session(name: str = ""):
    return registry.get(name)
