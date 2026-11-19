"""Offline tests for the posting open/closed rule (no network, no credits)."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("triggers", ROOT / "scripts" / "02_triggers.py")
triggers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(triggers)


class ClosedRule(unittest.TestCase):
    def test_bare_false_is_not_closed(self):
        # Nov 18, 2026: 8 open postings came back is_open=false with no supporting sentence.
        self.assertFalse(triggers.page_says_closed({"is_open": False}))
        self.assertFalse(triggers.page_says_closed({"is_open": False, "closed_evidence": "Apply now"}))

    def test_closed_with_evidence(self):
        self.assertTrue(triggers.page_says_closed(
            {"is_open": False, "closed_evidence": "This job is no longer accepting applications."}))

    def test_open(self):
        self.assertFalse(triggers.page_says_closed({"is_open": True}))


if __name__ == "__main__":
    unittest.main()
