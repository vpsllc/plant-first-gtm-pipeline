"""Resolve a ticker to its latest 10-K on SEC EDGAR. Free, no API key."""
from __future__ import annotations

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

_ticker_map: dict[str, int] | None = None


def _get(url: str, user_agent: str) -> dict:
    resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def ticker_to_cik(ticker: str, user_agent: str) -> int | None:
    global _ticker_map
    if _ticker_map is None:
        data = _get(TICKERS_URL, user_agent)
        _ticker_map = {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}
    return _ticker_map.get(ticker.upper())


def latest_10k(ticker: str, user_agent: str) -> dict | None:
    """Return {'url', 'filing_date', 'cik'} for the most recent 10-K, or None."""
    cik = ticker_to_cik(ticker, user_agent)
    if cik is None:
        return None
    recent = _get(SUBMISSIONS_URL.format(cik=cik), user_agent)["filings"]["recent"]
    for form, acc, doc, date in zip(recent["form"], recent["accessionNumber"],
                                    recent["primaryDocument"], recent["filingDate"]):
        if form == "10-K":
            return {
                "url": ARCHIVE_URL.format(cik=cik, acc=acc.replace("-", ""), doc=doc),
                "filing_date": date,
                "cik": cik,
            }
    return None
