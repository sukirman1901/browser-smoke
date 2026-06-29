import asyncio
import base64
import fnmatch
import os
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


@dataclass
class BrowserSession:
    browser: Optional[Browser] = None
    context: Optional[BrowserContext] = None
    page: Optional[Page] = None
    _pw: Optional[async_playwright] = field(default=None)
    _console_logs: list[dict] = field(default_factory=list)
    _page_errors: list[dict] = field(default_factory=list)
    _network_logs: list[dict] = field(default_factory=list)
    _network_capturing: bool = False
    _capture_patterns: list[str] = field(default_factory=list)
    _blocked_patterns: list = field(default_factory=list)
    _pages: list[Page] = field(default_factory=list)
    _offscreen_page: Optional[Page] = field(default=None)

    async def start(self, headless: bool = False):
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(headless=headless, channel="chrome")
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=os.path.join(os.getcwd(), "artifacts") if not headless else None,
        )
        self.context.on("page", self._on_new_page)
        self.page = await self.context.new_page()
        self._pages = [self.page]
        self._setup_page_listeners(self.page)

    def _setup_page_listeners(self, page: Page):
        page.on("console", lambda msg: self._console_logs.append({
            "type": msg.type, "text": msg.text, "url": msg.location.get("url", ""),
        }))
        page.on("pageerror", lambda err: self._page_errors.append({
            "message": str(err), "url": page.url,
        }))

    def _on_new_page(self, page: Page):
        self._pages.append(page)
        self._setup_page_listeners(page)

    async def start_network_capture(self, patterns: list[str] | None = None):
        self._network_logs.clear()
        self._network_capturing = True
        self._capture_patterns = patterns or ["**/*"]
        await self.context.route("**/*", self._handle_capture_route)
        return {"status": "ok", "message": "Network capture started"}

    async def _handle_capture_route(self, route):
        req = route.request
        if self._capture_patterns != ["**/*"] and not any(
            fnmatch.fnmatch(req.url, p) for p in self._capture_patterns
        ):
            await route.continue_()
            return
        entry = {
            "method": req.method,
            "url": req.url,
            "headers": dict(req.headers),
            "resource_type": req.resource_type,
            "timestamp": int(req.timing.request_time * 1000) if req.timing.request_time else 0,
        }
        try:
            resp = await route.fetch()
            entry["status"] = resp.status
            entry["response_headers"] = dict(resp.headers)
            entry["body_size"] = len(await resp.body()) if resp else 0
            await route.fulfill(response=resp)
        except Exception as e:
            entry["status"] = 0
            entry["error"] = str(e)
            await route.continue_()
        self._network_logs.append(entry)

    async def stop_network_capture(self):
        self._network_capturing = False
        await self.context.unroute("**/*")
        return {"status": "ok", "captured": len(self._network_logs)}

    def get_network_logs(self):
        return list(self._network_logs)

    async def block_resources(self, patterns: list[str]):
        if not patterns:
            self._blocked_patterns = []
            await self.context.unroute("**/*")
            return {"status": "ok", "message": "All resources unblocked"}
        self._blocked_patterns = patterns
        async def _block_handler(route):
            req = route.request
            for pat in patterns:
                if fnmatch.fnmatch(req.url, pat):
                    await route.abort()
                    return
            await route.continue_()
        await self.context.route("**/*", _block_handler)
        return {"status": "ok", "blocked_patterns": patterns}

    async def open(self, url: str) -> dict:
        if not self.page:
            await self.start()
        try:
            response = await self.page.goto(url, wait_until="networkidle", timeout=30000)
            title = await self.page.title()
            ss = await self._screenshot()
            return {
                "status": "ok",
                "title": title,
                "status_code": response.status if response else None,
                "screenshot": ss,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def extract_dom(self) -> list[dict]:
        elements = await self.page.evaluate("""
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
                        text: text.substring(0, 100),
                        selector,
                        type: tag === 'input' ? inputType : tag,
                        visible: rect.top < window.innerHeight && rect.bottom > 0,
                        enabled: !el.disabled,
                        rect: {x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height)},
                    });
                });
                return items;

                function buildSelector(el) {
                    if (el.id) return '#' + CSS.escape(el.id);
                    if (el.getAttribute('data-testid')) return '[data-testid="' + el.getAttribute('data-testid') + '"]';
                    const tag = el.tagName.toLowerCase();
                    const text = el.textContent?.trim().substring(0, 50);
                    if (text && ['button', 'a'].includes(tag)) return tag + ':has-text("' + text + '")';
                    const parent = el.parentElement?.closest('[id]');
                    if (parent) return '#' + CSS.escape(parent.id) + ' ' + tag + ':nth-child(' + (Array.from(parent.children).indexOf(el) + 1) + ')';
                    return tag + ':nth-child(' + (Array.from(el.parentElement?.children || []).indexOf(el) + 1) + ')';
                }
            }
        """)
        return elements

    async def click(self, selector: str) -> dict:
        try:
            await self.page.click(selector, timeout=5000)
            await self.page.wait_for_timeout(500)
            return {"status": "ok", "screenshot": await self._screenshot(), "url": self.page.url}
        except Exception as e:
            return {"status": "error", "message": str(e), "screenshot": await self._screenshot()}

    async def type_text(self, selector: str, text: str) -> dict:
        try:
            await self.page.fill(selector, text, timeout=5000)
            await self.page.wait_for_timeout(300)
            return {"status": "ok", "screenshot": await self._screenshot()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def screenshot(self) -> dict:
        return {"screenshot": await self._screenshot()}

    async def highlight(self, selector: str, color: str = "red", duration: int = 2000) -> dict:
        try:
            await self.page.evaluate(f"""
                (() => {{
                    const el = document.querySelector({selector!r});
                    if (!el) return {{ found: false }};
                    const orig = {{
                        outline: el.style.outline,
                        outlineOffset: el.style.outlineOffset,
                        boxShadow: el.style.boxShadow,
                    }};
                    el.style.outline = '3px solid {color}';
                    el.style.outlineOffset = '2px';
                    el.style.boxShadow = '0 0 15px rgba(255,0,0,0.3)';
                    setTimeout(() => {{
                        el.style.outline = orig.outline;
                        el.style.outlineOffset = orig.outlineOffset;
                        el.style.boxShadow = orig.boxShadow;
                    }}, {duration});
                    return {{ found: true, tag: el.tagName, text: (el.textContent || '').trim().substring(0, 100) }};
                }})()
            """)
            ss = await self._screenshot()
            return {"status": "ok", "screenshot": ss}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def screenshot_diff(self, name: str, threshold: float = 0.01) -> dict:
        import os
        import hashlib
        import io
        import base64
        from PIL import Image
        from pixelmatch.contrib.PIL import pixelmatch

        baseline_dir = os.path.join(os.getcwd(), "artifacts", "baselines")
        os.makedirs(baseline_dir, exist_ok=True)
        baseline_path = os.path.join(baseline_dir, f"{name}.png")

        current_png = await self.page.screenshot(type="png")
        current_hash = hashlib.md5(current_png).hexdigest()[:12]

        if not os.path.exists(baseline_path):
            with open(baseline_path, "wb") as f:
                f.write(current_png)
            return {
                "status": "baseline_created",
                "name": name,
                "hash": current_hash,
                "message": f"Baseline saved to {baseline_path}",
            }

        with open(baseline_path, "rb") as f:
            baseline_png = f.read()

        baseline_img = Image.open(io.BytesIO(baseline_png))
        current_img = Image.open(io.BytesIO(current_png))
        diff_img = Image.new("RGBA", baseline_img.size)

        diff_pixels = pixelmatch(baseline_img, current_img, diff_img, threshold=threshold, includeAA=True)

        diff_buf = io.BytesIO()
        diff_img.save(diff_buf, format="PNG")
        diff_b64 = base64.b64encode(diff_buf.getvalue()).decode()

        return {
            "status": "ok" if diff_pixels == 0 else "diff",
            "name": name,
            "diff_pixels": diff_pixels,
            "total_pixels": baseline_img.width * baseline_img.height,
            "threshold": threshold,
            "baseline_hash": hashlib.md5(baseline_png).hexdigest()[:12],
            "current_hash": current_hash,
            "diff_screenshot": diff_b64 if diff_pixels > 0 else "",
        }

    async def scroll(self, x: int = 0, y: int = 200) -> dict:
        await self.page.evaluate(f"window.scrollTo({x}, {y})")
        await self.page.wait_for_timeout(300)
        return {"status": "ok", "screenshot": await self._screenshot()}

    async def execute(self, js_code: str) -> dict:
        try:
            result = await self.page.evaluate(js_code)
            return {"status": "ok", "result": str(result) if result is not None else "undefined"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def inject_script(self, script: str, url_pattern: str = "*"):
        await self.context.add_init_script(script=script)
        return {"status": "ok", "message": "Script will run on all new pages"}

    async def offscreen(self, action: str, url: str = "", js: str = "") -> dict:
        if action == "open":
            self._offscreen_page = await self.context.new_page()
            if url:
                await self._offscreen_page.goto(url, wait_until="domcontentloaded")
            return {"status": "ok", "url": url or "blank", "offscreen": True}
        elif action == "exec":
            if not self._offscreen_page:
                return {"status": "error", "message": "No offscreen page. Call mode=open first."}
            result = await self._offscreen_page.evaluate(js)
            return {"status": "ok", "result": str(result) if result is not None else "undefined"}
        elif action == "close":
            if self._offscreen_page:
                await self._offscreen_page.close()
                self._offscreen_page = None
            return {"status": "ok", "message": "Offscreen page closed"}
        return {"status": "error", "message": f"unknown action: {action}"}

    async def execute_in_all_pages(self, js_code: str):
        results = []
        for p in self._pages:
            try:
                r = await p.evaluate(js_code)
                results.append({"url": p.url, "result": str(r) if r is not None else "undefined"})
            except Exception as e:
                results.append({"url": p.url, "error": str(e)})
        return results

    async def open_tab(self, url: str) -> dict:
        try:
            page = await self.context.new_page()
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
            title = await page.title()
            self.page = page
            return {"status": "ok", "title": title, "url": url}
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

    def get_console(self) -> list[dict]:
        logs = list(self._console_logs)
        return logs

    def get_errors(self) -> list[dict]:
        errors = list(self._page_errors)
        return errors

    async def get_cookies(self) -> dict:
        cookies = await self.context.cookies()
        return {"cookies": cookies, "count": len(cookies)}

    async def set_cookie(self, name: str, value: str, domain: str = "", path: str = "/") -> dict:
        await self.context.add_cookies([{
            "name": name,
            "value": value,
            "domain": domain,
            "path": path,
        }])
        return {"status": "ok", "cookie": {"name": name, "domain": domain, "path": path}}

    async def clear_cookies(self) -> dict:
        await self.context.clear_cookies()
        return {"status": "ok", "message": "All cookies cleared"}

    async def storage(self, mode: str, storage: str = "local", key: str = "", value: str = "") -> dict:
        store = "localStorage" if storage == "local" else "sessionStorage"
        if mode == "all":
            result = await self.page.evaluate(f"JSON.parse(JSON.stringify({store}))")
            return {"storage": storage, "data": result}
        elif mode == "get":
            result = await self.page.evaluate(f"{store}.getItem({key!r})")
            return {"storage": storage, "key": key, "value": result}
        elif mode == "set":
            await self.page.evaluate(f"{store}.setItem({key!r}, {value!r})")
            return {"storage": storage, "key": key, "value": value, "status": "set"}
        elif mode == "clear":
            await self.page.evaluate(f"{store}.clear()")
            return {"storage": storage, "status": "cleared"}
        return {"status": "error", "message": f"unknown mode: {mode}"}

    async def close(self):
        if self._pw:
            await self._pw.stop()
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
            if self._offscreen_page:
                await self._offscreen_page.close()
                self._offscreen_page = None

    async def _screenshot(self) -> str:
        data = await self.page.screenshot(type="png", full_page=False)
        return base64.b64encode(data).decode()


_session = BrowserSession()


async def get_session() -> BrowserSession:
    return _session
