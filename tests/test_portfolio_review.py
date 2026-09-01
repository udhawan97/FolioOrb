"""Financial and workflow contracts for the local Review Orbit."""
# pylint: disable=redefined-outer-name
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Base,
    DcaContribution,
    DcaPlan,
    Holding,
    Portfolio,
    PortfolioSnapshot,
    RealizedTrade,
)
from app.services import portfolio_review, portfolio_valuation


@pytest.fixture
def db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)  # pylint: disable=invalid-name
    session = Session()
    session.add(Portfolio(id=1, name="Review book"))
    session.add_all([
        Holding(
            id=1, portfolio_id=1, ticker="AAPL", shares=10, avg_cost=100,
            is_active=True, is_watchlist=False, notes="Durable cash flows",
            thesis_reviewed_at=datetime.now() - timedelta(days=100),
            thesis_review_interval_days=90,
        ),
        Holding(
            id=2, portfolio_id=1, ticker="MSFT", shares=0, avg_cost=0,
            is_active=True, is_watchlist=True, notes=None,
        ),
        Holding(
            id=3, portfolio_id=1, ticker="NVDA", shares=0, avg_cost=0,
            is_active=True, is_watchlist=True, notes="AI infrastructure",
            thesis_reviewed_at=datetime.now(),
            thesis_review_interval_days=90,
        ),
    ])
    session.commit()

    def fast_quotes(tickers):
        return [
            {
                "ticker": ticker,
                "name": ticker,
                "current_price": 150.0 if ticker == "AAPL" else 100.0,
                "day_change": 1.0,
                "day_change_pct": 0.5,
            }
            for ticker in tickers
        ]

    monkeypatch.setattr(portfolio_valuation, "get_portfolio_quotes", fast_quotes)
    yield session
    session.close()


def _full_quotes(tickers):
    return [
        {
            "ticker": ticker,
            "name": ticker,
            "current_price": 150.0,
            "day_change_pct": 1.0,
            "quote_type": "EQUITY",
            "security_type": "STOCK",
            "sector": "Technology",
            "market_cap": 100_000_000,
            "pe_ratio": 20.0,
        }
        for ticker in tickers
    ]


def test_thesis_cadence_distinguishes_missing_and_overdue(db):
    apple = db.get(Holding, 1)
    microsoft = db.get(Holding, 2)

    assert portfolio_review.thesis_state(apple)["status"] == "overdue"
    assert portfolio_review.thesis_state(microsoft)["status"] == "missing"


def test_trust_center_reports_real_coverage_and_provenance(db):
    trust = portfolio_review.build_trust_center(db, 1, quote_loader=_full_quotes)
    areas = {area["key"]: area for area in trust["areas"]}

    assert areas["prices"]["quality"] == "complete"
    assert areas["prices"]["covered"] == 1  # research rows do not count in P&L coverage
    assert areas["fundamentals"]["covered"] == 3
    assert areas["theses"]["missing"] == ["MSFT"]
    assert trust["principle"].startswith("Missing data")


def test_data_health_csv_keeps_missing_coverage_and_provenance_visible():
    content = portfolio_review.trust_center_csv({
        "generated_at": "2026-08-25T12:00:00+00:00",
        "portfolio_id": 7,
        "overall_quality": "partial",
        "reporting_currency": "USD",
        "foreign_currency_tickers": ["VOD.L"],
        "latest_snapshot": "2026-08-24",
        "snapshot_count": 12,
        "principle": "Missing data stays missing.",
        "areas": [{
            "key": "prices",
            "label": "Position prices",
            "quality": "partial",
            "covered": 1,
            "expected": 2,
            "missing": ["MSFT"],
            "foreign_currency_tickers": ["VOD.L"],
            "source": "Provider cache",
            "caveat": "Foreign-priced positions are excluded from USD totals.",
        }],
    })

    assert content.startswith("\ufeffFolioOrb data health receipt")
    assert "overall_quality,partial" in content
    assert "foreign_currency_tickers,VOD.L" in content
    assert "Position prices,partial,1,2,MSFT,VOD.L,Provider cache" in content
    assert "Foreign-priced positions are excluded from USD totals." in content


def test_target_plan_csv_preserves_partial_valuation_instead_of_inventing_drift():
    content = portfolio_review.target_plan_csv({
        "portfolio_id": 3,
        "reporting_currency": "USD",
        "known_value": 1000.0,
        "valuation_quality": "partial",
        "complete": True,
        "drift_available": False,
        "missing_tickers": ["MSFT"],
        "foreign_currency_tickers": ["VOD.L"],
        "items": [{
            "ticker": "AAPL",
            "target_weight_bps": 6000,
            "actual_weight_bps": None,
            "drift_bps": None,
            "drift_direction": None,
        }],
    }, generated_at="2026-08-25T12:00:00+00:00")

    assert content.startswith("\ufeffFolioOrb target plan snapshot")
    assert "valuation_quality,partial" in content
    assert "drift_available,False" in content
    assert "missing_tickers,MSFT" in content
    assert "foreign_currency_tickers,VOD.L" in content
    assert "AAPL,6000,60.0,,,," in content


def test_review_receipt_csv_neutralizes_spreadsheet_formula_cells():
    trust = portfolio_review.trust_center_csv({
        "generated_at": "2026-08-25T12:00:00+00:00",
        "portfolio_id": 1,
        "overall_quality": "partial",
        "reporting_currency": "USD",
        "foreign_currency_tickers": ["-FOREIGN"],
        "areas": [{
            "label": "-DANGER",
            "quality": "partial",
            "covered": 0,
            "expected": 1,
            "missing": ["=MISSING"],
            "foreign_currency_tickers": ["-FOREIGN"],
            "source": "+SOURCE",
            "caveat": "@CAVEAT",
        }],
    })
    plan = portfolio_review.target_plan_csv({
        "portfolio_id": 1,
        "reporting_currency": "USD",
        "missing_tickers": ["=MISSING"],
        "foreign_currency_tickers": ["-FOREIGN"],
        "items": [{"ticker": "-DANGER", "target_weight_bps": 10000}],
    })

    for dangerous in ("'-DANGER", "'=MISSING", "'-FOREIGN", "'+SOURCE", "'@CAVEAT"):
        assert dangerous in trust
    for dangerous in ("'-DANGER", "'=MISSING", "'-FOREIGN"):
        assert dangerous in plan


def test_trust_center_names_foreign_exclusions_for_mixed_and_foreign_only_books(
    db, monkeypatch
):
    db.add(Holding(
        id=4, portfolio_id=1, ticker="VOD.L", shares=10, avg_cost=80,
        is_active=True, is_watchlist=False,
    ))
    db.add(Portfolio(id=2, name="Foreign-only book"))
    db.add(Holding(
        id=5, portfolio_id=2, ticker="VOD.L", shares=10, avg_cost=80,
        is_active=True, is_watchlist=False,
    ))
    db.commit()

    def currency_quotes(tickers):
        return [
            {
                "ticker": ticker,
                "name": ticker,
                "current_price": 100.0,
                "day_change": 1.0,
                "day_change_pct": 0.5,
                "currency": "GBp" if ticker == "VOD.L" else "USD",
                "quote_type": "EQUITY",
                "security_type": "STOCK",
                "sector": "Technology",
            }
            for ticker in tickers
        ]

    monkeypatch.setattr(portfolio_valuation, "get_portfolio_quotes", currency_quotes)
    mixed = portfolio_review.build_trust_center(db, 1, quote_loader=currency_quotes)
    foreign_only = portfolio_review.build_trust_center(db, 2, quote_loader=currency_quotes)
    mixed_prices = {area["key"]: area for area in mixed["areas"]}["prices"]
    foreign_prices = {area["key"]: area for area in foreign_only["areas"]}["prices"]

    assert mixed["foreign_currency_tickers"] == ["VOD.L"]
    assert mixed_prices["foreign_currency_tickers"] == ["VOD.L"]
    assert mixed_prices["quality"] == "partial"
    assert foreign_only["foreign_currency_tickers"] == ["VOD.L"]
    assert foreign_prices["foreign_currency_tickers"] == ["VOD.L"]
    assert foreign_prices["quality"] == "unavailable"
    assert "excluded from USD totals" in foreign_prices["caveat"]


def test_trust_center_keeps_active_rows_missing_from_the_valuation(db, monkeypatch):
    def fast_quotes_without_microsoft(tickers):
        return [
            {
                "ticker": ticker,
                "current_price": 150.0,
                "day_change": 1.0,
                "day_change_pct": 0.5,
            }
            for ticker in tickers
            if ticker != "MSFT"
        ]

    monkeypatch.setattr(
        portfolio_valuation, "get_portfolio_quotes", fast_quotes_without_microsoft
    )
    trust = portfolio_review.build_trust_center(
        db, 1, quote_loader=lambda tickers: [
            row for row in _full_quotes(tickers) if row["ticker"] != "MSFT"
        ]
    )
    areas = {area["key"]: area for area in trust["areas"]}

    assert areas["fundamentals"]["expected"] == 3
    assert areas["fundamentals"]["covered"] == 2
    assert areas["fundamentals"]["missing"] == ["MSFT"]


def test_inbox_prioritises_pending_dca_and_thesis_reviews(db):
    plan = DcaPlan(
        id=1, portfolio_id=1, ticker="AAPL", amount=50, frequency="monthly",
        start_date=date.today().isoformat(), is_active=True,
    )
    db.add(plan)
    db.add(DcaContribution(
        plan_id=1, scheduled_date=date.today().isoformat(),
        exec_date=date.today().isoformat(), price=100, shares=0.5,
        amount=50, status="pending",
    ))
    db.commit()

    inbox = portfolio_review.build_review_inbox(
        db, 1, earnings_loader=lambda _tickers, _window: []
    )
    ids = {item["id"] for item in inbox["items"]}

    assert "dca-pending" in ids
    assert "thesis-1" in ids
    assert "thesis-2" in ids
    assert inbox["counts"]["attention"] >= 3


def test_report_labels_value_change_as_cash_flow_affected(db):
    today = date.today()
    db.add_all([
        PortfolioSnapshot(
            portfolio_id=1,
            snapshot_date=(today - timedelta(days=20)).isoformat(),
            total_value=1000,
            total_cost_basis=900,
            unrealized_gain=100,
            realized_gain=0,
            total_return=100,
        ),
        PortfolioSnapshot(
            portfolio_id=1,
            snapshot_date=today.isoformat(),
            total_value=1500,
            total_cost_basis=1000,
            unrealized_gain=500,
            realized_gain=0,
            total_return=500,
        ),
        RealizedTrade(
            portfolio_id=1, ticker="AAPL", shares_sold=1, sale_price=140,
            avg_cost=100, realized_gain=40, created_at=datetime.now(),
            sale_currency="USD", sale_price_source="market_quote",
        ),
    ])
    db.commit()

    report = portfolio_review.build_review_report(db, 1, "month")

    assert report["period_activity"]["value_change"] == 500
    assert report["observed_start"] == (today - timedelta(days=20)).isoformat()
    assert report["data_quality"]["history"] == "partial"
    assert report["observed_start"] in report["period_activity"]["value_change_caveat"]
    assert "contributions and withdrawals" in report["period_activity"]["value_change_caveat"]
    assert report["period_activity"]["realized_gain"] == 40
    assert "time-weighted" in portfolio_review.report_html(report)
    assert portfolio_review.report_csv(report).startswith("\ufeffsection,metric,value")


def test_review_pack_csv_neutralizes_spreadsheet_formula_cells():
    content = portfolio_review.report_csv({
        "current": {"=METRIC": "+VALUE"},
        "period_activity": {"@ACTIVITY": "-VALUE"},
        "data_quality": {"valuation": "=PARTIAL", "history": "+HISTORY"},
        "observed_start": "-2026-08-25",
        "movers": [{"ticker": "-DANGER", "total_return_pct": "=1+1"}],
        "thesis_attention": [{"ticker": "+THESIS", "status": "@OVERDUE"}],
    })

    for dangerous in (
        "'=METRIC", "'+VALUE", "'@ACTIVITY", "'-VALUE", "'=PARTIAL",
        "'+HISTORY", "'-2026-08-25", "'-DANGER", "'=1+1", "'+THESIS",
        "'@OVERDUE",
    ):
        assert dangerous in content


def test_report_uses_the_nearest_snapshot_before_the_period_boundary(db):
    today = date.today()
    db.add_all([
        PortfolioSnapshot(
            portfolio_id=1,
            snapshot_date=(today - timedelta(days=32)).isoformat(),
            total_value=900,
            total_cost_basis=800,
            unrealized_gain=100,
            realized_gain=0,
            total_return=100,
        ),
        PortfolioSnapshot(
            portfolio_id=1,
            snapshot_date=(today - timedelta(days=10)).isoformat(),
            total_value=1200,
            total_cost_basis=900,
            unrealized_gain=300,
            realized_gain=0,
            total_return=300,
        ),
    ])
    db.commit()

    report = portfolio_review.build_review_report(db, 1, "month")

    assert report["observed_start"] == (today - timedelta(days=32)).isoformat()
    assert report["history_start_gap_days"] == 1
    assert report["data_quality"]["history"] == "complete"
    assert report["period_activity"]["value_change"] == 600


def test_watchlist_compare_rejects_owned_positions_and_mixed_types(db):
    with pytest.raises(ValueError, match="research-mode"):
        portfolio_review.compare_watchlist(
            db, 1, ["AAPL", "MSFT"], quote_loader=lambda ticker: {
                "ticker": ticker, "quote_type": "EQUITY", "current_price": 100,
            }
        )

    def mixed(ticker):
        return {
            "ticker": ticker,
            "quote_type": "ETF" if ticker == "NVDA" else "EQUITY",
            "current_price": 100,
        }

    with pytest.raises(ValueError, match="stocks with stocks"):
        portfolio_review.compare_watchlist(db, 1, ["MSFT", "NVDA"], quote_loader=mixed)


def test_watchlist_compare_returns_type_relevant_stock_metrics(db):
    def quotes(ticker):
        return {
            "ticker": ticker,
            "name": ticker,
            "quote_type": "EQUITY",
            "security_type": "STOCK",
            "current_price": 100,
            "day_change_pct": 1,
            "market_cap": 1_000_000,
            "pe_ratio": 22,
            "revenue_growth": 0.12,
        }

    result = portfolio_review.compare_watchlist(
        db, 1, ["MSFT", "NVDA"], quote_loader=quotes
    )

    assert result["security_type"] == "STOCK"
    assert result["items"][0]["metrics"]["pe_ratio"] == 22
    assert "expense_ratio" not in result["items"][0]["metrics"]
