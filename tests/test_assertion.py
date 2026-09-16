import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

from tools.assertion import (
    as_bool,
    batch_halt,
    describe,
    evaluate,
    validate_assert,
    verdict,
)


class ValidateAssertTests(unittest.TestCase):
    def test_unknown_expect_is_error(self):
        err = validate_assert(expect="color", selector="@1", text="x")
        self.assertEqual(err["status"], "error")
        self.assertIn("unknown expect: color", err["message"])
        self.assertIn("text|url|visible|hidden|count|input_value", err["hint"])

    def test_visible_requires_selector(self):
        err = validate_assert(expect="visible", selector="", text="")
        self.assertEqual(err["status"], "error")
        self.assertIn("selector", err["message"])

    def test_hidden_requires_selector(self):
        err = validate_assert(expect="hidden", selector="  ", text="")
        self.assertEqual(err["status"], "error")

    def test_count_requires_selector(self):
        err = validate_assert(expect="count", selector="", text="")
        self.assertEqual(err["status"], "error")

    def test_text_requires_text(self):
        err = validate_assert(expect="text", selector="body", text="")
        self.assertEqual(err["status"], "error")
        self.assertIn("text", err["message"])

    def test_url_requires_text(self):
        err = validate_assert(expect="url", selector="", text="  ")
        self.assertEqual(err["status"], "error")

    def test_input_value_allows_empty_text(self):
        self.assertIsNone(validate_assert(expect="input_value", selector="@1", text=""))

    def test_count_zero_is_valid(self):
        self.assertIsNone(validate_assert(expect="count", selector="@1", text=""))

    def test_text_on_body_is_valid(self):
        self.assertIsNone(validate_assert(expect="text", selector="", text="Saved"))

    def test_expect_is_case_insensitive(self):
        self.assertIsNone(validate_assert(expect="TEXT", selector="", text="ok"))


class EvaluateTests(unittest.TestCase):
    def test_text_contains(self):
        self.assertTrue(evaluate("text", observed="Hello Saved there", expected_text="Saved"))
        self.assertFalse(evaluate("text", observed="Hello", expected_text="Saved"))

    def test_url_substring_not_glob(self):
        self.assertTrue(evaluate("url", observed="https://a.com/checkout", expected_text="/checkout"))
        self.assertFalse(evaluate("url", observed="https://a.com/cart", expected_text="/checkout"))
        self.assertFalse(evaluate("url", observed="https://a.com/checkout", expected_text="**/checkout"))

    def test_visible_and_hidden(self):
        self.assertTrue(evaluate("visible", observed=True))
        self.assertFalse(evaluate("visible", observed=False))
        self.assertTrue(evaluate("hidden", observed=True))
        self.assertFalse(evaluate("hidden", observed=False))

    def test_count_exact(self):
        self.assertTrue(evaluate("count", observed=3, expected_count=3))
        self.assertFalse(evaluate("count", observed=0, expected_count=3))
        self.assertTrue(evaluate("count", observed=0, expected_count=0))

    def test_input_value_exact(self):
        self.assertTrue(evaluate("input_value", observed="hi", expected_text="hi"))
        self.assertFalse(evaluate("input_value", observed="hi ", expected_text="hi"))
        self.assertTrue(evaluate("input_value", observed="", expected_text=""))

    def test_negate_flips(self):
        self.assertTrue(evaluate("text", observed="x", expected_text="Saved", negate=True))
        self.assertFalse(evaluate("url", observed="https://a.com/checkout", expected_text="/checkout", negate=True))
        self.assertTrue(evaluate("visible", observed=False, negate=True))
        self.assertTrue(evaluate("count", observed=2, expected_count=3, negate=True))


class VerdictTests(unittest.TestCase):
    def test_ok_payload(self):
        got = verdict(
            assert_line="text @3 contains 'Berhasil disimpan'",
            expected="text contains 'Berhasil disimpan'",
            actual="found in @3",
            passed=True,
        )
        self.assertEqual(got["status"], "ok")
        self.assertEqual(got["assert"], "text @3 contains 'Berhasil disimpan'")
        self.assertEqual(got["expected"], "text contains 'Berhasil disimpan'")
        self.assertEqual(got["actual"], "found in @3")
        self.assertNotIn("hint", got)

    def test_fail_is_assert_fail_not_error(self):
        got = verdict(
            assert_line="url contains /checkout",
            expected="url contains /checkout",
            actual="https://a.com/cart",
            passed=False,
        )
        self.assertEqual(got["status"], "assert_fail")
        self.assertNotEqual(got["status"], "error")
        self.assertEqual(got["actual"], "https://a.com/cart")
        self.assertIn("Snapshot", got["hint"])


class DescribeTests(unittest.TestCase):
    def test_text_with_ref(self):
        line, expected = describe(expect="text", selector="@3", text="Berhasil disimpan")
        self.assertEqual(line, "text @3 contains 'Berhasil disimpan'")
        self.assertEqual(expected, "text contains 'Berhasil disimpan'")

    def test_url(self):
        line, expected = describe(expect="url", selector="", text="/checkout")
        self.assertEqual(line, "url contains /checkout")
        self.assertEqual(expected, "url contains /checkout")

    def test_negate_prefix(self):
        line, expected = describe(expect="text", selector="@3", text="x", negate=True)
        self.assertTrue(line.startswith("not "))
        self.assertIn("does not contain", expected)

    def test_visible_hidden_count_input(self):
        self.assertEqual(describe(expect="visible", selector="@4")[0], "visible @4")
        self.assertEqual(describe(expect="hidden", selector="#x")[0], "hidden #x")
        self.assertEqual(describe(expect="count", selector="@2", count=3)[0], "count @2 == 3")
        self.assertEqual(
            describe(expect="input_value", selector="@1", text="hi")[0],
            "input_value @1 == 'hi'",
        )


class HelperTests(unittest.TestCase):
    def test_as_bool_string_false(self):
        self.assertFalse(as_bool("false"))
        self.assertFalse(as_bool("False"))
        self.assertTrue(as_bool("true"))
        self.assertTrue(as_bool(True))
        self.assertFalse(as_bool(False))
        self.assertFalse(as_bool(None))
        self.assertTrue(as_bool("1"))

    def test_batch_halt(self):
        self.assertTrue(batch_halt("error"))
        self.assertTrue(batch_halt("assert_fail"))
        self.assertFalse(batch_halt("ok"))
        self.assertFalse(batch_halt("truncated"))


class WiringTests(unittest.TestCase):
    """CI cannot import browser.py (no Playwright). Parse source so assert is actually hooked up."""

    def test_session_and_mcp_define_assert(self):
        root = Path(__file__).resolve().parents[1]
        browser = ast.parse((root / "mcp" / "tools" / "browser.py").read_text())
        names = {
            node.name
            for node in ast.walk(browser)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("assert_condition", names)
        self.assertIn("_assert_poll", names)
        self.assertIn("_resolve_locator", names)

        server = (root / "mcp" / "server.py").read_text()
        self.assertIn("async def browser_assert(", server)
        self.assertIn("await sess.assert_condition(", server)

        run_one = (root / "mcp" / "tools" / "browser.py").read_text()
        self.assertIn('if action == "assert":', run_one)
        self.assertIn('if method == "assert":', run_one)
        self.assertIn("batch_halt(", run_one)
        self.assertIn('method == "assert" and batch_halt', run_one)

        host = (root / "mcp" / "script-host.mjs").read_text()
        self.assertIn("assert: (opts) => rpc(\"assert\"", host)
        self.assertIn('"assert"', host)
        self.assertIn("const assert = (opts) => page.assert(opts);", host)

    def test_report_signature_unchanged(self):
        server = (Path(__file__).resolve().parents[1] / "mcp" / "server.py").read_text()
        self.assertIn("async def browser_report(results_json: str,", server)
        self.assertNotIn("transcript", server.lower())


if __name__ == "__main__":
    unittest.main()
