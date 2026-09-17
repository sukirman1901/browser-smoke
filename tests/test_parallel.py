import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

from tools.parallel import MAX_PARALLEL_JOBS, parse_parallel_jobs, settle_parallel


class ParseParallelJobsTests(unittest.TestCase):
    def test_urls_json_with_js(self):
        parsed = parse_parallel_jobs(
            urls='["https://a.com","https://b.com"]',
            js_code="() => document.title",
        )
        self.assertEqual(
            parsed["jobs"],
            [
                {"url": "https://a.com", "js": "() => document.title"},
                {"url": "https://b.com", "js": "() => document.title"},
            ],
        )

    def test_urls_python_list(self):
        parsed = parse_parallel_jobs(urls=["https://a.com", "https://b.com"])
        self.assertEqual(parsed["jobs"], [{"url": "https://a.com"}, {"url": "https://b.com"}])

    def test_urls_comma_separated(self):
        parsed = parse_parallel_jobs(urls="https://a.com, https://b.com")
        self.assertEqual(
            parsed["jobs"],
            [{"url": "https://a.com"}, {"url": "https://b.com"}],
        )

    def test_js_on_existing_tabs(self):
        parsed = parse_parallel_jobs(js_code="() => location.href", existing_tabs=[0, 2])
        self.assertEqual(
            parsed["jobs"],
            [
                {"tab": 0, "js": "() => location.href"},
                {"tab": 2, "js": "() => location.href"},
            ],
        )

    def test_tabs_filter(self):
        parsed = parse_parallel_jobs(
            js_code="() => 1",
            tabs="[1]",
            existing_tabs=[0, 1, 2],
        )
        self.assertEqual(parsed["jobs"], [{"tab": 1, "js": "() => 1"}])

    def test_jobs_json_mixed(self):
        parsed = parse_parallel_jobs(
            jobs_json='[{"url":"https://a.com","js":"() => 1"},{"tab":2,"js_code":"() => 2"}]',
        )
        self.assertEqual(
            parsed["jobs"],
            [
                {"url": "https://a.com", "js": "() => 1"},
                {"tab": 2, "js": "() => 2"},
            ],
        )

    def test_jobs_json_string_items(self):
        parsed = parse_parallel_jobs(
            jobs_json='["https://a.com"]',
            js_code="() => 1",
        )
        self.assertEqual(parsed["jobs"], [{"url": "https://a.com", "js": "() => 1"}])

    def test_cap(self):
        urls = [f"https://n{i}.example" for i in range(MAX_PARALLEL_JOBS + 1)]
        import json

        parsed = parse_parallel_jobs(urls=json.dumps(urls))
        self.assertEqual(parsed["status"], "error")
        self.assertIn("max 8", parsed["message"])

    def test_empty_is_error(self):
        parsed = parse_parallel_jobs()
        self.assertEqual(parsed["status"], "error")
        self.assertIn("urls", parsed["message"])

    def test_js_without_tabs_is_error(self):
        parsed = parse_parallel_jobs(js_code="() => 1", existing_tabs=[])
        self.assertEqual(parsed["status"], "error")
        self.assertIn("No tabs", parsed["message"])

    def test_bad_jobs_json(self):
        parsed = parse_parallel_jobs(jobs_json="{")
        self.assertEqual(parsed["status"], "error")
        self.assertIn("JSON", parsed["message"])

    def test_job_missing_url_and_tab(self):
        parsed = parse_parallel_jobs(jobs_json='[{"js":"() => 1"}]')
        self.assertEqual(parsed["status"], "error")
        self.assertIn("url or tab", parsed["message"])


class SettleParallelTests(unittest.TestCase):
    def test_all_ok(self):
        out = settle_parallel([{"status": "ok"}, {"status": "ok"}])
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["parallel"])
        self.assertEqual(out["ok"], 2)
        self.assertEqual(out["failed"], 0)

    def test_partial_is_ok(self):
        out = settle_parallel([{"status": "ok"}, {"status": "error", "message": "x"}])
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["failed"], 1)

    def test_all_fail(self):
        out = settle_parallel([{"status": "error"}])
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["ok"], 0)


class WiringTests(unittest.TestCase):
    def test_session_and_mcp_define_parallel(self):
        root = Path(__file__).resolve().parents[1]
        browser = ast.parse((root / "mcp" / "tools" / "browser.py").read_text())
        names = {
            node.name
            for node in ast.walk(browser)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("run_parallel", names)
        self.assertIn("_parallel_one", names)

        server = (root / "mcp" / "server.py").read_text()
        self.assertIn("async def browser_parallel(", server)
        self.assertIn("await sess.run_parallel(", server)

        source = (root / "mcp" / "tools" / "browser.py").read_text()
        self.assertIn('if action == "parallel":', source)


if __name__ == "__main__":
    unittest.main()
