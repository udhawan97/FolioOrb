"""Frozen-input financial coverage across services and actual exported receipts."""
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import socket
from zipfile import ZipFile

import pytest
from sqlalchemy import event, select

from app.models import Base, Holding, Portfolio, PortfolioSnapshot, RealizedTrade
from app.services import (
    portfolio_planning as planning, portfolio_review as review,
    portfolio_valuation as valuation, review_bundle,
)
from app.services.ttl_cache import ttl_cache

CASES = [
    ("complete_usd", ["USD"], ["USD"], "complete", 40, [], []),
    ("one_missing", ["USD", "MISS"], ["USD"], "partial", 40, ["MISS"], []),
    ("all_missing", ["USD"], [], "unavailable", 0, ["USD"], []),
    ("foreign_gbp", ["USD", "VOD.L", "CAD"], ["USD", "VOD.L", "CAD"],
     "partial", 40, [], ["CAD", "VOD.L"]),
    ("mixed_realized", ["USD"], ["USD"], "partial", 40, [], []),
    ("mixed_realized_empty", [], [], "partial", 0, [], []),
    ("mixed_realized_watchlist", ["WATCH"], ["WATCH"], "partial", 0, [], []),
    ("watchlist_only", ["WATCH"], ["WATCH"], "complete", 0, [], []),
    ("empty", [], [], "complete", 0, [], []),
]


def _snapshot(db):
    return {table.name: list(db.execute(select(table))) for table in Base.metadata.sorted_tables}


def _seed(db, tickers, mixed=False):
    db.add(Portfolio(id=2, name="Fictional other book"))
    db.add(Holding(portfolio_id=2, ticker="OTHER", shares=99, avg_cost=99))
    for index, ticker in enumerate(tickers):
        db.add(Holding(portfolio_id=1, ticker=ticker, shares=2, avg_cost=10,
                       notes="Fictional matrix", is_watchlist=ticker == "WATCH",
                       target_weight_bps=(10000 // len(tickers) if index else
                                          10000 - (len(tickers) - 1) * (10000 // len(tickers)))))
    if mixed:
        for currency, source, days in [("USD", "manual_entry", 0),
                                       ("CAD", "manual_entry", 0),
                                       (None, "legacy_unknown", 100)]:
            db.add(RealizedTrade(portfolio_id=1, ticker="SOLD", shares_sold=1,
                                 avg_cost=10, sale_price=12, realized_gain=2,
                                 sale_currency=currency, sale_price_source=source,
                                 created_at=datetime.now() - timedelta(days=days)))
    db.add(RealizedTrade(portfolio_id=2, ticker="OTHER", shares_sold=1, avg_cost=1,
                         sale_price=100, realized_gain=99, sale_currency="CAD",
                         sale_price_source="manual_entry"))
    db.commit()


def _loader(tickers):
    quotes = [{"ticker": ticker, "current_price": 20, "day_change": 1,
               "currency": "GBp" if ticker == "VOD.L" else "CAD" if ticker == "CAD" else "USD",
               "quote_type": "EQUITY", "sector": "Fictional"} for ticker in tickers]
    return lambda requested: [dict(q) for q in quotes if q["ticker"] in requested]


def _surfaces(db, load):
    return (
        valuation.evaluate(db, 1, quote_loader=load),
        review.build_trust_center(db, 1, quote_loader=load, valuation_quote_loader=load),
        planning.build_target_plan(db, 1, quote_loader=load),
        review.build_review_report(db, 1, "month", quote_loader=load),
    )


def _csv(text):
    return list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))


@pytest.fixture(autouse=True)
def _deny_external(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Matrix must not perform external I/O or AI work")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.setattr("anthropic.resources.messages.Messages.create", forbidden)


def _assert_bundle_receipts(bundle, *, quality, known, excluded):
    with ZipFile(io.BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["data_quality"]["review_valuation"] == quality
        assert manifest["data_quality"]["target_plan_valuation"] == quality
        report_rows = _csv(archive.read("review-pack.csv").decode("utf-8-sig"))
        trust_rows = _csv(archive.read("data-health.csv").decode("utf-8-sig"))
        plan_rows = _csv(archive.read("target-plan.csv").decode("utf-8-sig"))
        assert ["coverage", "excluded_realized_trade_count", str(excluded)] in report_rows
        assert ["excluded_realized_trade_count", str(excluded)] in trust_rows
        assert ["excluded_realized_trade_count", str(excluded)] in plan_rows
        generated = manifest["generated_at_utc"]
        assert ["coverage", "generated_at", generated] in report_rows
        assert ["generated_at", generated] in trust_rows
        assert ["generated_at", generated] in plan_rows
        assert generated in archive.read("review-pack.html").decode()
        assert ["known_value", str(float(known))] in plan_rows
        assert ["current", "known_value", str(float(known))] in report_rows
        if excluded:
            assert "all time" in archive.read("review-pack.html").decode()
            assert "all time" in archive.read("data-health.csv").decode()
            assert "all time" in archive.read("target-plan.csv").decode()



@pytest.mark.parametrize("case", CASES, ids=lambda case: case[0])
def test_frozen_cross_surface_matrix(db, case):
    name, tickers, quoted, quality, known, missing, foreign = case
    _seed(db, tickers, mixed=name.startswith("mixed_realized"))
    load = _loader(quoted)
    before = _snapshot(db)

    def deny_writes(_conn, _cursor, statement, *_args):
        assert statement.lstrip().split()[0].upper() not in {
            "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER",
        }, "Financial matrix surfaces must remain read-only"

    event.listen(db.bind, "before_cursor_execute", deny_writes)
    try:
        valued, trust, plan, report = _surfaces(db, load)
        bundle = review_bundle.build_review_bundle(db, 1, "month", quote_loader=load)
        assert review_bundle.verify_review_bundle(bundle)["valid"]
    finally:
        event.remove(db.bind, "before_cursor_execute", deny_writes)
    assert _snapshot(db) == before
    price_area = next(area for area in trust["areas"] if area["key"] == "prices")
    assert valued.total_value == plan["known_value"] == report["current"]["known_value"] == known
    assert valued.data_quality == price_area["quality"] == plan["valuation_quality"] == quality
    assert report["data_quality"]["valuation"] == quality
    assert list(valued.missing_tickers) == plan["missing_tickers"] == missing
    assert report["data_quality"]["missing_prices"] == price_area["missing"] == missing
    assert list(valued.foreign_currency_tickers) == plan["foreign_currency_tickers"] == foreign
    assert report["foreign_currency_tickers"] == price_area["foreign_currency_tickers"] == foreign
    assert price_area["expected"] == valued.expected_position_count == len(tickers) - (
        1 if "WATCH" in tickers else 0)
    assert price_area["covered"] == valued.priced_position_count == (1 if known else 0)
    excluded = 2 if name.startswith("mixed_realized") else 0
    realized_quality = "partial" if excluded else "complete"
    for data in [trust, plan, report["data_quality"]]:
        assert data["excluded_realized_trade_count"] == excluded
        assert data["realized_data_quality"] == realized_quality
    assert valued.realized_gain == report["period_activity"]["realized_gain"] == (
        2 if excluded else 0)
    if quality != "complete":
        assert report["current"]["total_value"] is None
        assert report["period_activity"]["value_change"] is None
        assert not plan["drift_available"]
        assert all(item["drift_bps"] is None for item in plan["items"])
    if excluded:
        caveat = report["period_activity"]["value_change_caveat"]
        assert "price coverage is incomplete" not in caveat
    if foreign:
        assert next(row for row in valued.holdings if row["ticker"] == "VOD.L")["currency"] == "GBp"
    _assert_bundle_receipts(bundle, quality=quality, known=known, excluded=excluded)
    valued_with_snapshot = valuation.evaluate(db, 1, quote_loader=load, record_snapshot=True)
    assert valued_with_snapshot.snapshot_recorded == (quality == "complete")
    assert db.query(PortfolioSnapshot).count() == (1 if quality == "complete" else 0)


def test_capture_time_is_not_quote_freshness_or_cache_age(db, monkeypatch):
    _seed(db, ["USD"])
    clock = [0]
    calls = []

    @ttl_cache(900, now=lambda: clock[0], key=tuple)
    def cached_quotes(tickers):
        calls.append(tickers)
        return _loader(["USD"])(tickers)

    captures = []
    for hour in [12, 13]:
        clock[0] = (hour - 12) * 300
        stamp = datetime(2026, 10, 30, hour, tzinfo=timezone.utc)
        monkeypatch.setattr(review, "_utc_now", lambda stamp=stamp: stamp)
        valued, trust, plan, report = _surfaces(db, cached_quotes)
        assert valued.total_value == 40
        # Current provider contract has no observed/fetched timestamp. No generation
        # time may be reinterpreted as either, even while an older cache value is reused.
        assert all("observed_at" not in row and "fetched_at" not in row for row in valued.holdings)
        assert trust["generated_at"] == report["generated_at"] == stamp.isoformat()
        rows = _csv(review.report_csv(report))
        assert ["coverage", "generated_at", stamp.isoformat()] in rows
        assert ["generated_at", stamp.isoformat()] in _csv(review.trust_center_csv(trust))
        assert ["generated_at", stamp.isoformat()] in _csv(
            review.target_plan_csv(plan, generated_at=stamp.isoformat()))
        assert stamp.isoformat() in review.report_html(report)
        captures.append(review.report_csv(report))
    assert len(calls) == 1
    assert captures[0] != captures[1]
    assert db.query(PortfolioSnapshot).count() == 0
