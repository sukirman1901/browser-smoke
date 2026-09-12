import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

from tools.dom_extractor import classify_inputs, guess_input_value
from tools.payload import (
    MAX_RESULT_CHARS,
    cap_snapshot_items,
    compact_classified,
    compact_network,
    dumps,
    format_snapshot_lines,
    clip_logs,
    matches_url,
    safe_artifact_name,
    wrap_init_script,
)
from tools.reporter import generate_report


class PayloadTests(unittest.TestCase):
    def test_dumps_is_compact(self):
        text = dumps({"status": "ok", "title": "Home"})
        self.assertNotIn("\n", text)
        self.assertIn('"status":"ok"', text)

    def test_dumps_truncates(self):
        huge = {"data": "x" * (MAX_RESULT_CHARS + 100)}
        parsed = __import__("json").loads(dumps(huge))
        self.assertEqual(parsed["status"], "truncated")
        self.assertIn("preview", parsed)

    def test_snapshot_lines(self):
        text = format_snapshot_lines(
            [
                {"ref": 1, "role": "textbox", "name": "Email", "type": "email"},
                {"ref": 2, "role": "button", "name": "Login"},
                {"ref": 3, "role": "link", "name": "Docs", "href": "/docs"},
            ]
        )
        self.assertEqual(
            text,
            '@1 textbox "Email" email\n@2 button "Login"\n@3 link "Docs" /docs',
        )

    def test_snapshot_marks_iframe(self):
        text = format_snapshot_lines(
            [{"ref": 4, "role": "button", "name": "Pay", "iframe": True}]
        )
        self.assertEqual(text, '@4 button "Pay" iframe')

    def test_snapshot_marks_hidden_file(self):
        text = format_snapshot_lines(
            [{"ref": 7, "role": "file", "name": "Upload", "type": "file", "hidden": True}]
        )
        self.assertEqual(text, '@7 file "Upload" hidden file')

    def test_href_is_clipped(self):
        href = "https://example.com/" + ("a" * 80)
        text = format_snapshot_lines(
            [{"ref": 1, "role": "link", "name": "X", "href": href}]
        )
        tail = text.split(" ")[-1]
        self.assertEqual(len(tail), 40)

    def test_cap_keeps_hidden_file(self):
        items = [{"ref": i, "role": "link", "name": str(i)} for i in range(1, 91)]
        items.append({"ref": 99, "role": "file", "name": "up", "hidden": True})
        shown, total = cap_snapshot_items(items, limit=10)
        self.assertEqual(total, 91)
        self.assertEqual(len(shown), 10)
        self.assertTrue(any(x.get("hidden") for x in shown))

    def test_compact_classified_drops_rects(self):
        classified = {
            "buttons": [
                {
                    "tag": "button",
                    "selector": "#go",
                    "text": "Go",
                    "rect": {"x": 1, "y": 2, "width": 3, "height": 4},
                    "visible": True,
                    "enabled": True,
                }
            ],
            "inputs": [],
            "links": [],
            "others": [],
            "total": 1,
        }
        compact = compact_classified(classified)
        self.assertEqual(compact["buttons"][0], {"tag": "button", "sel": "#go", "text": "Go"})

    def test_clip_logs_caps_and_truncates(self):
        entries = [{"type": "log", "text": "a" * 500, "url": "https://x"} for _ in range(80)]
        clipped = clip_logs(entries)
        self.assertEqual(len(clipped), 40)
        self.assertEqual(len(clipped[0]["text"]), 240)
        self.assertNotIn("url", clipped[0])

    def test_network_omits_headers_by_default(self):
        entries = [
            {
                "method": "GET",
                "url": "https://api.test/x",
                "status": 200,
                "resource_type": "fetch",
                "headers": {"authorization": "secret"},
            }
        ]
        compact = compact_network(entries)
        self.assertNotIn("headers", compact[0])
        self.assertEqual(compact[0]["status"], 200)

    def test_matches_json_glob(self):
        self.assertTrue(matches_url("https://app.test/data.json", ["*.json"]))
        self.assertFalse(matches_url("https://app.test/page", ["*.json"]))

    def test_matches_substring_host(self):
        self.assertTrue(matches_url("https://api.foo.com/v1", ["*api*"]))

    def test_safe_artifact_name_strips_path(self):
        self.assertEqual(safe_artifact_name("../../etc/passwd"), "passwd")
        self.assertEqual(safe_artifact_name("home page!"), "home_page")

    def test_wrap_init_skips_star(self):
        self.assertEqual(wrap_init_script("window.x=1", "*"), "window.x=1")
        wrapped = wrap_init_script("window.x=1", "*.example.com*")
        self.assertIn("new RegExp", wrapped)
        self.assertIn("window.x=1", wrapped)

    def test_cap_append_trims_oldest(self):
        from tools.payload import cap_append
        items = list(range(5))
        cap_append(items, 5, cap=5)
        self.assertEqual(items, [1, 2, 3, 4, 5])

    def test_snapshot_selector_covers_editors_and_dialogs(self):
        from tools.payload import SNAPSHOT_SELECTOR
        self.assertIn("contenteditable", SNAPSHOT_SELECTOR)
        self.assertIn('[role="dialog"]', SNAPSHOT_SELECTOR)
        self.assertIn('[role="combobox"]', SNAPSHOT_SELECTOR)
        self.assertIn('[role="listbox"]', SNAPSHOT_SELECTOR)
        self.assertIn('[role="switch"]', SNAPSHOT_SELECTOR)

    def test_classify_expired_ref(self):
        from tools.payload import classify_target_error
        err = classify_target_error("Expired ref @4. Call browser_snapshot again.")
        self.assertEqual(err["code"], "expired_ref")
        self.assertIn("snapshot", err["hint"])

    def test_classify_intercepted(self):
        from tools.payload import classify_target_error
        err = classify_target_error("<div> intercepts pointer events")
        self.assertEqual(err["code"], "intercepted")
        self.assertIn("scroll", err["hint"].lower())

    def test_classify_type_select(self):
        from tools.payload import classify_type_error
        err = classify_type_error("Cannot fill input of type select")
        self.assertIn("select_option", err["hint"])

    def test_version_constant(self):
        from tools.payload import SMOKE_VERSION
        self.assertEqual(SMOKE_VERSION, "1.4.3")

    def test_parse_aria_keeps_interactive_refs(self):
        from tools.payload import parse_aria_snapshot
        yaml_text = """
- banner:
  - heading "Example Domain" [level=1] [ref=e1]
  - link "More information" [ref=e2]:
    - /url: https://example.com
- main:
  - textbox "Email" [ref=e3]
  - button "Publish" [ref=e4]
  - paragraph: Static copy [ref=e5]
"""
        items = parse_aria_snapshot(yaml_text)
        self.assertEqual([i["role"] for i in items], ["link", "textbox", "button"])
        self.assertEqual([i["ref"] for i in items], [1, 2, 3])
        self.assertEqual(items[0]["sel"], "aria-ref=e2")
        self.assertEqual(items[2]["name"], "Publish")

    def test_parse_aria_viewport_drops_offscreen(self):
        from tools.payload import parse_aria_snapshot
        yaml_text = """
- button "Visible" [ref=e1] [box=10,10,80,24]
- button "Below" [ref=e2] [box=10,900,80,24]
"""
        items = parse_aria_snapshot(yaml_text, viewport={"width": 1280, "height": 720})
        self.assertEqual([i["name"] for i in items], ["Visible"])

    def test_parse_aria_textbox_ref(self):
        from tools.payload import parse_aria_snapshot
        items = parse_aria_snapshot('- textbox "Post body" [ref=e9]\n')
        self.assertEqual(items[0]["aria_ref"], "e9")
        self.assertEqual(items[0]["role"], "textbox")


class DomExtractorTests(unittest.TestCase):
    def test_guess_email(self):
        self.assertEqual(guess_input_value({"type": "email"}), "test@test.com")

    def test_classify_without_visible_key(self):
        elements = [{"tag": "button", "text": "Ok", "selector": "button"}]
        classified = classify_inputs(elements)
        self.assertEqual(classified["total"], 1)
        self.assertEqual(len(classified["buttons"]), 1)


class ReporterTests(unittest.TestCase):
    def test_report_counts(self):
        md = generate_report(
            "http://localhost",
            [
                {"step": "open", "status": "ok", "url": "/"},
                {"step": "click", "status": "error", "message": "missing"},
            ],
        )
        self.assertIn("1 passed, 1 failed", md)

    def test_report_without_step_key(self):
        md = generate_report("http://localhost", [{"status": "error", "message": "boom"}])
        self.assertIn("step:", md)
        self.assertIn("boom", md)


if __name__ == "__main__":
    unittest.main()
