"""Step 3: merge parents, plant counts and triggers into one CSV for Clay.

Tiering, ranking and play routing are NOT done here. They are Clay formulas, so Cody
can see the logic in the table. This script only assembles clean, sourced inputs.

Rows marked row_group=not_used in config/parents.csv (Toray, per spec v1.5) are always dropped.

Output: out/clay_import.csv and out/run_report.md
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.common import OUT, load_parents, read_csv, write_csv  # noqa: E402
from pipeline.filters import WINDOW_DAYS  # noqa: E402
from pipeline.firecrawl_client import ledger_total  # noqa: E402

FIELDS = [
    # 1-2 identity and rollup
    "company", "parent", "rollup_note", "industry", "row_group",
    # 3 footprint
    "plant_count", "us_plant_count", "plant_unit", "plant_count_label", "plant_count_source_url",
    "plant_count_quote", "plant_count_method",
    # 4 Augury status
    "augury_status", "augury_confirmed_sites", "augury_source_url", "augury_announced_as_of",
    # 5 trigger
    "trigger_role", "trigger_plant", "trigger_posted", "trigger_as_of", "trigger_date_source", "trigger_expires",
    "trigger_url", "trigger_verified_on_board", "trigger_source",
    # notes for the reason column and QC
    "notes",
    # 10 tracking (left blank for Clay)
    "reply", "positive_reply", "meeting_booked", "engaged_contacts", "baseline_note",
]


def load_optional(name: str) -> list[dict]:
    path = OUT / name
    return read_csv(path) if path.exists() else []


def main() -> None:
    parents = load_parents()
    counts = {r["company"]: r for r in load_optional("plant_counts.csv")}
    triggers = {r["company"]: r for r in load_optional("triggers_best.csv")}

    as_of_values = {r.get("as_of") for r in triggers.values() if r.get("as_of")}
    if len(as_of_values) > 1:
        raise SystemExit(f"Triggers carry more than one as-of date {sorted(as_of_values)}. "
                         "Re-run 02_triggers.py once with a single --as-of.")
    as_of = next(iter(as_of_values), "")

    out, gaps, dropped = [], [], []
    for p in parents:
        if p["row_group"] == "not_used":
            dropped.append(p["company"])
            continue
        c = dict(counts.get(p["company"], {}))
        if p.get("plant_count_hand") or p.get("us_plant_count_hand"):
            # A hand count read from the saved filing text wins over the script's automatic count.
            filed = re.search(r"\(filed [^)]+\)", c.get("plant_count_label", "") or "")
            c.update(plant_count=p.get("plant_count_hand", ""), us_plant_count=p.get("us_plant_count_hand", ""),
                     plant_count_label=p["plant_count_hand_note"] + (f" {filed.group(0)}" if filed else ""),
                     method="hand count from filing text", evidence=p["plant_count_hand_note"], status="ok: hand count")
        t = triggers.get(p["company"], {})
        augury_date = p["augury_date"]
        row = {
            "company": p["company"], "parent": p["parent"], "rollup_note": p["rollup_note"],
            "industry": p["industry"], "row_group": p["row_group"],
            "plant_count": c.get("plant_count", ""), "us_plant_count": c.get("us_plant_count", ""),
            "plant_unit": c.get("unit_label", ""), "plant_count_label": c.get("plant_count_label", ""),
            "plant_count_source_url": c.get("source_url", ""), "plant_count_quote": c.get("evidence") or c.get("quote", ""),
            "plant_count_method": c.get("method", ""),
            "augury_status": p["augury_status"], "augury_confirmed_sites": p["augury_sites"],
            "augury_source_url": p["augury_source_url"],
            "augury_announced_as_of": f"publicly announced as of {augury_date}" if augury_date else "",
            "trigger_role": t.get("title", ""), "trigger_plant": t.get("plant", ""),
            "trigger_posted": t.get("posted_iso", ""),
            "trigger_as_of": f"as of {as_of}" if t else "",
            "trigger_date_source": t.get("date_source", ""),
            "trigger_expires": t.get("expires_iso", ""),
            "trigger_url": t.get("url", ""),
            "trigger_verified_on_board": t.get("verified_on_board", ""),
            "trigger_source": p["trigger_source"],
            "notes": p["notes"],
            "baseline_note": "Baseline: the prior $1B list got near-zero replies",
        }
        out.append(row)

        if (p["row_group"] != "excluded_reference" and p["plant_count_source"] != "none"
                and not row["plant_count"] and not row["us_plant_count"]):
            gaps.append(f"- {p['company']}: no plant count ({c.get('status', 'not pulled')})")
        if str(c.get("status", "")).startswith("CHECK"):
            gaps.append(f"- {p['company']}: plant count needs a hand check ({c['status']})")
        if p["trigger_source"] in ("script", "seed") and not t:
            gaps.append(f"- {p['company']}: no qualifying trigger found by the script")

    write_csv(OUT / "clay_import.csv", out, FIELDS)

    groups: dict[str, int] = {}
    for r in out:
        groups[r["row_group"]] = groups.get(r["row_group"], 0) + 1
    expiring = sorted((r["trigger_expires"], r["company"]) for r in out if r["trigger_expires"])
    report = [
        f"# Run report ({date.today().isoformat()})",
        "",
        f"- Rows written: {len(out)} ({', '.join(f'{k}: {v}' for k, v in sorted(groups.items()))})",
        f"- Trigger window: {WINDOW_DAYS} days, as of {as_of or 'n/a'}",
        f"- First triggers to age out: {', '.join(f'{c} ({d})' for d, c in expiring[:3]) or 'n/a'}",
        f"- Not used (dropped): {', '.join(dropped) or 'none'}",
        f"- Firecrawl credits spent to date (ledger): {ledger_total()}",
        "",
        "## Gaps to resolve before Clay import",
        *(gaps or ["- none"]),
    ]
    (OUT / "run_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Wrote {len(out)} rows to out/clay_import.csv and out/run_report.md ({len(gaps)} gaps).")


if __name__ == "__main__":
    main()
