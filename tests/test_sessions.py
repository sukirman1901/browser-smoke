import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

from tools.persist import safe_session_name, session_cdp_port
from tools.registry import SessionRegistry


class PersistHelperTests(unittest.TestCase):
    def test_safe_session_name(self):
        self.assertEqual(safe_session_name(""), "default")
        self.assertEqual(safe_session_name("../evil"), "evil")
        self.assertEqual(safe_session_name("Work Mail"), "Work_Mail")

    def test_port_is_stable(self):
        self.assertEqual(session_cdp_port("work"), session_cdp_port("work"))
        self.assertNotEqual(session_cdp_port("work"), session_cdp_port("other"))


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


if __name__ == "__main__":
    unittest.main()
