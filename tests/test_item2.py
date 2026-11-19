"""Offline tests for the EDGAR Item 2 counter (no network, no credits)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.item2 import count_from_item2  # noqa: E402

TOC = """<table><tr><td>Item 2.</td><td>Properties</td><td>25</td></tr>
<tr><td>Item 3.</td><td>Legal Proceedings</td><td>26</td></tr></table>"""


def doc(item2_body: str) -> str:
    return (f"<html><body>{TOC}<p>Item 1. Business</p><p>We make things.</p>"
            f"<p>ITEM 2. PROPERTIES</p>{item2_body}<p>ITEM 3. LEGAL PROCEEDINGS</p><p>None.</p></body></html>")


def name(i: int) -> str:
    """Letter-only town names (real site names don't contain digits)."""
    return "Town " + chr(65 + i // 26) + chr(97 + i % 26)


def site_rows(sites):
    return "".join(f"<tr><td>{c}</td><td>{s}</td></tr>" for c, s in sites)


class LocationList(unittest.TestCase):
    """Shaped like Graphic Packaging's Item 2: section headers, then City / State or Country rows."""

    def test_counts_list_and_us_split(self):
        mills = [(name(i), "Georgia") for i in range(5)]
        na = [(name(i), "Ohio") for i in range(49)] + [(name(i), "Ontario, Canada") for i in range(7)]
        intl = [(name(i), "Germany") for i in range(41)]
        body = (
            "<p>Our headquarters are in Atlanta, Georgia. We have over 100 locations worldwide.</p>"
            "<table><tr><td>Paperboard Mills</td></tr>" + site_rows(mills)
            + "<tr><td>North American Packaging Plants</td></tr>" + site_rows(na)
            + "<tr><td>International Packaging Plants</td></tr>" + site_rows(intl) + "</table>"
        )
        r = count_from_item2(doc(body))
        self.assertEqual(r["method"], "location list")
        self.assertEqual(r["total_count"], 102)
        self.assertEqual(r["us_count"], 54)
        self.assertTrue(r["status"].startswith("ok"))

    def test_skips_offices_and_warehouses(self):
        body = ("<table>" + site_rows([("Macon", "Georgia"), ("Plant B", "Texas"), ("Plant C", "Ohio")])
                + "<tr><td>Atlanta corporate office</td><td>Georgia</td></tr>"
                + "<tr><td>Memphis warehouse</td><td>Tennessee</td></tr></table>")
        r = count_from_item2(doc(body))
        self.assertEqual(r["total_count"], 3)

    def test_row_filter_for_conglomerates(self):
        body = ("<table>" + "".join(f"<tr><td>Johns Manville</td><td>{name(i)}</td><td>Texas</td></tr>" for i in range(4))
                + "".join(f"<tr><td>Other Sub</td><td>{name(i)}</td><td>Ohio</td></tr>" for i in range(9)) + "</table>")
        r = count_from_item2(doc(body), row_filter="Johns Manville")
        self.assertEqual(r["total_count"], 4)


class SummaryAndProse(unittest.TestCase):
    def test_summary_table_total_row(self):
        body = ("<table><tr><td>Segment</td><td>Manufacturing Plants</td></tr>"
                "<tr><td>Foods</td><td>40</td></tr><tr><td>Beverages</td><td>60</td></tr>"
                "<tr><td>Total</td><td>100</td></tr></table>")
        r = count_from_item2(doc(body))
        self.assertEqual((r["method"], r["total_count"]), ("summary table", 100))

    def test_stated_count_is_check(self):
        r = count_from_item2(doc("<p>We operate 14 proppant production facilities in the Permian Basin.</p>"))
        self.assertEqual(r["total_count"], 14)
        self.assertTrue(r["status"].startswith("CHECK"))

    def test_missing_section(self):
        r = count_from_item2("<html><body><p>No properties here.</p></body></html>")
        self.assertTrue(r["status"].startswith("CHECK"))


if __name__ == "__main__":
    unittest.main()
