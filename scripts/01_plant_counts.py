"""Step 1: plant counts from public filings and company disclosures.

- 10-K rows: resolve the latest 10-K on SEC EDGAR, download it and count the sites listed in
  Item 2 "Properties" directly (pipeline/item2.py). Free, no model. The Item 2 text is saved to
  out/item2/<company>.txt so every count can be checked line by line.
  (A model-based count undercounted Graphic Packaging 22 vs 102 listed, so 10-Ks never use Firecrawl.)
- annual_report rows: Firecrawl extracts from the filing_url in config/parents.csv.
- company_page rows: Firecrawl extracts from a company locations, directory or operations page.
- estimate rows: copied from plant_count_manual, no call.
- none rows (excluded references): skipped.

Dry run by default. Add --run to spend credits. Add --limit 1 for the one-row test.

Output: out/plant_counts.csv
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.common import OUT, env, load_parents, read_csv, write_csv  # noqa: E402
from pipeline.firecrawl_client import CreditCapReached, Firecrawl  # noqa: E402
from pipeline.item2 import count_from_item2, fetch  # noqa: E402
from pipeline.sec import latest_10k  # noqa: E402

SCHEMA = {
    "type": "object",
    "properties": {
        "total_count": {"type": ["integer", "null"]},
        "us_count": {"type": ["integer", "null"]},
        "unit_label": {"type": ["string", "null"]},
        "as_of": {"type": ["string", "null"]},
        "quote": {"type": ["string", "null"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["total_count", "confidence"],
}

FIELDS = ["company", "parent", "plant_count", "us_plant_count", "unit_label", "as_of",
          "plant_count_label", "source_url", "method", "evidence", "quote", "confidence", "quote_check",
          "excerpt_file", "status"]

NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
                9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
                15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty"}


def quote_check(result: dict) -> str:
    """Does the supporting quote actually state the count? Counts read off a list are legitimate,
    but they get flagged so a human checks them against the filing before the row ships."""
    quote = (result.get("quote") or "").lower()
    # "Item 2. Properties" must not count as a 2 (or "Item 1A" as a 1).
    quote = re.sub(r"\bitem\s+\d+[a-z]?\b", " ", quote)
    counts = [c for c in (result.get("total_count"), result.get("us_count")) if isinstance(c, int)]
    if not counts:
        return ""
    if not quote:
        return "CHECK: no quote returned"
    for c in counts:
        if re.search(rf"\b{c}\b", quote) or (NUMBER_WORDS.get(c) and NUMBER_WORDS[c] in quote):
            return "ok: quote states the count"
    return "CHECK: quote does not state the count (counted from a list?)"


def prompt_for(row: dict) -> str:
    scope = row["plant_scope_hint"] or "manufacturing plants or production facilities"
    where = {
        "10-K": 'Item 2 "Properties" of this Form 10-K',
        "annual_report": "the operations or properties section of this annual report",
        "company_page": "this page (a company locations, directory or operations page)",
    }[row["plant_count_source"]]
    return (
        f"Using {where}, count the {scope} operated by {row['company']}. "
        "Return total_count (all locations) and us_count (United States only) if the filing states or lists them, "
        "the word the filing uses for them (unit_label), the as-of date of the figure, and one short verbatim "
        "sentence or table caption that supports the count (quote, under 25 words). "
        "Count only owned or leased production sites, not offices, warehouses or distribution centers. "
        "If the filing gives no count and no list you can count, return null counts and confidence low."
    )


def label_for(row: dict, filing_date: str | None) -> str:
    if row["plant_count_label_override"]:
        return row["plant_count_label_override"]
    if row["plant_count_source"] == "10-K":
        return f"approx., 10-K Item 2 (filed {filing_date})" if filing_date else "approx., 10-K Item 2"
    if row["plant_count_source"] == "annual_report":
        return "approx., annual report"
    if row["plant_count_source"] == "company_page":
        return "approx., company page"
    return "estimate"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="spend credits (default is a dry run)")
    ap.add_argument("--limit", type=int, default=0, help="process at most N rows that need a call")
    ap.add_argument("--only", default="", help="comma-separated company names to process")
    ap.add_argument("--resume", action="store_true",
                    help="skip companies already in out/plant_counts.csv with status ok (no re-spend after tests)")
    ap.add_argument("--pdf-max-pages", type=int, default=0,
                    help="page cap for PDF annual reports (each page costs credits)")
    args = ap.parse_args()

    fc = Firecrawl(env("FIRECRAWL_API_KEY", required=args.run),
                   int(env("FIRECRAWL_CREDIT_CAP", "300")), run=args.run)
    ua = env("SEC_USER_AGENT", required=True)
    only = {s.strip().lower() for s in args.only.split(",") if s.strip()}
    out_path = OUT / "plant_counts.csv"
    existing = {r["company"]: r for r in read_csv(out_path)} if out_path.exists() else {}

    out_rows, calls = [], 0
    for row in load_parents():
        if only and row["company"].lower() not in only:
            continue
        if args.resume and str(existing.get(row["company"], {}).get("status", "")).startswith("ok"):
            continue
        base = {"company": row["company"], "parent": row["parent"]}
        src = row["plant_count_source"]

        if src == "none":
            continue
        if src == "estimate":
            out_rows.append({**base, "plant_count": row["plant_count_manual"],
                             "plant_count_label": label_for(row, None),
                             "status": "estimate" if row["plant_count_manual"] else "MISSING estimate"})
            continue

        url, filing_date = row["filing_url"], None
        if src == "10-K" and not url:
            try:
                found = latest_10k(row["ticker"], ua) if row["ticker"] else None
            except Exception as e:  # one bad EDGAR lookup must not stop the run
                print(f"  ! EDGAR lookup failed for {row['company']}: {type(e).__name__}; skipped")
                out_rows.append({**base, "status": f"EDGAR lookup failed ({type(e).__name__})"})
                continue
            if not found:
                out_rows.append({**base, "status": "no 10-K found (add filing_url)"})
                continue
            url, filing_date = found["url"], found["filing_date"]
        if not url:
            out_rows.append({**base, "status": "MISSING filing_url"})
            continue

        if src == "10-K":
            if not args.run:
                print(f"  [dry-run] {row['company']}: would read Item 2 from {url} (EDGAR, free)")
                continue
            try:
                result = count_from_item2(fetch(url, ua), row.get("item2_filter", ""))
            except Exception as e:  # one bad download or parse must not stop the run
                print(f"  ! {row['company']}: EDGAR read failed ({type(e).__name__}); skipped")
                out_rows.append({**base, "source_url": url, "status": f"EDGAR read failed ({type(e).__name__})"})
                continue
            excerpt_path = OUT / "item2" / (re.sub(r"[^a-z0-9]+", "_", row["company"].lower()).strip("_") + ".txt")
            excerpt_path.parent.mkdir(parents=True, exist_ok=True)
            excerpt_path.write_text(f"{row['company']} | {url}\n\n{result['excerpt']}", encoding="utf-8")
            print(f"  {row['company']}: {result['total_count']} total / {result['us_count']} US "
                  f"({result['method'] or 'no method'}) -> {result['status']}")
            out_rows.append({
                **base,
                "plant_count": result["total_count"], "us_plant_count": result["us_count"],
                "plant_count_label": label_for(row, filing_date), "source_url": url,
                "method": result["method"], "evidence": result["evidence"], "quote": result["quote"],
                "excerpt_file": str(excerpt_path.relative_to(OUT.parent)), "status": result["status"],
            })
            continue

        if args.limit and calls >= args.limit:
            break
        calls += 1
        is_pdf = url.lower().split("?")[0].endswith(".pdf")
        row_cap = int(row["pdf_max_pages"]) if (row.get("pdf_max_pages") or "").isdigit() else 0
        pdf_pages = (args.pdf_max_pages or row_cap) if is_pdf else None
        if is_pdf and not pdf_pages:
            out_rows.append({**base, "source_url": url, "status": "PDF: set pdf_max_pages or pass --pdf-max-pages N"})
            continue
        try:
            result = fc.scrape_json(url, prompt_for(row), SCHEMA, label=f"plants:{row['company']}",
                                    pdf_max_pages=pdf_pages)
        except CreditCapReached as e:
            print(f"  STOP: {e}")
            break

        if result is None:
            out_rows.append({**base, "source_url": url, "plant_count_label": label_for(row, filing_date),
                             "status": "dry-run" if not args.run else "extraction failed"})
            continue
        out_rows.append({
            **base,
            "plant_count": result.get("total_count"),
            "us_plant_count": result.get("us_count"),
            "unit_label": result.get("unit_label"),
            "as_of": result.get("as_of"),
            "plant_count_label": label_for(row, filing_date),
            "source_url": url,
            "quote": result.get("quote"),
            "confidence": result.get("confidence"),
            "method": "firecrawl extraction",
            "quote_check": quote_check(result),
            "status": ("ok" if result.get("total_count") is not None and quote_check(result).startswith("ok")
                       else "CHECK: " + (quote_check(result) or "no count on page")),
        })

    if args.run:
        # Merge with earlier runs: new rows replace old ones for the same company, others are kept.
        merged = {**existing, **{r["company"]: r for r in out_rows}}
        write_csv(out_path, list(merged.values()), FIELDS)
        print(f"Wrote {len(out_rows)} new rows; out/plant_counts.csv now has {len(merged)} rows")
    else:
        print(f"Dry run covered {len(out_rows)} rows; nothing written.")
    print(fc.summary())


if __name__ == "__main__":
    main()
