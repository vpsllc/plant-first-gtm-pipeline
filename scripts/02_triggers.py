"""Step 2: plant-level reliability hiring triggers, verified on the employer's own board.

Two sources, both read from employer boards through Firecrawl:
  a) Seed postings (config/seed_postings.csv) found in the Stage 2 scan. Each employer_url
     is opened to confirm the posting is open and to read its title, location and date.
  b) Parents with trigger_source=script and a careers_url: the board's search page is read
     once per keyword and every listed posting is filtered.

Parents with trigger_source=clay are skipped on purpose: Clay's job-openings enrichment
finds (or fails to find) their trigger, and the tier formula promotes them.

Every candidate posting is written with its keep/reject reason, so QC can see why.
Dry run by default. Add --run to spend credits.

--as-of is required: one fixed date anchors the 60-day window for every row, and the
merge labels triggers "as of" that date. Each kept trigger also gets the date it ages out.

Order of spend: seed postings first. Customer board searches (b) are optional and run
only with --boards, last, if credits allow.

Output: out/triggers.csv (all candidates), out/triggers_best.csv (one per parent)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.common import CONFIG, OUT, env, load_parents, read_csv, write_csv  # noqa: E402
from pipeline.filters import WINDOW_DAYS, evaluate, parse_posted  # noqa: E402
from pipeline.firecrawl_client import CreditCapReached, Firecrawl  # noqa: E402

POSTING_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": ["string", "null"]},
        "company": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"]},
        "posted_date": {"type": ["string", "null"]},
        "status": {"type": "string", "enum": ["open", "closed", "unclear"]},
        "status_evidence": {"type": ["string", "null"]},
    },
    "required": ["status", "status_evidence"],
}
POSTING_PROMPT = (
    "This is a single job posting page. Return the job title, the hiring company as shown, the work location "
    "(city and state as shown), and the posted or posting start date exactly as shown. "
    "Then set status: 'open' if the page shows an Apply button or link or otherwise accepts applications; "
    "'closed' only if the page explicitly says the job is closed, filled, expired, no longer available or no "
    "longer accepting applications; otherwise 'unclear'. In status_evidence, copy the exact short text from the "
    "page that shows it (for example the Apply button label, or the closed message), under 15 words."
)


def posting_status(data: dict) -> tuple[str, str]:
    """Return (open|closed|unclear, evidence). Open or closed needs evidence text from the page;
    anything else is unclear, and an unclear posting never counts as closed or as a trigger."""
    status = str(data.get("status") or "").strip().lower()
    evidence = str(data.get("status_evidence") or "").strip()
    if status in ("open", "closed") and evidence:
        return status, evidence
    return "unclear", evidence

BOARD_SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "location": {"type": ["string", "null"]},
                    "posted_date": {"type": ["string", "null"]},
                    "url": {"type": ["string", "null"]},
                },
                "required": ["title"],
            },
        }
    },
    "required": ["jobs"],
}
BOARD_PROMPT = (
    "This is a company careers search results page. List every job whose title mentions reliability, "
    "maintenance planning, condition monitoring or vibration analysis. For each, return the title, the "
    "location as shown, the posted date exactly as shown (null if not shown), and the link to the posting."
)

FIELDS = ["company", "parent", "title", "plant", "posted", "posted_iso", "date_source", "expires_iso", "as_of", "url",
          "final_url", "source", "verified_on_board", "status_evidence", "qualifies", "reason"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="spend credits (default is a dry run)")
    ap.add_argument("--limit", type=int, default=0, help="at most N Firecrawl calls")
    ap.add_argument("--as-of", required=True, help="fixed window anchor date for every row, YYYY-MM-DD")
    ap.add_argument("--keywords", default="reliability,planner",
                    help="board search keywords; each one is a separate scrape per board")
    ap.add_argument("--only", default="", help="comma-separated seed companies to (re)check")
    ap.add_argument("--boards", action="store_true",
                    help="also run customer board searches (optional, run last, credits permitting)")
    args = ap.parse_args()

    as_of = date.fromisoformat(args.as_of)
    fc = Firecrawl(env("FIRECRAWL_API_KEY", required=args.run),
                   int(env("FIRECRAWL_CREDIT_CAP", "300")), run=args.run)
    parents = {p["company"]: p for p in load_parents()}
    rows, calls = [], 0

    def budget_ok() -> bool:
        return not args.limit or calls < args.limit

    try:
        # a) Seed postings: open each on the employer board.
        only = {x.strip().lower() for x in args.only.split(",") if x.strip()}
        for seed in read_csv(CONFIG / "seed_postings.csv"):
            if only and seed["company"].lower() not in only:
                continue
            parent = parents.get(seed["company"], {}).get("parent", seed["company"])
            if not seed["employer_url"]:
                ok, reason, posted = evaluate(seed["title"], seed["location"], seed["posted_at"], as_of)
                rows.append({"company": seed["company"], "parent": parent, "title": seed["title"],
                             "plant": seed["location"], "posted": seed["posted_at"],
                             "url": seed["aggregator_url"], "source": "aggregator only",
                             "verified_on_board": False, "qualifies": False,
                             "reason": "no employer board URL; not verified" if ok else reason})
                continue
            if seed.get("confirmed_open_on"):
                # Already confirmed open on the employer's own page (by a person, or an earlier read):
                # no call, no credits. Title, plant and date come from the seed row.
                ok, reason, pdate = evaluate(seed["title"], seed["location"], seed["posted_at"], as_of)
                rows.append({"company": seed["company"], "parent": parent, "title": seed["title"],
                             "plant": seed["location"], "posted": seed["posted_at"],
                             "posted_iso": pdate.isoformat() if pdate else "",
                             "date_source": (f"posted {seed['posted_at']} per job board; confirmed open on "
                                             f"employer site {seed['confirmed_open_on']} "
                                             f"({seed.get('confirmed_by') or 'confirmed'})"),
                             "url": seed["employer_url"], "final_url": "", "source": "employer board",
                             "verified_on_board": True,
                             "status_evidence": f"open per {seed.get('confirmed_by') or 'confirmation'}",
                             "qualifies": ok, "reason": reason})
                continue
            if not budget_ok():
                break
            calls += 1
            data = fc.scrape_json(seed["employer_url"], POSTING_PROMPT, POSTING_SCHEMA,
                                  label=f"posting:{seed['company']}")
            if data is None:
                rows.append({"company": seed["company"], "parent": parent, "title": seed["title"],
                             "plant": seed["location"], "posted": seed["posted_at"],
                             "url": seed["employer_url"], "source": "employer board",
                             "verified_on_board": False, "qualifies": False,
                             "reason": "dry-run" if not args.run else "page read failed"})
                continue
            title = data.get("title") or seed["title"]
            location = data.get("location") or seed["location"]
            # The employer's own date wins when the page shows one we can read. If the employer page
            # confirms the posting is open but shows no readable date, use the seed's job-board date,
            # labeled as such. (Board-search rows get no fallback: no date, no trigger.)
            status, evidence = posting_status(data)
            employer_date = data.get("posted_date") or ""
            if parse_posted(employer_date, as_of):
                posted, date_source = employer_date, "employer site"
            else:
                posted = seed["posted_at"]
                date_source = f"posted {seed['posted_at']} per job board"
                if status == "open":
                    date_source += f"; confirmed open on employer site {as_of.isoformat()}"
            ok, reason, pdate = evaluate(title, location, posted, as_of)
            if status == "closed":
                ok, reason = False, f'closed on employer site ("{evidence}")'
            elif status == "unclear":
                ok, reason = False, "open or closed unclear on employer page; check by hand"
            rows.append({"company": seed["company"], "parent": parent, "title": title, "plant": location,
                         "posted": posted, "posted_iso": pdate.isoformat() if pdate else "",
                         "date_source": date_source,
                         "url": seed["employer_url"], "final_url": data.get("_final_url", ""),
                         "source": "employer board",
                         "verified_on_board": status == "open", "status_evidence": evidence,
                         "qualifies": ok, "reason": reason})

        # b) Board searches for script-sourced parents with a careers_url.
        if args.boards:
            for p in parents.values():
                if p["trigger_source"] != "script" or not p["careers_url"]:
                    continue
                for kw in [k.strip() for k in args.keywords.split(",") if k.strip()]:
                    if not budget_ok():
                        break
                    calls += 1
                    url = p["careers_url"].replace("{q}", kw.replace(" ", "+"))
                    data = fc.scrape_json(url, BOARD_PROMPT, BOARD_SCHEMA, label=f"board:{p['company']}:{kw}")
                    if data is None:
                        continue
                    for job in data.get("jobs", []):
                        ok, reason, pdate = evaluate(job.get("title", ""), job.get("location", ""),
                                                     job.get("posted_date", ""), as_of)
                        rows.append({"company": p["company"], "parent": p["parent"], "title": job.get("title"),
                                     "plant": job.get("location"), "posted": job.get("posted_date"),
                                     "posted_iso": pdate.isoformat() if pdate else "",
                                     "date_source": "employer board search",
                                     "url": job.get("url") or url, "source": "employer board search",
                                     "verified_on_board": True,
                             "status_evidence": f"open per {seed.get('confirmed_by') or 'confirmation'}",
                             "qualifies": ok, "reason": reason})
    except CreditCapReached as e:
        print(f"  STOP: {e}")

    # Stamp every row with the shared as-of date and each kept trigger with its age-out date.
    for r in rows:
        r["as_of"] = as_of.isoformat()
        if r.get("qualifies") is True and r.get("posted_iso"):
            r["expires_iso"] = (date.fromisoformat(r["posted_iso"]) + timedelta(days=WINDOW_DAYS)).isoformat()

    # With --only, keep earlier results for every company not re-checked in this run.
    if args.only and args.run and (OUT / "triggers.csv").exists():
        rechecked = {r["company"] for r in rows}
        kept = [r for r in read_csv(OUT / "triggers.csv") if r["company"] not in rechecked]
        for r in kept:
            r["qualifies"] = r.get("qualifies") in (True, "True")
        rows = kept + rows

    # One best trigger per parent: the most recent qualifying posting.
    best: dict[str, dict] = {}
    for r in rows:
        if r["qualifies"] is True:
            cur = best.get(r["company"])
            if cur is None or r["posted_iso"] > cur["posted_iso"]:
                best[r["company"]] = r

    if args.run:
        write_csv(OUT / "triggers.csv", rows, FIELDS)
        write_csv(OUT / "triggers_best.csv", list(best.values()), FIELDS)
        print(f"{len(rows)} candidate postings, {len(best)} parents with a qualifying trigger "
              f"(window {WINDOW_DAYS} days, as of {as_of}). Wrote out/triggers.csv and out/triggers_best.csv")
        expiring = sorted((r["expires_iso"], r["company"]) for r in best.values() if r.get("expires_iso"))
        if expiring:
            print("First triggers to age out: " + ", ".join(f"{c} {d}" for d, c in expiring[:3]))
    else:
        print(f"Dry run: {calls} calls planned; nothing written.")
    print(fc.summary())


if __name__ == "__main__":
    main()
