import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

from tools.persist import (
    allocate_port,
    kill_pid,
    normalize_cdp_endpoint,
    port_free,
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

    def test_none_is_empty_dict(self):
        self.assertEqual(coerce_rpc_params("wait", None), {})


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
