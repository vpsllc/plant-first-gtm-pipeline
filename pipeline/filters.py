"""Strict trigger rules from the spec. Titles are never loosened."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

WINDOW_DAYS = 60

# Spec titles: reliability engineer, maintenance planner, reliability manager,
# condition monitoring or vibration analyst.
INCLUDE = [
    r"\breliability\s+engineer",
    r"\bengineer\W+(?:mechanical\s+)?reliability\b",      # "Senior Engineer - Reliability"
    r"\breliability\s+(?:engineering\s+)?manager",
    r"\bmaintenance\s+(?:&\s+reliability\s+)?planner",
    r"\bcondition\s+monitoring\s+(?:analyst|engineer|specialist)",
    r"\bvibration\s+analyst",
]

# Software, product and test reliability roles, plus maintenance techs (always hiring).
EXCLUDE = [
    r"\bsite\s+reliability", r"\bsre\b", r"\bsoftware\b", r"\bdevops\b", r"\bcloud\b",
    r"\bobservability\b", r"\bquality\b", r"\bproduct\b", r"\bbuild\b", r"\bhardware\b",
    r"\btest\b", r"\bsystems?\s+safety\b", r"\bdata\s+center\b",
    r"\bmaintenance\s+tech", r"\btechnician\b", r"\bmechanic\b", r"\belectrician\b",
    r"\bintern\b", r"\bco-?op\b",
]

NOT_A_PLANT = re.compile(r"^\s*(remote|telecommute|multiple|various|united states|usa|us)\s*$", re.I)
CITY_STATE = re.compile(r"[A-Za-z .'-]+,\s*[A-Za-z]{2,}")


def title_reason(title: str) -> str | None:
    """None if the title qualifies, else the rejection reason."""
    t = (title or "").lower()
    for pat in EXCLUDE:
        if re.search(pat, t):
            return f"excluded title ({pat})"
    if not any(re.search(p, t) for p in INCLUDE):
        return "title not on strict list"
    return None


def parse_posted(value: str, as_of: date) -> date | None:
    """Parse '2026-10-28', '2026-10-28T05:00:00Z', '10/28/26', '10/28/2026', 'Posted 3 days ago', 'today'."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if v in {"today", "posted today", "just posted"}:
        return as_of
    if "yesterday" in v:
        return as_of - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s+days?\s+ago", v)
    if m:
        if "+" in v:          # "30+ days ago" has no real date
            return None
        return as_of - timedelta(days=int(m.group(1)))
    m = re.search(r"\d{4}-\d{2}-\d{2}", v)
    if m:
        return datetime.strptime(m.group(0), "%Y-%m-%d").date()
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        m = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", v)
        if m:
            try:
                return datetime.strptime(m.group(0), fmt).date()
            except ValueError:
                continue
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def is_named_plant(location: str) -> bool:
    loc = (location or "").strip()
    if not loc or NOT_A_PLANT.match(loc):
        return False
    return bool(CITY_STATE.search(loc))


def evaluate(title: str, location: str, posted: str, as_of: date,
             window_days: int = WINDOW_DAYS) -> tuple[bool, str, date | None]:
    """Return (qualifies, reason, posted_date)."""
    reason = title_reason(title)
    if reason:
        return False, reason, None
    if not is_named_plant(location):
        return False, "no named plant location", None
    posted_date = parse_posted(posted, as_of)
    if posted_date is None:
        return False, "posting date unknown", None
    age = (as_of - posted_date).days
    if age < 0 or age > window_days:
        return False, f"posted {age} days ago (window {window_days})", posted_date
    return True, "qualifies", posted_date


def js_regex_literals() -> tuple[str, str]:
    """INCLUDE and EXCLUDE as JavaScript regex literals for the Clay formula.

    These are the exact same patterns joined with '|', every \\b kept. clay/CLAY_SETUP.md
    must carry these strings verbatim; tests/test_filters.py fails if they drift.
    Regenerate with: python scripts/print_clay_regex.py
    """
    include = "/" + "|".join(INCLUDE) + "/i"
    exclude = "/" + "|".join(EXCLUDE) + "/i"
    return include, exclude
