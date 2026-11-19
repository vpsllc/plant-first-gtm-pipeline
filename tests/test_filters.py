"""Offline tests for the strict trigger rules. Run: python -m unittest discover tests"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.filters import evaluate, is_named_plant, parse_posted, title_reason  # noqa: E402

AS_OF = date(2026, 11, 18)


class TitleRules(unittest.TestCase):
    def test_keeps_strict_titles(self):
        for t in ["Reliability Engineer II", "Senior Mechanical Reliability Engineer",
                  "Sr Reliability Engineer - Maintenance", "Senior Engineer - Reliability",
                  "Reliability Manager", "Maintenance Planner", "Vibration Analyst",
                  "Condition Monitoring Specialist", "Manufacturing Reliability Engineer"]:
            self.assertIsNone(title_reason(t), t)

    def test_drops_software_product_and_techs(self):
        for t in ["Site Reliability Engineer - Memphis", "Lead Site Reliability Engineer",
                  "Quality & Reliability Engineer", "Product Reliability Engineer",
                  "Build Reliability Engineer I", "Hardware Reliability Engineer",
                  "STAFF RELIABILITY & TEST ENGINEER", "Maintenance Technician II",
                  "Reliability Engineer Co-op", "Production Electrician"]:
            self.assertIsNotNone(title_reason(t), t)


class DatesAndPlaces(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(parse_posted("2026-10-28T05:00:00Z", AS_OF), date(2026, 10, 28))
        self.assertEqual(parse_posted("5/23/26", AS_OF), date(2026, 5, 23))
        self.assertEqual(parse_posted("Posted 3 days ago", AS_OF), date(2026, 11, 15))
        self.assertIsNone(parse_posted("30+ days ago", AS_OF))

    def test_named_plant(self):
        self.assertTrue(is_named_plant("Macon, GA"))
        self.assertFalse(is_named_plant("Remote"))
        self.assertFalse(is_named_plant("United States"))

    def test_window(self):
        self.assertTrue(evaluate("Reliability Engineer", "Cleburne, TX", "2026-11-13", AS_OF)[0])
        # Colgate Cambridge OH posting from 5/23/26 is outside 60 days
        ok, reason, _ = evaluate("Sr. Maintenance Reliability Engineer", "Cambridge, OH", "5/23/26", AS_OF)
        self.assertFalse(ok)
        self.assertIn("window", reason)


class QuoteCheck(unittest.TestCase):
    def setUp(self):
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "scripts" / "01_plant_counts.py"
        spec = importlib.util.spec_from_file_location("plant_counts", path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_quote_states_count(self):
        r = {"total_count": 14, "quote": "We operate 14 proppant production facilities."}
        self.assertTrue(self.mod.quote_check(r).startswith("ok"))

    def test_number_word(self):
        r = {"total_count": 6, "quote": "six float glass plants"}
        self.assertTrue(self.mod.quote_check(r).startswith("ok"))

    def test_flags_unsupported_count(self):
        r = {"total_count": 23, "quote": "We operate manufacturing plants in the United States."}
        self.assertTrue(self.mod.quote_check(r).startswith("CHECK"))

    def test_item_number_is_not_a_count(self):
        r = {"total_count": 2, "quote": "Item 2. Properties: our plants are listed below."}
        self.assertTrue(self.mod.quote_check(r).startswith("CHECK"))


class WordBoundaries(unittest.TestCase):
    """Exclusions must not fire inside longer words."""

    def test_seed_and_lookalike_titles_pass(self):
        for t in ["Senior Mechanical Reliability Engineer",        # Smurfit Westrock seed title
                  "Production Reliability Engineer",
                  "Reliability Engineer, International Operations",
                  "Reliability Engineer, Building Products"]:
            self.assertIsNone(title_reason(t), t)


class ClaySync(unittest.TestCase):
    """clay/CLAY_SETUP.md must carry the exact regexes generated from filters.py."""

    def test_clay_formula_matches_filters(self):
        from pipeline.filters import js_regex_literals
        include, exclude = js_regex_literals()
        doc = (Path(__file__).resolve().parent.parent / "clay" / "CLAY_SETUP.md").read_text(encoding="utf-8")
        self.assertIn(f"const include = {include};", doc)
        self.assertIn(f"const exclude = {exclude};", doc)


class Config(unittest.TestCase):
    def test_toray_not_used_and_no_industry_only_exclusions(self):
        import csv
        path = Path(__file__).resolve().parent.parent / "config" / "parents.csv"
        with open(path, encoding="utf-8") as f:
            rows = {r["company"]: r for r in csv.DictReader(f)}
        self.assertEqual(rows["Toray Industries"]["row_group"], "not_used")
        for r in rows.values():
            if r["row_group"] == "excluded_reference":
                self.assertNotIn("reason: industry", r["notes"].lower(), r["company"])


if __name__ == "__main__":
    unittest.main()


class HandCounts(unittest.TestCase):
    def test_hand_counts_are_numbers_with_a_source_note(self):
        import csv
        path = Path(__file__).resolve().parent.parent / "config" / "parents.csv"
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                for col in ("plant_count_hand", "us_plant_count_hand"):
                    ok = r[col] == "" or r[col].isdigit() or (col == "plant_count_hand" and r[col] == "not stated")
                    self.assertTrue(ok, (r["company"], col))
                if r["plant_count_hand"] or r["us_plant_count_hand"]:
                    self.assertTrue(r["plant_count_hand_note"], r["company"])


class SeedDateFallback(unittest.TestCase):
    def test_unreadable_employer_date_falls_back_to_seed(self):
        from pipeline.filters import parse_posted
        self.assertIsNone(parse_posted("Not specified", AS_OF))
        self.assertIsNone(parse_posted("", AS_OF))
        self.assertTrue(evaluate("Reliability Engineer", "Macon, GA", "2026-10-28", AS_OF)[0])


class PostingStatus(unittest.TestCase):
    def setUp(self):
        import importlib.util
        path = Path(__file__).resolve().parent.parent / "scripts" / "02_triggers.py"
        spec = importlib.util.spec_from_file_location("triggers", path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_open_needs_evidence(self):
        self.assertEqual(self.mod.posting_status({"status": "open", "status_evidence": "Apply"})[0], "open")
        self.assertEqual(self.mod.posting_status({"status": "open", "status_evidence": ""})[0], "unclear")

    def test_missing_status_is_unclear_not_closed(self):
        self.assertEqual(self.mod.posting_status({"title": "Reliability Engineer II"})[0], "unclear")

    def test_closed_needs_evidence(self):
        s = self.mod.posting_status({"status": "closed", "status_evidence": "This job is no longer available"})
        self.assertEqual(s[0], "closed")
