"""
SEC EDGAR — company filings straight from the primary source.

Keyless and public domain (17 U.S.C. §105), which makes it the one market-data
source here that nobody can paywall or rate-limit out from under the app.

Two rules EDGAR enforces, both learned the hard way:
  * every request must declare a contact address — a project URL earns a 403,
    an email earns a 200. ``FOLIO_SEC_CONTACT`` lets a user speak for themselves.
  * ten requests a second, tops. ``_throttle`` is the only way out of this module.

Only listed operating companies have a CIK. ETFs, funds and most foreign
listings simply aren't in the ticker map, and callers get an empty list — an
honest "nothing to show", never a fabricated timeline.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

from app.version import __version__

logger = logging.getLogger(__name__)

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"

# The maintainer is the party responsible for this app's traffic, so they are
# the default contact. Users running their own copy can say so instead.
_DEFAULT_CONTACT = "umangdhawan97@gmail.com"

_MIN_REQUEST_INTERVAL = 0.11  # SEC's ceiling is 10 req/s; sit just under it.
_TICKER_MAP_TTL = 24 * 3600  # CIKs change about as often as company names do.
_FILINGS_TTL = 30 * 60

# What belongs on a "why did this move" timeline: material events and periodic
# reports. Form 4 (insider) is deliberately absent — it's noisy here and is its
# own feature.
_MATERIAL_FORMS = (
    "8-K",
    "10-Q",
    "10-K",
    "20-F",
    "40-F",
    "6-K",
    "DEF 14A",
)

_FORM_LABELS = {
    "8-K": "Material event (8-K)",
    "10-Q": "Quarterly report (10-Q)",
    "10-K": "Annual report (10-K)",
    "20-F": "Annual report (20-F)",
    "40-F": "Annual report (40-F)",
    "6-K": "Foreign issuer report (6-K)",
    "DEF 14A": "Proxy statement",
    "4": "Insider transaction (Form 4)",
}

_lock = threading.Lock()
_THROTTLE: dict = {"last_request_at": 0.0}
_TICKER_MAP_CACHE: dict = {"fetched_at": 0.0, "raw": None}
_FILINGS_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _user_agent() -> str:
    contact = os.getenv("FOLIO_SEC_CONTACT", "").strip() or _DEFAULT_CONTACT
    return f"FolioOrb/{__version__} ({contact})"


def _throttle() -> None:
    """Serialize EDGAR calls so the whole app can't exceed SEC's fair-access rate."""
    with _lock:
        wait = _MIN_REQUEST_INTERVAL - (
            time.monotonic() - _THROTTLE["last_request_at"]
        )
        if wait > 0:
            time.sleep(wait)
        _THROTTLE["last_request_at"] = time.monotonic()


def _get(url: str) -> str | None:
    import requests

    _throttle()
    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent": _user_agent(),
                "Accept-Encoding": "gzip, deflate",
            },
        )
        if resp.status_code != 200:
            logger.debug("EDGAR %s -> HTTP %s", url, resp.status_code)
            return None
        return resp.text or None
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("EDGAR fetch failed (%s): %s", url, type(exc).__name__)
        return None


def _fetch_ticker_map() -> str | None:
    return _get(_TICKER_MAP_URL)


def _fetch_submissions(cik: str) -> str | None:
    return _get(_SUBMISSIONS_URL.format(cik=cik))


def _cik_from_map(raw_map: str, ticker: str) -> str | None:
    """Resolve a ticker to its zero-padded 10-digit CIK."""
    wanted = (ticker or "").strip().upper()
    if not wanted:
        return None
    try:
        entries = json.loads(raw_map)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(entries, dict):
        return None
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("ticker", "")).strip().upper() == wanted:
            try:
                return f"{int(entry['cik_str']):010d}"
            except (KeyError, TypeError, ValueError):
                return None
    return None


# The 8-K item codes worth naming in plain English. Unlisted codes fall back to
# "Item X.YZ" — honest, if less friendly, rather than guessed.
_ITEM_LABELS = {
    "1.01": "Entered a material agreement",
    "1.02": "Ended a material agreement",
    "2.01": "Completed an acquisition or sale",
    "2.02": "Results announced",
    "2.03": "Took on a financial obligation",
    "3.01": "Delisting notice",
    "4.01": "Changed auditors",
    "5.02": "Officer or director change",
    "5.03": "Amended bylaws or charter",
    "5.07": "Shareholder vote",
    "7.01": "Regulation FD disclosure",
    "8.01": "Other event",
    "9.01": "Financial statements filed",
}


def decode_8k_items(items: str) -> list[str]:
    """Turn an 8-K's comma-separated item codes into plain-English labels."""
    labels = []
    for code in str(items or "").split(","):
        code = code.strip()
        if not code:
            continue
        labels.append(_ITEM_LABELS.get(code, f"Item {code}"))
    return labels


def _filing_label(form: str) -> str:
    return _FORM_LABELS.get(form, form)


def _document_url(cik: str, accession: str, primary_doc: str) -> str:
    plain_cik = str(int(cik))  # Archives paths drop the zero padding
    folder = accession.replace("-", "")
    tail = primary_doc.strip() or f"{accession}-index.htm"
    return f"{_ARCHIVE_BASE}/{plain_cik}/{folder}/{tail}"


def _parse_filings(
    raw_submissions: str,
    *,
    cik: str,
    forms: tuple[str, ...] | None = None,
    limit: int = 8,
) -> list[dict]:
    """Flatten EDGAR's parallel arrays into filings, newest first."""
    try:
        payload = json.loads(raw_submissions)
        recent = payload["filings"]["recent"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []

    try:
        series = {
            name: list(recent[name])
            for name in ("form", "filingDate", "accessionNumber")
        }
    except (KeyError, TypeError):
        return []
    # The arrays are positional; if they disagree we can't trust any row.
    if len({len(v) for v in series.values()}) != 1:
        return []
    optional = {
        name: list(recent.get(name) or []) for name in ("primaryDocument", "items")
    }

    wanted = tuple(forms) if forms else _MATERIAL_FORMS
    rows = []
    for i in range(len(series["form"])):
        form = str(series["form"][i]).strip()
        if form not in wanted:
            continue
        accession = str(series["accessionNumber"][i]).strip()
        if not accession:
            continue
        rows.append(
            {
                "form": form,
                "label": _filing_label(form),
                "filed_at": str(series["filingDate"][i]).strip(),
                "items": (
                    str(optional["items"][i]).strip()
                    if i < len(optional["items"])
                    else ""
                ),
                "item_labels": decode_8k_items(
                    optional["items"][i] if i < len(optional["items"]) else ""
                ),
                "url": _document_url(
                    cik,
                    accession,
                    str(optional["primaryDocument"][i])
                    if i < len(optional["primaryDocument"])
                    else "",
                ),
            }
        )

    rows.sort(key=lambda row: row["filed_at"], reverse=True)
    return rows[:limit]


def get_recent_filings(
    ticker: str,
    *,
    limit: int = 8,
    forms: tuple[str, ...] | None = None,
    force_refresh: bool = False,
) -> list[dict]:
    """Recent material filings for a ticker; empty when EDGAR has nothing to say."""
    symbol = (ticker or "").strip().upper()
    if not symbol:
        return []

    cache_key = f"{symbol}:{limit}:{forms or ''}"
    cached = _FILINGS_CACHE.get(cache_key)
    if not force_refresh and cached and cached[0] > time.monotonic():
        return list(cached[1])

    cik = get_cik(symbol, force_refresh=force_refresh)
    if not cik:
        return []
    raw = _fetch_submissions(cik)
    if not raw:
        return []

    filings = _parse_filings(raw, cik=cik, forms=forms, limit=limit)
    _FILINGS_CACHE[cache_key] = (time.monotonic() + _FILINGS_TTL, filings)
    return list(filings)


def fetch_company_facts(cik: str) -> str | None:
    """Fetch a company's full XBRL fact set (financials), throttled like all EDGAR."""
    if not cik:
        return None
    return _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")


def fetch_filing_document(url: str) -> str | None:
    """Fetch one filing document by URL, throttled like every EDGAR call.

    URLs here originate in parsed EDGAR data; if that data were ever poisoned,
    this must not become a fetch-anything vector — sec.gov or nothing.
    """
    if not str(url or "").startswith("https://www.sec.gov/"):
        return None
    return _get(url)


def get_cik(ticker: str, *, force_refresh: bool = False) -> str | None:
    """Resolve a ticker to its SEC CIK, or None if it isn't an SEC filer."""
    now = time.monotonic()
    fresh = (
        _TICKER_MAP_CACHE["raw"]
        and now - _TICKER_MAP_CACHE["fetched_at"] < _TICKER_MAP_TTL
    )
    if force_refresh or not fresh:
        raw = _fetch_ticker_map()
        if raw:
            _TICKER_MAP_CACHE.update({"raw": raw, "fetched_at": now})
    raw_map = _TICKER_MAP_CACHE["raw"]
    if not raw_map:
        return None
    return _cik_from_map(raw_map, ticker)
