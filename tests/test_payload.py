import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

from tools.dom_extractor import classify_inputs, guess_input_value
from tools.payload import (
    MAX_RESULT_CHARS,
    compact_classified,
    compact_network,
    dumps,
    format_snapshot_lines,
    clip_logs,
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


if __name__ == "__main__":
    unittest.main()
