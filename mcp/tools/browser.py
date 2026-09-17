from __future__ import annotations

import asyncio
import base64
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from tools.assertion import (
    as_bool,
    batch_halt,
    clip_actual,
    describe,
    evaluate,
    normalize_expect,
    validate_assert,
    verdict,
)
from tools.image_diff import compare_png
from tools.parallel import parse_parallel_jobs, settle_parallel
from tools.payload import (
    SNAPSHOT_SELECTOR,
    SMOKE_VERSION,
    cap_append,
    cap_snapshot_items,
    classify_target_error,
    classify_type_error,
    format_snapshot_lines,
    matches_url,
    parse_aria_snapshot,
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
      if (t === "file") return "file";
      if (t === "submit" || t === "button") return "button";
      if (t === "checkbox") return "checkbox";
      if (t === "radio") return "radio";
      return "textbox";
    }
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (el.isContentEditable) return "textbox";
    return el.getAttribute("role") || tag;
  };
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    if (!full && (rect.bottom < 0 || rect.top > window.innerHeight)) return false;
    return true;
  };
  const push = (el, hidden) => {
    const role = el.getAttribute("role") || implicit(el);
    const name = (
      el.getAttribute("aria-label") ||
      el.getAttribute("placeholder") ||
      el.getAttribute("alt") ||
      (el.value && String(el.value)) ||
      (el.textContent || "")
    ).trim().replace(/\\s+/g, " ").slice(0, 60);
    el.setAttribute("data-bs-ref", String(n));
    const item = {
      ref: n,
      role,
      name,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type") || undefined,
      href: el.getAttribute("href") || undefined,
    };
    if (hidden) item.hidden = true;
    items.push(item);
    n += 1;
  };
  document.querySelectorAll("[data-bs-ref]").forEach((el) => el.removeAttribute("data-bs-ref"));
  const selector = __SNAPSHOT_SELECTOR__;
  const items = [];
  let n = start;
  document.querySelectorAll(selector).forEach((el) => {
    if (!visible(el)) return;
    push(el, false);
  });
  document.querySelectorAll('input[type="file"]').forEach((el) => {
    if (el.hasAttribute("data-bs-ref")) return;
    push(el, true);
  });
  return {items, next: n};
}
""".replace("__SNAPSHOT_SELECTOR__", json.dumps(SNAPSHOT_SELECTOR))


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
    persist: bool = True
    attached: bool = False
    mode: str = "persist"
    _cdp_port: Optional[int] = None
    _chrome_pid: Optional[int] = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

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
        persist: bool = True,
        cdp: str = "",
    ):
        from tools.persist import (
            allocate_port,
            cdp_alive,
            chrome_executable,
            kill_pid,
            normalize_cdp_endpoint,
            persist_preferred_port,
            persist_profile,
            pid_on_port,
            read_state,
            resolve_launch_mode,
            spawn_chromium,
            state_dir,
            write_state,
        )

        mode = resolve_launch_mode(persist=persist, cdp=cdp, channel=channel)
        persist = bool(mode["persist"])
        cdp = str(mode["cdp"])
        channel = str(mode["channel"])
        self.mode = str(mode["mode"])
        self.persist = persist
        self.attached = False
        self._pw = await async_playwright().start()
        os.makedirs(os.path.join(os.getcwd(), "artifacts", "downloads"), exist_ok=True)
        if cdp:
            endpoint = normalize_cdp_endpoint(cdp)
            try:
                self.browser = await self._pw.chromium.connect_over_cdp(endpoint)
            except Exception as e:
                if self._pw:
                    try:
                        await self._pw.stop()
                    except Exception:
                        pass
                    self._pw = None
                raise RuntimeError(
                    "CDP connect failed. Chrome 136+ ignores --remote-debugging-port on the "
                    "daily profile (Gmail in your normal Chrome). Quit that Chrome, launch a "
                    "separate debug Chrome with --remote-debugging-port=9222 and a non-default "
                    f"--user-data-dir, then retry. ({e})"
                ) from e
            self.attached = True
            if self.browser.contexts:
                self.context = self.browser.contexts[0]
            else:
                self.context = await self.browser.new_context(accept_downloads=True)
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            self._bind_io()
            return
        if persist:
            profile = persist_profile(self.name, user_data_dir)
            os.makedirs(profile, exist_ok=True)
            state = read_state(self.name)
            saved_port = int(state.get("port") or 0)
            saved_dir = os.path.abspath(str(state.get("user_data_dir") or ""))
            spawned = False
            pid = int(state.get("pid") or 0)
            port = saved_port
            prefer = persist_preferred_port(self.name)
            try:
                if prefer and cdp_alive(prefer):
                    port = prefer
                    pid = pid_on_port(port) or pid
                elif saved_port and cdp_alive(saved_port) and (not saved_dir or saved_dir == profile):
                    port = saved_port
                    pid = pid_on_port(port) or pid
                else:
                    port = allocate_port(self.name, prefer or saved_port)
                    if cdp_alive(port):
                        pid = pid_on_port(port) or pid
                    else:
                        chrome = chrome_executable()
                        exe = chrome or self._pw.chromium.executable_path
                        log_path = os.path.join(state_dir(), f"{self.name}.spawn.log")
                        pid = spawn_chromium(
                            exe,
                            port,
                            profile,
                            headless=headless,
                            log_path=log_path,
                            disable_sync=not bool(chrome),
                        )
                        spawned = True
                self.browser = await self._pw.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}"
                )
                if self.browser.contexts:
                    self.context = self.browser.contexts[0]
                else:
                    self.context = await self.browser.new_context(
                        viewport={"width": 1280, "height": 720},
                        accept_downloads=True,
                    )
                self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
                try:
                    await self.page.set_viewport_size({"width": 1280, "height": 720})
                except Exception:
                    pass
                self._cdp_port = port
                self._chrome_pid = pid
                self._bind_io()
                write_state(
                    self.name,
                    {"port": port, "pid": pid, "user_data_dir": profile},
                )
                return
            except Exception:
                if spawned:
                    kill_pid(pid)
                if self._pw:
                    try:
                        await self._pw.stop()
                    except Exception:
                        pass
                    self._pw = None
                raise
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
        persist: bool | None = None,
        cdp: str = "",
    ):
        if self.page is None:
            await self.start(
                headless=headless,
                channel=channel,
                user_data_dir=user_data_dir,
                persist=self.persist if persist is None else persist,
                cdp=cdp,
            )

    def _need_page(self) -> dict | None:
        if self.page is None:
            return {
                "status": "error",
                "code": "no_session",
                "message": "No page open. Call browser_open first.",
            }
        return None

    def _need_context(self) -> dict | None:
        if self.context is None:
            return {
                "status": "error",
                "code": "no_session",
                "message": "No browser session. Call browser_open first.",
            }
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

    def _resolve_locator(self, selector: str):
        target = self._target(selector)
        if isinstance(target, str):
            return self.page.locator(target)
        frame = target.get("frame") or ""
        if frame:
            return self.page.frame_locator(frame).locator(target["sel"])
        return self.page.locator(target["sel"])

    async def _locator(self, selector: str, *, hidden_ok: bool = False):
        is_ref = selector.startswith("@") and selector[1:].isdigit()
        loc = self._resolve_locator(selector)
        count = await loc.count()
        if is_ref and count == 0:
            raise ValueError(f"Expired ref {selector}. Call browser_snapshot again.")
        if count <= 1 or hidden_ok:
            return loc.first
        for i in range(count):
            nth = loc.nth(i)
            try:
                if await nth.is_visible():
                    return nth
            except Exception:
                continue
        return loc.last

    async def _bring_into_view(self, loc) -> None:
        try:
            await loc.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            return

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

    async def _refs_fields(self) -> dict:
        snap = await self.snapshot()
        if snap.get("status") == "error":
            return {}
        out = {"snapshot": snap.get("snapshot"), "count": snap.get("count")}
        if snap.get("truncated"):
            out["truncated"] = True
            out["total"] = snap.get("total")
        return out

    async def open(
        self,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        screenshot: bool = False,
        screenshot_base64: bool = False,
        refs: bool = False,
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
                "session": self.name,
                "persist": self.persist,
                "attached": self.attached,
                "mode": self.mode,
                "version": SMOKE_VERSION,
            }
            result.update(await self._shot_fields(screenshot, screenshot_base64))
            if refs:
                result.update(await self._refs_fields())
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
        items = await self._snapshot_aria(full)
        if items:
            items = await self._supplement_aria(items)
        else:
            items = await self._snapshot_dom(full)
        shown, total = cap_snapshot_items(items)
        self._refs = {}
        for item in shown:
            sel = item.get("sel")
            if not sel:
                continue
            self._refs[str(item["ref"])] = {
                "sel": sel,
                "frame": item.get("frame") or "",
            }
        out = {
            "status": "ok",
            "url": self.page.url,
            "count": len(shown),
            "snapshot": format_snapshot_lines(shown),
        }
        if total > len(shown):
            out["truncated"] = True
            out["total"] = total
        return out

    async def _snapshot_aria(self, full: bool) -> list[dict]:
        loc = self.page.locator(":root")
        try:
            if full:
                yaml_text = await loc.aria_snapshot(mode="ai", timeout=8000)
                viewport = None
            else:
                yaml_text = await loc.aria_snapshot(mode="ai", boxes=True, timeout=8000)
                viewport = await self.page.evaluate(
                    "() => ({width: window.innerWidth, height: window.innerHeight})"
                )
        except TypeError:
            return []
        except Exception:
            return []
        if not yaml_text or "[ref=" not in yaml_text:
            return []
        items = parse_aria_snapshot(
            yaml_text, start=1, viewport=None if full else viewport
        )
        if not full and viewport and not items:
            items = parse_aria_snapshot(yaml_text, start=1, viewport=None)
        return items

    async def _supplement_aria(self, items: list[dict]) -> list[dict]:
        n = max((int(i.get("ref") or 0) for i in items), default=0) + 1
        try:
            file_count = await self.page.locator('input[type="file"]').count()
        except Exception:
            file_count = 0
        has_file = any(x.get("role") == "file" or x.get("type") == "file" for x in items)
        if file_count and not has_file:
            for i in range(file_count):
                loc = self.page.locator('input[type="file"]').nth(i)
                name = (
                    (await loc.get_attribute("aria-label"))
                    or (await loc.get_attribute("name"))
                    or "file"
                )
                items.append(
                    {
                        "ref": n,
                        "role": "file",
                        "name": str(name)[:60],
                        "hidden": True,
                        "type": "file",
                        "sel": f'input[type="file"] >> nth={i}',
                    }
                )
                n += 1
        try:
            count = await self.page.locator("iframe").count()
        except Exception:
            count = 0
        for i in range(count):
            frame_loc = self.page.locator("iframe").nth(i)
            src = (await frame_loc.get_attribute("src")) or ""
            handle = await frame_loc.element_handle()
            content = await handle.content_frame() if handle else None
            if content is not None:
                continue
            items.append(
                {
                    "ref": n,
                    "role": "iframe",
                    "name": "cross-origin",
                    "href": src[:80],
                    "iframe": True,
                }
            )
            n += 1
        return items

    async def _snapshot_dom(self, full: bool) -> list[dict]:
        items: list[dict] = []
        payload = await self.page.evaluate(SNAPSHOT_JS, {"full": full, "start": 1})
        n = payload["next"]
        for item in payload["items"]:
            item["sel"] = f'[data-bs-ref="{item["ref"]}"]'
            items.append(item)
        count = await self.page.locator("iframe").count()
        for i in range(count):
            frame_loc = self.page.locator("iframe").nth(i)
            src = (await frame_loc.get_attribute("src")) or ""
            handle = await frame_loc.element_handle()
            if handle is None:
                continue
            content = await handle.content_frame()
            if content is None:
                items.append(
                    {
                        "ref": n,
                        "role": "iframe",
                        "name": "cross-origin",
                        "href": src[:80],
                        "iframe": True,
                    }
                )
                n += 1
                continue
            try:
                payload = await content.evaluate(SNAPSHOT_JS, {"full": full, "start": n})
            except Exception:
                items.append(
                    {
                        "ref": n,
                        "role": "iframe",
                        "name": "cross-origin",
                        "href": src[:80],
                        "iframe": True,
                    }
                )
                n += 1
                continue
            n = payload["next"]
            frame_sel = f"iframe >> nth={i}"
            for item in payload["items"]:
                item["iframe"] = True
                item["sel"] = f'[data-bs-ref="{item["ref"]}"]'
                item["frame"] = frame_sel
                items.append(item)
        return items

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
            await self._bring_into_view(loc)
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
            err = classify_target_error(msg)
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
            loc = await self._locator(selector)
            await self._bring_into_view(loc)
            await loc.fill(text, timeout=timeout)
            result = {"status": "ok"}
            result.update(await self._shot_fields(screenshot, screenshot_base64))
            return result
        except Exception as e:
            return classify_type_error(str(e))

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
        selector: str = "",
        *,
        screenshot: bool = False,
        screenshot_base64: bool = False,
    ) -> dict:
        err = self._need_page()
        if err:
            return err
        try:
            if selector:
                loc = await self._locator(selector)
                await loc.scroll_into_view_if_needed(timeout=5000)
                result = {
                    "status": "ok",
                    "scrolled": selector,
                    "hint": "Call browser_snapshot again. Viewport @refs changed.",
                }
            else:
                await self.page.evaluate("([dx, dy]) => window.scrollBy(dx, dy)", [x, y])
                result = {
                    "status": "ok",
                    "x": x,
                    "y": y,
                    "hint": "Call browser_snapshot again. Viewport @refs changed.",
                }
            result.update(await self._shot_fields(screenshot, screenshot_base64))
            return result
        except Exception as e:
            return classify_target_error(str(e))

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

    async def assert_condition(
        self,
        expect: str,
        text: str = "",
        selector: str = "",
        count: int = 0,
        timeout: int = 5000,
        negate: bool = False,
    ) -> dict:
        err = self._need_page()
        if err:
            return err
        negate = as_bool(negate)
        try:
            count_i = int(count or 0)
            timeout_ms = int(timeout if timeout is not None else 5000)
        except (TypeError, ValueError):
            return {"status": "error", "message": "count and timeout must be integers"}
        timeout_ms = max(0, timeout_ms)
        bad = validate_assert(expect=expect, selector=selector, text=text)
        if bad:
            return bad
        kind = normalize_expect(expect)
        line, expected = describe(
            expect=kind, selector=selector, text=text, count=count_i, negate=negate
        )
        try:
            passed, actual = await self._assert_poll(
                kind, text, selector, count_i, timeout_ms, negate
            )
        except ValueError as e:
            return classify_target_error(str(e))
        except Exception as e:
            classified = classify_target_error(str(e))
            if classified.get("code"):
                return classified
            passed, actual = False, clip_actual(str(e))
        return verdict(assert_line=line, expected=expected, actual=actual, passed=passed)

    async def _assert_poll(
        self,
        kind: str,
        text: str,
        selector: str,
        count: int,
        timeout_ms: int,
        negate: bool,
    ) -> tuple[bool, str]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_ms / 1000
        last_actual = ""
        while True:
            remaining = deadline - loop.time()
            wait_ms = 1 if remaining <= 0 else min(1000, max(1, int(remaining * 1000)))
            ok, actual = await self._assert_once(
                kind, text, selector, count, negate, wait_ms
            )
            if ok:
                return True, actual
            last_actual = actual
            remaining = deadline - loop.time()
            if remaining <= 0:
                if timeout_ms > 0:
                    return False, f"{last_actual} after {timeout_ms}ms"
                return False, last_actual
            await asyncio.sleep(min(0.1, remaining))

    async def _assert_once(
        self,
        kind: str,
        text: str,
        selector: str,
        count: int,
        negate: bool,
        wait_ms: int = 1000,
    ) -> tuple[bool, str]:
        if kind == "url":
            observed = self.page.url
            ok = evaluate("url", observed=observed, expected_text=text, negate=negate)
            return ok, observed
        if kind == "count":
            loc = self._resolve_locator(selector)
            n = await loc.count()
            ok = evaluate("count", observed=n, expected_count=count, negate=negate)
            return ok, str(n)
        if kind == "text":
            loc = self._resolve_locator((selector or "").strip() or "body")
            n = await loc.count()
            observed = ""
            if n > 0:
                try:
                    observed = await loc.first.inner_text(timeout=wait_ms)
                except Exception:
                    observed = ""
            ok = evaluate("text", observed=observed, expected_text=text, negate=negate)
            where = (selector or "").strip() or "body"
            if ok:
                return True, f"not found in {where}" if negate else f"found in {where}"
            return False, clip_actual(observed) or "not found"
        if kind == "input_value":
            loc = self._resolve_locator((selector or "").strip() or "input, textarea, select")
            n = await loc.count()
            if n == 0:
                ok = evaluate("input_value", observed="", expected_text=text, negate=negate)
                return ok, "no input"
            try:
                observed = await loc.first.input_value(timeout=wait_ms)
            except Exception as e:
                return False, clip_actual(str(e))
            ok = evaluate("input_value", observed=observed, expected_text=text, negate=negate)
            return ok, clip_actual(observed) if observed else '""'
        if kind in ("visible", "hidden"):
            loc = self._resolve_locator(selector)
            n = await loc.count()
            is_vis = False
            if n > 0:
                try:
                    is_vis = await loc.first.is_visible()
                except Exception:
                    is_vis = False
            if kind == "visible":
                observed = is_vis
                actual = "visible" if is_vis else ("detached" if n == 0 else "hidden")
            else:
                observed = n == 0 or not is_vis
                actual = "detached" if n == 0 else ("hidden" if not is_vis else "visible")
            ok = evaluate(kind, observed=observed, negate=negate)
            return ok, actual
        return False, f"unknown expect: {kind}"

    async def execute(self, js_code: str) -> dict:
        err = self._need_page()
        if err:
            return err
        return await self._eval_page(self.page, js_code)

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

    def _live_tab_indexes(self) -> list[int]:
        indexes = []
        for i, page in enumerate(self._pages):
            if page is self._offscreen_page:
                continue
            try:
                if page.is_closed():
                    continue
            except Exception:
                continue
            indexes.append(i)
        return indexes

    def _page_index(self, page: Page) -> int | None:
        try:
            return self._pages.index(page)
        except ValueError:
            return None

    async def _eval_page(self, page: Page, js_code: str) -> dict:
        try:
            result = await page.evaluate(js_code)
            return {"status": "ok", "result": result}
        except Exception as e:
            msg = str(e)
            err = {"status": "error", "message": msg}
            if "serializ" in msg.lower():
                err["hint"] = "Return a JSON object, array, or string — not a DOM node or function."
            return err

    async def _parallel_one(self, job: dict) -> dict:
        url = str(job.get("url") or "").strip()
        js = str(job.get("js") or "")
        tab = job.get("tab")
        page: Optional[Page] = None
        try:
            if url:
                page = await self.context.new_page()
                self._on_new_page(page)
                response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                status_code = response.status if response else None
            else:
                idx = int(tab)
                if idx < 0 or idx >= len(self._pages):
                    return {
                        "status": "error",
                        "tab": idx,
                        "message": f"tab {idx} out of range (0-{max(len(self._pages) - 1, 0)})",
                    }
                page = self._pages[idx]
                if page.is_closed():
                    return {"status": "error", "tab": idx, "message": f"tab {idx} is closed"}
                status_code = None
            title = await page.title()
            out: dict[str, Any] = {
                "status": "ok",
                "url": page.url,
                "title": title,
            }
            index = self._page_index(page)
            if index is not None:
                out["index"] = index
            if status_code is not None:
                out["status_code"] = status_code
            if js:
                evaluated = await self._eval_page(page, js)
                if evaluated.get("status") == "ok":
                    out["result"] = evaluated.get("result")
                else:
                    evaluated.pop("status", None)
                    out["status"] = "error"
                    out.update(evaluated)
            return out
        except Exception as e:
            err = {"status": "error", "message": str(e)}
            if url:
                err["url"] = url
            elif tab is not None:
                err["tab"] = tab
            return err

    async def run_parallel(self, jobs: list[dict]) -> dict:
        needs_url = any(str(job.get("url") or "").strip() for job in jobs)
        if self.context is None:
            if not needs_url:
                return {
                    "status": "error",
                    "code": "no_session",
                    "message": "No browser session. Call browser_open first.",
                }
            try:
                await self.ensure_started()
            except Exception as e:
                return {"status": "error", "message": str(e)}
        err = self._need_context()
        if err:
            return err
        focused = self.page
        gathered = await asyncio.gather(
            *[self._parallel_one(job) for job in jobs],
            return_exceptions=True,
        )
        results: list[dict] = []
        for item in gathered:
            if isinstance(item, Exception):
                results.append({"status": "error", "message": str(item)})
            else:
                results.append(item)
        if focused is not None:
            try:
                if not focused.is_closed():
                    self.page = focused
            except Exception:
                pass
        elif self.page is None:
            for page in self._pages:
                if page is self._offscreen_page:
                    continue
                try:
                    if not page.is_closed():
                        self.page = page
                        break
                except Exception:
                    continue
        return settle_parallel(results)

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

    async def _find_file_input(self):
        loc = self.page.locator('input[type="file"]')
        if await loc.count():
            return loc.first
        for frame in self.page.frames:
            if frame == self.page.main_frame:
                continue
            fl = frame.locator('input[type="file"]')
            try:
                if await fl.count():
                    return fl.first
            except Exception:
                continue
        return None

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
        loc = None
        if selector.strip():
            try:
                loc = await self._locator(selector, hidden_ok=True)
                await loc.set_input_files(files)
                return {"status": "ok", "files": [os.path.basename(p) for p in files]}
            except Exception:
                loc = None
        found = await self._find_file_input()
        if found is None:
            return {
                "status": "error",
                "message": (
                    "No input[type=file] in this document (hidden inputs included). "
                    "A Google/OS picker iframe is cross-origin and cannot be filled. "
                    "Save the file with browser_download url=... then insert by URL/HTML, "
                    "or set_files on a snapshot ref tagged file hidden."
                ),
            }
        await found.set_input_files(files)
        return {"status": "ok", "files": [os.path.basename(p) for p in files], "auto": True}

    async def save_url(self, url: str, save_as: str = "") -> dict:
        err = self._need_context()
        if err:
            return err
        dest_dir = os.path.join(os.getcwd(), "artifacts", "downloads")
        os.makedirs(dest_dir, exist_ok=True)
        try:
            resp = await self.context.request.get(url)
        except Exception as e:
            return {"status": "error", "message": str(e)}
        if not resp.ok:
            return {"status": "error", "message": f"HTTP {resp.status}", "url": url}
        body = await resp.body()
        ctype = (resp.headers.get("content-type") or "").split(";")[0].strip()
        guessed = save_as
        if not guessed:
            path_name = url.split("?", 1)[0].rstrip("/").split("/")[-1] or "download"
            if "." not in path_name:
                ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(
                    ctype, ""
                )
                path_name = path_name + ext
            guessed = path_name
        path = os.path.join(dest_dir, safe_artifact_name(guessed, "download"))
        with open(path, "wb") as f:
            f.write(body)
        return {
            "status": "ok",
            "path": path,
            "filename": os.path.basename(path),
            "bytes": len(body),
            "content_type": ctype,
            "url": url,
        }

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
        await self._bring_into_view(loc)
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
        try:
            loc = await self._locator(selector)
            await self._bring_into_view(loc)
            await loc.hover()
            return {"status": "ok"}
        except Exception as e:
            return classify_target_error(str(e))

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
            if batch_halt(result.get("status") or ""):
                return {"status": result.get("status"), "failed_at": action, "results": results}
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
            return await self.scroll(
                int(raw.get("x", 0) or 0),
                int(raw.get("y", 200) if raw.get("y") is not None else 200),
                selector=str(raw.get("selector") or ""),
            )
        if action == "wait":
            return await self.wait(
                state=raw.get("state", "load"),
                selector=raw.get("selector", ""),
                url=raw.get("url", ""),
                js=raw.get("js") or raw.get("js_code") or "",
                timeout=int(raw.get("timeout", 10000)),
            )
        if action == "assert":
            return await self.assert_condition(
                expect=str(raw.get("expect") or ""),
                text=str(raw.get("text") or ""),
                selector=str(raw.get("selector") or ""),
                count=raw.get("count", 0),
                timeout=raw.get("timeout", 5000),
                negate=raw.get("negate", False),
            )
        if action in ("switch_tab", "tab"):
            return await self.switch_tab(int(raw["index"]))
        if action == "parallel":
            urls = raw.get("urls") or ""
            tabs = raw.get("tabs") or ""
            jobs = raw.get("jobs_json") or raw.get("jobs") or ""
            if isinstance(urls, list):
                urls = json.dumps(urls)
            if isinstance(tabs, list):
                tabs = json.dumps(tabs)
            if isinstance(jobs, (list, dict)):
                jobs = json.dumps(jobs)
            parsed = parse_parallel_jobs(
                urls=urls,
                js_code=raw.get("js") or raw.get("js_code") or "",
                jobs_json=jobs,
                tabs=tabs,
                existing_tabs=self._live_tab_indexes(),
            )
            if parsed.get("status") == "error":
                return parsed
            return await self.run_parallel(parsed["jobs"])
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
            return await self.set_files(
                raw.get("selector") or "",
                raw.get("paths") or raw.get("files") or "",
            )
        if action == "download":
            if raw.get("url"):
                return await self.save_url(raw["url"], raw.get("save_as", ""))
            return await self.click_download(raw.get("selector") or "", raw.get("save_as", ""))
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

    async def _script_rpc(self, method: str, params: object) -> dict:
        from tools.script_rpc import coerce_rpc_params

        params = coerce_rpc_params(method, params)
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
        if method == "assert":
            return await self.assert_condition(
                expect=str(params.get("expect") or ""),
                text=str(params.get("text") or ""),
                selector=str(params.get("selector") or ""),
                count=params.get("count", 0),
                timeout=params.get("timeout", 5000),
                negate=params.get("negate", False),
            )
        if method == "execute":
            return await self.execute(params.get("js_code") or params.get("js") or "")
        if method == "press":
            return await self.press(params["selector"], params.get("key", "Enter"))
        if method == "hover":
            return await self.hover(params["selector"])
        if method == "scroll":
            y = params.get("y")
            return await self.scroll(
                int(params.get("x", 0) or 0),
                int(y if y is not None else 200),
                selector=str(params.get("selector") or ""),
            )
        if method == "reload":
            return await self.reload(params.get("wait_until", "domcontentloaded"))
        if method == "paste":
            return await self.paste(params["selector"], params.get("text", ""))
        if method == "drag":
            return await self.drag(params.get("source") or params["selector"], params["target"])
        if method == "dialog":
            return await self.handle_dialog(params.get("handle") or params.get("action") or "accept", params.get("prompt", ""))
        if method == "download":
            if params.get("url"):
                return await self.save_url(params["url"], params.get("save_as", ""))
            return await self.click_download(params.get("selector") or "", params.get("save_as", ""))
        if method in ("set_files", "upload"):
            return await self.set_files(
                params.get("selector") or "",
                params.get("paths") or params.get("files") or "",
            )
        if method == "select":
            return await self.select_option(
                params["selector"],
                value=params.get("value", ""),
                label=params.get("label", ""),
                index=int(params.get("index", -1)),
            )
        if method == "switch_tab":
            return await self.switch_tab(int(params["index"]))
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
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(timeout, 1000) / 1000
        finished = False
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
                    method = msg.get("method") or ""
                    try:
                        result = await self._script_rpc(method, msg.get("params"))
                        if method == "assert" and batch_halt(result.get("status") or ""):
                            out = dict(result)
                            if logs:
                                out["logs"] = logs[-20:]
                            return out
                        proc.stdin.write(
                            (
                                json.dumps(
                                    {"type": "ok", "id": msg["id"], "result": result},
                                    default=str,
                                )
                                + "\n"
                            ).encode()
                        )
                    except Exception as e:
                        proc.stdin.write(
                            (json.dumps({"type": "err", "id": msg["id"], "message": str(e)}) + "\n").encode()
                        )
                    await proc.stdin.drain()
                elif kind == "done":
                    finished = True
                    return {"status": "ok", "result": msg.get("result"), "logs": (msg.get("logs") or logs)[-20:]}
                elif kind == "error":
                    finished = True
                    return {
                        "status": "error",
                        "message": msg.get("message") or "script error",
                        "logs": (msg.get("logs") or logs)[-20:],
                    }
        finally:
            if not finished and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

    async def close(self, shutdown: bool = True):
        from tools.persist import clear_state, kill_pid

        if self.attached:
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
            self.attached = False
            return

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
        self.persist = True
        self.attached = False
        self.mode = "persist"


from tools.registry import SessionRegistry

registry = SessionRegistry(lambda name="default": BrowserSession(name=name))


async def get_session(name: str = ""):
    return registry.get(name)


@asynccontextmanager
async def locked_session(name: str = ""):
    sess = await get_session(name)
    async with sess._lock:
        yield sess
