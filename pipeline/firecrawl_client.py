"""Minimal Firecrawl v2 client with a hard credit cap and a dry-run default.

Every call is logged to out/credit_ledger.jsonl. The cap counts every run, not
just the current one, so re-running a script can never exceed FIRECRAWL_CREDIT_CAP.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import requests

from .common import OUT

API_URL = "https://api.firecrawl.dev/v2/scrape"
LEDGER = OUT / "credit_ledger.jsonl"

# Planning estimates only. Real spend comes from the API response when it reports one.
EST_JSON_SCRAPE = 5          # base page + JSON extraction
EST_PDF_PER_PAGE = 1


class CreditCapReached(RuntimeError):
    pass


def ledger_total() -> int:
    if not LEDGER.exists():
        return 0
    total = 0
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.strip():
            total += int(json.loads(line).get("credits", 0))
    return total


class Firecrawl:
    def __init__(self, api_key: str | None, cap: int, run: bool):
        self.api_key = api_key
        self.cap = cap
        self.run = run
        self.spent_before = ledger_total()
        self.planned = 0  # dry-run estimate for this session

    @property
    def spent(self) -> int:
        return ledger_total()

    def _estimate(self, pdf_max_pages: int | None) -> int:
        if pdf_max_pages:
            return EST_JSON_SCRAPE + pdf_max_pages * EST_PDF_PER_PAGE
        return EST_JSON_SCRAPE

    def scrape_json(self, url: str, prompt: str, schema: dict, *, label: str,
                    pdf_max_pages: int | None = None) -> dict | None:
        """Return the extracted JSON, or None on dry run or any failure.

        Never raises for a single bad call (network error, timeout, bad JSON, API error):
        the failure is logged to the ledger and printed, and the run moves on.
        Only CreditCapReached propagates, because that should stop the run.
        """
        est = self._estimate(pdf_max_pages)
        already = self.spent if self.run else self.spent_before + self.planned
        if already + est > self.cap:
            raise CreditCapReached(
                f"Stopping before '{label}': {already} spent/planned + ~{est} would pass cap {self.cap}."
            )

        if not self.run:
            self.planned += est
            print(f"  [dry-run] {label}: would scrape {url} (~{est} credits)")
            return None

        body = {
            "url": url,
            "formats": [{"type": "json", "prompt": prompt, "schema": schema}],
            "onlyMainContent": True,
            "timeout": 120000,
        }
        if pdf_max_pages:
            body["parsers"] = [{"type": "pdf", "maxPages": pdf_max_pages}]

        try:
            data = self._post(body)
        except Exception as e:  # network error, timeout, anything else on one call
            self._log(label, url, 0, ok=False, error=f"{type(e).__name__}: {e}")
            print(f"  ! {label}: request failed ({type(e).__name__}); logged and skipped")
            return None

        meta = (data.get("data") or {}).get("metadata") or {}
        try:
            credits = int(meta.get("creditsUsed") or (est if data.get("success") else 0))
        except (TypeError, ValueError):
            credits = est
        final_url = meta.get("url") or meta.get("sourceURL") or ""
        self._log(label, url, credits, ok=bool(data.get("success")), final_url=final_url,
                  error=None if data.get("success") else str(data.get("error"))[:300])
        if not data.get("success"):
            print(f"  ! {label}: Firecrawl error: {data.get('error')}; logged and skipped")
            return None
        result = (data.get("data") or {}).get("json")
        if not isinstance(result, dict):
            print(f"  ! {label}: no JSON in response; logged and skipped")
            return None
        result["_final_url"] = final_url
        return result

    def _post(self, body: dict, attempts: int = 3) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        for i in range(attempts):
            resp = requests.post(API_URL, headers=headers, json=body, timeout=180)
            if resp.status_code == 429 and i < attempts - 1:
                time.sleep(10 * (i + 1))
                continue
            try:
                return resp.json()
            except ValueError:
                return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        return {"success": False, "error": "rate limited"}

    def _log(self, label: str, url: str, credits: int, ok: bool,
             final_url: str = "", error: str | None = None) -> None:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "label": label, "url": url, "final_url": final_url, "credits": credits, "ok": ok,
        }
        if error:
            entry["error"] = error
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def summary(self) -> str:
        if self.run:
            return f"Firecrawl credits: {self.spent - self.spent_before} this run, {self.spent} total, cap {self.cap}."
        return (f"Dry run: ~{self.planned} credits planned. {self.spent_before} already spent, cap {self.cap}. "
                f"Re-run with --run to spend.")
