import os
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

from tools.persist import (
    allocate_port,
    kill_pid,
    normalize_cdp_endpoint,
    persist_preferred_port,
    persist_profile,
    port_free,
    resolve_launch_mode,
    safe_session_name,
    session_cdp_port,
)
from tools.registry import SessionRegistry
from tools.script_rpc import coerce_rpc_params


class PersistHelperTests(unittest.TestCase):
    def test_safe_session_name(self):
        self.assertEqual(safe_session_name(""), "default")
        self.assertEqual(safe_session_name("../evil"), "evil")
        self.assertEqual(safe_session_name("Work Mail"), "Work_Mail")

    def test_port_is_stable(self):
        self.assertEqual(session_cdp_port("work"), session_cdp_port("work"))
        self.assertNotEqual(session_cdp_port("work"), session_cdp_port("other"))

    def test_normalize_cdp_endpoint(self):
        self.assertEqual(normalize_cdp_endpoint(""), "")
        self.assertEqual(normalize_cdp_endpoint("9222"), "http://127.0.0.1:9222")
        self.assertEqual(
            normalize_cdp_endpoint("http://127.0.0.1:9222"),
            "http://127.0.0.1:9222",
        )
        self.assertEqual(
            normalize_cdp_endpoint("ws://127.0.0.1:9222/devtools/browser/abc"),
            "ws://127.0.0.1:9222/devtools/browser/abc",
        )
        self.assertEqual(
            normalize_cdp_endpoint("127.0.0.1:9222"),
            "http://127.0.0.1:9222",
        )

    def test_resolve_launch_mode_default_is_persist(self):
        self.assertEqual(resolve_launch_mode()["mode"], "persist")
        self.assertTrue(resolve_launch_mode()["persist"])

    def test_resolve_cdp_wins_over_default_persist(self):
        got = resolve_launch_mode(persist=True, cdp="9222")
        self.assertEqual(got["mode"], "attach")
        self.assertFalse(got["persist"])
        self.assertEqual(got["cdp"], "9222")

    def test_resolve_channel_is_ephemeral_chrome(self):
        got = resolve_launch_mode(persist=True, channel="chrome")
        self.assertEqual(got["mode"], "channel")
        self.assertFalse(got["persist"])

    def test_resolve_persist_false_is_ephemeral(self):
        self.assertEqual(resolve_launch_mode(persist=False)["mode"], "ephemeral")

    def test_resolve_cdp_and_channel_error(self):
        with self.assertRaises(ValueError):
            resolve_launch_mode(cdp="9222", channel="chrome")

    def test_persist_profile_default_is_chrome_attach(self):
        path = persist_profile("default")
        self.assertTrue(path.endswith(os.path.join(".browser-smoke", "chrome-attach")))
        self.assertNotIn("profiles", path)

    def test_persist_profile_named_is_isolated(self):
        path = persist_profile("work")
        self.assertTrue(path.endswith(os.path.join(".browser-smoke", "chrome-profiles", "work")))

    def test_persist_preferred_port_default_is_9222(self):
        self.assertEqual(persist_preferred_port("default"), 9222)
        self.assertEqual(persist_preferred_port(""), 9222)
        self.assertEqual(persist_preferred_port("work"), 0)


class RegistryTests(unittest.TestCase):
    def test_named_sessions_are_isolated(self):
        n = {"count": 0}

        class Fake:
            def __init__(self, name="default"):
                n["count"] += 1
                self.name = name

        reg = SessionRegistry(lambda name="default": Fake(name=name))
        a = reg.get("work")
        b = reg.get("mail")
        self.assertEqual(a.name, "work")
        self.assertEqual(b.name, "mail")
        self.assertIsNot(a, b)
        self.assertEqual(reg.current, "mail")
        self.assertIs(reg.get("work"), a)

    def test_list_does_not_switch_current(self):
        class Fake:
            def __init__(self, name="default"):
                self.name = name

        reg = SessionRegistry(lambda name="default": Fake(name=name))
        reg.get("work")
        self.assertEqual(reg.current, "work")
        reg.get("mail", switch=False)
        self.assertEqual(reg.current, "work")


class RpcCoerceTests(unittest.TestCase):
    def test_wait_load_string(self):
        self.assertEqual(coerce_rpc_params("wait", "load"), {"state": "load"})
        self.assertIsInstance(coerce_rpc_params("wait", "load"), dict)

    def test_wait_url_glob(self):
        self.assertEqual(coerce_rpc_params("wait", "**/done"), {"url": "**/done"})
        self.assertEqual(
            coerce_rpc_params("wait", "https://example.com/*"),
            {"url": "https://example.com/*"},
        )

    def test_wait_selector_string(self):
        self.assertEqual(coerce_rpc_params("wait", "#ready"), {"selector": "#ready"})

    def test_click_selector_string(self):
        self.assertEqual(coerce_rpc_params("click", "@1"), {"selector": "@1"})

    def test_dict_passthrough(self):
        self.assertEqual(coerce_rpc_params("wait", {"state": "load"}), {"state": "load"})

    def test_upload_paths_list(self):
        self.assertEqual(
            coerce_rpc_params("set_files", {"selector": "#f", "paths": ["/a.pdf", "/b.pdf"]}),
            {"selector": "#f", "paths": "/a.pdf,/b.pdf"},
        )

    def test_scroll_ref_string(self):
        self.assertEqual(coerce_rpc_params("scroll", "@3"), {"selector": "@3"})

    def test_scroll_pixels_string(self):
        self.assertEqual(coerce_rpc_params("scroll", "800"), {"y": 800})

    def test_scroll_pixels_number(self):
        self.assertEqual(coerce_rpc_params("scroll", 400), {"y": 400})

    def test_none_is_empty_dict(self):
        self.assertEqual(coerce_rpc_params("wait", None), {})

    def test_assert_dict_passthrough(self):
        self.assertEqual(
            coerce_rpc_params(
                "assert",
                {"expect": "text", "text": "Saved", "selector": "@3", "negate": False},
            ),
            {"expect": "text", "text": "Saved", "selector": "@3", "negate": False},
        )

    def test_assert_string_is_not_silently_a_selector(self):
        self.assertEqual(coerce_rpc_params("assert", "Saved"), {})


class PersistPortTests(unittest.TestCase):
    def test_port_free_false_when_bound(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.listen(1)
        try:
            self.assertFalse(port_free(port))
        finally:
            sock.close()

    def test_allocate_port_skips_occupied_preferred(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.listen(1)
        try:
            got = allocate_port("alloc-test", port)
            self.assertNotEqual(got, port)
        finally:
            sock.close()

    def test_kill_pid_zero_is_noop(self):
        kill_pid(0)


if __name__ == "__main__":
    unittest.main()
