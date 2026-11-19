"""Count plants straight from a 10-K's Item 2 "Properties" section. No model, no credits.

Why: a model asked to count a 100-row location list inside a full 10-K undercounted badly
(Graphic Packaging: model said 22 total / 5 US; the filing lists 102 / 54). Reading the list
directly is free and every count traces back to lines in the filing.

Method, in order of preference:
  1. summary table  - a table in Item 2 with a "plants / facilities / mills" column of numbers
                      (uses its Total row if there is one, else sums the column)
  2. location list  - table rows or lines that look like a site ("Macon, Georgia", "Macon, GA"),
                      excluding offices, warehouses, distribution and R&D; US counted separately
  3. stated count   - a sentence like "we operate 54 manufacturing facilities" (always CHECK)
Anything else comes back CHECK. The Item 2 text is always saved so a human can verify.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

import requests

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "puerto rico": "PR",
}
STATE_ABBRS = set(US_STATES.values())

NON_PLANT = re.compile(
    r"\b(office|offices|headquarter|headquarters|warehouse|warehouses|distribution|"
    r"research|r&d|sales|administrative|corporate|data center|showroom|retail)\b", re.I)
SITE_LINE = re.compile(r"^[A-Za-z .'\-]{2,40},\s*[A-Za-z .]{2,30}$")
COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
               "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20}
STATED = re.compile(
    r"\b(\d{1,4}|" + "|".join(COUNT_WORDS) + r")\s+(?:[a-z\-]+\s+){0,3}?"
    r"(plants|facilities|mills|manufacturing sites|production centers|breweries|production facilities)\b",
    re.I)
# One table cell that is just a site: "Macon, GA", "Elk Grove, IL(a)(b)", "Jundiai, Sao Paulo, Brazil".
SITE_CELL = re.compile(r"^[^\W\d_][^\W\d_ .'\-]*(?:[ .'\-]+[^\W\d_]+)*\.?"
                       r"(?:,\s*[^\W\d_][^\W\d_ .'\-]*(?:[ .'\-]+[^\W\d_]+)*\.?){1,2}(?:\([a-z]\))*$")
FOOTNOTE = re.compile(r"(?:\([a-z]\))+$")
# A list can be only a sample of the footprint ("Significant properties by segment are as follows").
SAMPLE_LIST = re.compile(r"\b(significant|principal significant|selected|representative|largest)\s+"
                         r"(properties|facilities|plants|locations)\b", re.I)
PLANT_HEADER = re.compile(r"plants?|facilit|mills?|manufactur|production", re.I)

BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}


class _Blocks(HTMLParser):
    """Linearize HTML into ('text', str) and ('table', [[cell, ...], ...]) blocks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, object]] = []
        self._buf: list[str] = []
        self._table_depth = 0
        self._rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def _flush_text(self):
        text = " ".join("".join(self._buf).split())
        if text:
            self.blocks.append(("text", text))
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self._table_depth == 0:
                self._flush_text()
                self._rows = []
            self._table_depth += 1
        elif self._table_depth:
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th"):
                self._cell = []
        elif tag in BLOCK_TAGS:
            self._flush_text()

    def handle_endtag(self, tag):
        if tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0:
                rows = [r for r in self._rows if any(c for c in r)]
                if rows:
                    self.blocks.append(("table", rows))
        elif self._table_depth:
            if tag in ("td", "th") and self._cell is not None and self._row is not None:
                self._row.append(" ".join("".join(self._cell).split()))
                self._cell = None
            elif tag == "tr" and self._row is not None:
                self._rows.append([c for c in self._row if c])
                self._row = None
        elif tag in BLOCK_TAGS:
            self._flush_text()

    def handle_data(self, data):
        if self._table_depth:
            if self._cell is not None:
                self._cell.append(data)
        else:
            self._buf.append(data)

    def close(self):
        super().close()
        self._flush_text()


def html_blocks(html: str) -> list[tuple[str, object]]:
    p = _Blocks()
    p.feed(html)
    p.close()
    return p.blocks


def _block_text(block) -> str:
    kind, val = block
    return val if kind == "text" else " | ".join(" ".join(r) for r in val)


def item2_section(blocks) -> list:
    """The longest run of blocks from an 'Item 2 ... Properties' heading to the next 'Item 3'."""
    starts = []
    for i, (kind, val) in enumerate(blocks):
        if kind != "text":
            continue
        t = val.lower()
        nxt = blocks[i + 1][1].lower() if i + 1 < len(blocks) and blocks[i + 1][0] == "text" else ""
        if re.match(r"^item\s*2\b", t) and ("propert" in t or nxt.startswith("propert")) and len(t) < 120:
            starts.append(i)
    best: list = []
    for s in starts:
        end = len(blocks)
        for j in range(s + 1, len(blocks)):
            if blocks[j][0] == "text" and re.match(r"^item\s*3\b", blocks[j][1].lower()):
                end = j
                break
        if end - s > len(best):
            best = blocks[s:end]
    return best


def _is_us(text: str) -> bool:
    t = text.lower()
    if "united states" in t or re.search(r"\bu\.s\.", t):
        return True
    if any(re.search(rf"\b{name}\b", t) for name in US_STATES):
        return True
    abbr = re.search(r",\s*([A-Z]{2})\b", text)
    return bool(abbr and abbr.group(1) in STATE_ABBRS)


def _to_int(cell: str) -> int | None:
    c = cell.replace(",", "").strip()
    return int(c) if re.fullmatch(r"\d{1,4}", c) else None


def _summary_table(rows: list[list[str]], row_filter: str) -> tuple[int, str] | None:
    """A table with a plants/facilities column of numbers. Returns (count, evidence)."""
    for h, header in enumerate(rows[:3]):
        cols = [i for i, c in enumerate(header) if PLANT_HEADER.search(c) and not NON_PLANT.search(c)]
        if not cols:
            continue
        col = cols[0]
        total_row, total, used = None, 0, []
        for r in rows[h + 1:]:
            if len(r) <= col:
                continue
            label = " ".join(r[:col]) if col else r[0]
            if row_filter and row_filter.lower() not in " ".join(r).lower():
                continue
            n = _to_int(r[col])
            if n is None:
                continue
            if re.search(r"\btotal\b", label, re.I):
                total_row = (n, " ".join(r))
            else:
                total += n
                used.append(f"{label}: {n}")
        if total_row:
            return total_row[0], f"Item 2 table total row: {total_row[1]}"
        if used:
            return total, "Item 2 table, summed: " + "; ".join(used[:12])
    return None


def _subheader(row: list[str]) -> str | None:
    """A one-cell row like "North American Packaging Facilities:" or "Other:"."""
    if len(row) == 1 and "," not in row[0] and len(row[0]) < 80:
        return row[0]
    return None


def _location_rows(section, row_filter: str) -> list[str]:
    sites = []
    for kind, val in section:
        candidates = []
        if kind == "table":
            skip = False
            for r in val:
                head = _subheader(r)
                if head is not None:
                    # Sites listed under "Other:" or "Offices:" are not plants.
                    skip = bool(re.match(r"^\s*other\b", head, re.I) or NON_PLANT.search(head))
                    continue
                if skip:
                    continue
                line = ", ".join(r)
                if row_filter and row_filter.lower() not in line.lower():
                    continue
                if len(r) >= 2 and all(SITE_CELL.match(c) for c in r):
                    # Grid layout: several sites per table row, one per cell.
                    candidates.extend(FOOTNOTE.sub("", c) for c in r)
                else:
                    candidates.append(line)
        else:
            if SITE_LINE.match(val) and not (row_filter and row_filter.lower() not in val.lower()):
                candidates.append(val)
        for line in candidates:
            if NON_PLANT.search(line) or re.search(r"\b(total|location|segment)\b", line, re.I):
                continue
            first = line.split(",")[0]
            if re.search(r"\d", first) or len(first) > 40:
                continue
            if "," not in line and not _is_us(line):
                continue
            sites.append(line)
    return sites


def count_from_item2(html: str, row_filter: str = "") -> dict:
    """Return {total_count, us_count, method, evidence, quote, status, excerpt}."""
    section = item2_section(html_blocks(html))
    excerpt = "\n".join(_block_text(b) for b in section)
    out = {"total_count": None, "us_count": None, "method": "", "evidence": "", "quote": "",
           "status": "", "excerpt": excerpt}
    if not section:
        out["status"] = "CHECK: Item 2 section not found"
        return out
    out["quote"] = next((_block_text(b) for b in section[1:] if b[0] == "text" and len(b[1]) > 40), "")[:300]

    summary = None
    for kind, val in section:
        if kind == "table":
            summary = _summary_table(val, row_filter)
            if summary:
                break
    sites = _location_rows(section, row_filter)

    if len(sites) >= 3:
        us = [s for s in sites if _is_us(s)]
        out.update(total_count=len(sites), us_count=len(us), method="location list",
                   evidence=f"{len(sites)} listed sites ({len(us)} US), e.g. " + " / ".join(sites[:5]),
                   status="ok: counted the Item 2 location list")
        if SAMPLE_LIST.search(excerpt):
            out["status"] = (f"CHECK: Item 2 lists only {SAMPLE_LIST.search(excerpt).group(0).lower()}, "
                             "not every plant; the list count is not a plant count")
        elif summary and summary[0] != len(sites):
            out["status"] = (f"CHECK: location list gives {len(sites)}, a summary table gives {summary[0]} "
                             f"({summary[1][:120]})")
        return out
    if summary:
        out.update(total_count=summary[0], method="summary table", evidence=summary[1],
                   status="ok: read from Item 2 summary table (US split not stated)")
        return out

    for kind, val in section:
        if kind != "text":
            continue
        m = STATED.search(val)
        if m and not NON_PLANT.search(val[max(0, m.start() - 40):m.end() + 40]):
            word = m.group(1).lower()
            n = COUNT_WORDS.get(word) or int(word)
            out.update(total_count=n, method="stated count", evidence=val[:300], quote=val[:300],
                       status="CHECK: stated count in prose, confirm scope by hand")
            return out

    out["status"] = "CHECK: no list, table or stated count found; see excerpt"
    return out


def fetch(url: str, user_agent: str) -> str:
    resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=60)
    resp.raise_for_status()
    return resp.text
