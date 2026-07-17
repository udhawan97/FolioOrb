"""Tests for the SEC EDGAR filings source."""
import json

from app.services import edgar_service
from app.services.edgar_service import (
    _cik_from_map,
    _filing_label,
    _parse_filings,
    _user_agent,
    get_recent_filings,
)

# Shapes copied from the live endpoints (sec.gov/files/company_tickers.json and
# data.sec.gov/submissions/CIK0000320193.json), trimmed to what we read.
_TICKER_MAP = json.dumps(
    {
        "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
        "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    }
)

_SUBMISSIONS = json.dumps(
    {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "form": ["4", "8-K", "10-Q", "SD", "8-K"],
                "filingDate": [
                    "2026-06-17",
                    "2026-06-10",
                    "2026-05-02",
                    "2026-05-28",
                    "2026-01-30",
                ],
                "accessionNumber": [
                    "0001140361-26-025622",
                    "0000320193-26-000056",
                    "0000320193-26-000052",
                    "0001140361-26-023149",
                    "0000320193-26-000008",
                ],
                "primaryDocument": [
                    "xslF345X06/form4.xml",
                    "aapl-20260610.htm",
                    "aapl-20260502.htm",
                    "ef20073373_sd.htm",
                    "",
                ],
                "primaryDocDescription": ["FORM 4", "8-K", "10-Q", "SD", "8-K"],
                "items": ["", "2.02,9.01", "", "", "5.02"],
                "reportDate": ["", "2026-06-10", "2026-03-28", "", "2026-01-30"],
            }
        },
    }
)


def test_cik_is_zero_padded_to_ten_digits():
    assert _cik_from_map(_TICKER_MAP, "AAPL") == "0000320193"


def test_cik_lookup_ignores_case_and_padding():
    assert _cik_from_map(_TICKER_MAP, " nvda ") == "0001045810"


def test_cik_unknown_ticker():
    assert _cik_from_map(_TICKER_MAP, "NOTATICKER") is None


def test_cik_map_garbage():
    assert _cik_from_map("not json", "AAPL") is None


def test_parse_returns_material_filings_newest_first():
    filings = _parse_filings(_SUBMISSIONS, cik="0000320193")
    assert [f["form"] for f in filings] == ["8-K", "10-Q", "8-K"]
    assert filings[0]["filed_at"] == "2026-06-10"


def test_parse_excludes_insider_and_niche_forms_by_default():
    # Form 4 is its own feature; SD would just be noise in a move timeline.
    forms = {f["form"] for f in _parse_filings(_SUBMISSIONS, cik="0000320193")}
    assert "4" not in forms
    assert "SD" not in forms


def test_parse_builds_a_resolvable_document_url():
    filings = _parse_filings(_SUBMISSIONS, cik="0000320193")
    assert filings[0]["url"] == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019326000056/aapl-20260610.htm"
    )


def test_parse_falls_back_to_the_filing_index_without_a_primary_document():
    filings = _parse_filings(_SUBMISSIONS, cik="0000320193", limit=10)
    no_doc = [f for f in filings if f["filed_at"] == "2026-01-30"][0]
    assert no_doc["url"] == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019326000008/0000320193-26-000008-index.htm"
    )


def test_parse_honors_an_explicit_form_filter():
    filings = _parse_filings(_SUBMISSIONS, cik="0000320193", forms=("10-Q",))
    assert [f["form"] for f in filings] == ["10-Q"]


def test_parse_respects_the_limit():
    assert len(_parse_filings(_SUBMISSIONS, cik="0000320193", limit=1)) == 1


def test_parse_carries_8k_item_codes():
    filings = _parse_filings(_SUBMISSIONS, cik="0000320193")
    assert filings[0]["items"] == "2.02,9.01"


def test_parse_survives_a_malformed_payload():
    assert not _parse_filings('{"filings": {}}', cik="0000320193")
    assert not _parse_filings("not json", cik="0000320193")


def test_parse_survives_ragged_arrays():
    # Defensive: EDGAR's parallel arrays are only useful if they line up.
    ragged = json.dumps(
        {"filings": {"recent": {"form": ["8-K", "10-Q"], "filingDate": ["2026-06-10"]}}}
    )
    assert not _parse_filings(ragged, cik="0000320193")


def test_labels_are_human_readable():
    assert "8-K" in _filing_label("8-K")
    assert _filing_label("8-K") != "8-K"
    assert "10-K" in _filing_label("10-K")


def test_unknown_form_falls_back_to_the_bare_code():
    assert _filing_label("XYZ-9") == "XYZ-9"


def test_user_agent_declares_a_contact_address():
    # SEC hands out 403s to any agent without a contact; a URL is not enough.
    assert "@" in _user_agent()
    assert "FolioOrb" in _user_agent()


def test_user_agent_is_overridable(monkeypatch):
    monkeypatch.setenv("FOLIO_SEC_CONTACT", "someone@example.com")
    assert "someone@example.com" in _user_agent()


def test_get_recent_filings_for_a_known_ticker(monkeypatch):
    monkeypatch.setattr(edgar_service, "_fetch_ticker_map", lambda: _TICKER_MAP)
    monkeypatch.setattr(edgar_service, "_fetch_submissions", lambda cik: _SUBMISSIONS)
    filings = get_recent_filings("AAPL", force_refresh=True)
    assert [f["form"] for f in filings] == ["8-K", "10-Q", "8-K"]
    assert filings[0]["label"] == _filing_label("8-K")


def test_get_recent_filings_is_empty_for_an_etf_with_no_cik(monkeypatch):
    # ETFs and foreign listings simply aren't in the ticker map — that's an
    # honest empty state, not an error.
    monkeypatch.setattr(edgar_service, "_fetch_ticker_map", lambda: _TICKER_MAP)
    monkeypatch.setattr(edgar_service, "_fetch_submissions", lambda cik: _SUBMISSIONS)
    assert not get_recent_filings("VOO", force_refresh=True)


def test_get_recent_filings_is_empty_when_edgar_is_unreachable(monkeypatch):
    monkeypatch.setattr(edgar_service, "_fetch_ticker_map", lambda: None)
    monkeypatch.setattr(edgar_service, "_fetch_submissions", lambda cik: None)
    assert not get_recent_filings("AAPL", force_refresh=True)


def test_get_recent_filings_is_empty_for_a_blank_ticker():
    assert not get_recent_filings("", force_refresh=True)


def test_get_recent_filings_serves_from_cache(monkeypatch):
    monkeypatch.setattr(edgar_service, "_fetch_ticker_map", lambda: _TICKER_MAP)
    calls: list[str] = []

    def _counted(cik):
        calls.append(cik)
        return _SUBMISSIONS

    monkeypatch.setattr(edgar_service, "_fetch_submissions", _counted)
    get_recent_filings("AAPL", force_refresh=True)
    get_recent_filings("AAPL")
    assert len(calls) == 1


# --- fetching a filing document (Form 4 XML etc.) ---


def test_fetch_filing_document_refuses_non_sec_hosts(monkeypatch):
    # This function takes URLs that originated in parsed EDGAR data; if that
    # data were ever poisoned, the fetcher must not become an SSRF vector.
    calls: list[str] = []
    monkeypatch.setattr(edgar_service, "_get", lambda url: calls.append(url) or "x")
    assert edgar_service.fetch_filing_document("https://evil.example/form4.xml") is None
    assert not calls


def test_fetch_filing_document_fetches_sec_urls(monkeypatch):
    monkeypatch.setattr(edgar_service, "_get", lambda url: "<xml/>")
    url = "https://www.sec.gov/Archives/edgar/data/1/2/form4.xml"
    assert edgar_service.fetch_filing_document(url) == "<xml/>"


# --- 8-K item codes decoded to plain English ---


def test_decode_8k_items_names_the_common_ones():
    labels = edgar_service.decode_8k_items("2.02,9.01")
    assert "Results announced" in labels
    assert any("financial statement" in s.lower() for s in labels)


def test_decode_8k_names_an_officer_change():
    assert any("officer" in s.lower() or "director" in s.lower()
               for s in edgar_service.decode_8k_items("5.02"))


def test_decode_8k_keeps_unknown_codes_as_the_bare_code():
    assert edgar_service.decode_8k_items("9.99") == ["Item 9.99"]


def test_decode_8k_handles_blank_and_whitespace():
    assert not edgar_service.decode_8k_items("")
    assert edgar_service.decode_8k_items("  2.02 , 9.01 ")[0] == "Results announced"


def test_parse_filings_attaches_decoded_item_labels():
    filings = _parse_filings(_SUBMISSIONS, cik="0000320193")
    eightk = [f for f in filings if f["form"] == "8-K"][0]
    assert isinstance(eightk["item_labels"], list)
    assert "Results announced" in eightk["item_labels"]
