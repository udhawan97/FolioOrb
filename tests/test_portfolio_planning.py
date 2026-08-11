"""Target, rehearsal, and all-books contracts stay scoped and read-only."""
from decimal import Decimal

import pytest

from app.models import Holding, Portfolio, PortfolioSnapshot
from app.services import portfolio_planning


def _quotes(prices, currencies=None):
    currencies = currencies or {}

    def load(tickers):
        return [
            {
                "ticker": ticker,
                "name": ticker,
                "current_price": prices.get(ticker, 0),
                "currency": currencies.get(ticker, "USD"),
            }
            for ticker in tickers
        ]

    return load


def _seed_positions(db):
    db.add_all([
        Holding(
            id=1, portfolio_id=1, ticker="AAPL", shares=10,
            avg_cost=100, is_active=True, is_watchlist=False,
        ),
        Holding(
            id=2, portfolio_id=1, ticker="MSFT", shares=5,
            avg_cost=200, is_active=True, is_watchlist=False,
        ),
        Holding(
            id=3, portfolio_id=1, ticker="WATCH", shares=0,
            avg_cost=0, is_active=True, is_watchlist=True,
        ),
    ])
    db.commit()


def test_targets_are_atomic_portfolio_scoped_and_never_normalized(db):
    _seed_positions(db)

    snapshot = portfolio_planning.replace_targets(
        db, 1, [(1, 6000), (2, 3500)]
    )
    assert snapshot["complete"] is False
    assert snapshot["target_total_bps"] == 9500
    assert snapshot["remaining_bps"] == 500

    with pytest.raises(ValueError, match="only once"):
        portfolio_planning.replace_targets(db, 1, [(1, 5000), (1, 5000)])
    with pytest.raises(ValueError, match="every eligible"):
        portfolio_planning.replace_targets(db, 1, [(1, 10_000)])
    with pytest.raises(ValueError, match="more than"):
        portfolio_planning.replace_targets(db, 1, [(1, 8000), (2, 3000)])

    stored = {row.id: row.target_weight_bps for row in db.query(Holding).all()}
    assert stored == {1: 6000, 2: 3500, 3: None}


def test_targets_reject_foreign_ineligible_boolean_and_out_of_range_ids(db):
    _seed_positions(db)
    db.add_all([
        Portfolio(id=2, name="Other book"),
        Holding(
            id=4, portfolio_id=2, ticker="OTHER", shares=1,
            avg_cost=1, is_active=True, is_watchlist=False,
        ),
        Holding(
            id=5, portfolio_id=1, ticker="INACTIVE", shares=1,
            avg_cost=1, is_active=False, is_watchlist=False,
        ),
    ])
    db.commit()

    for assignments in (
        [(1, 5000), (4, 5000)],
        [(1, 5000), (3, 5000)],
        [(1, 5000), (5, 5000)],
    ):
        with pytest.raises(ValueError, match="every eligible"):
            portfolio_planning.replace_targets(db, 1, assignments)
    with pytest.raises(ValueError, match="whole basis points"):
        portfolio_planning.replace_targets(db, 1, [(1, True), (2, 9999)])
    with pytest.raises(ValueError, match="whole basis points"):
        portfolio_planning.replace_targets(db, 1, [(1, 10_001), (2, None)])


def test_corrupt_persisted_targets_are_incomplete_instead_of_crashing(db):
    _seed_positions(db)
    db.get(Holding, 1).target_weight_bps = 12_000
    db.get(Holding, 2).target_weight_bps = -1
    db.commit()

    snapshot = portfolio_planning.target_snapshot(db, 1)

    assert snapshot["complete"] is False
    assert snapshot["assigned_count"] == 0
    assert [item["target_weight_bps"] for item in snapshot["items"]] == [None, None]


def test_share_change_recomputes_drift_but_new_eligibility_breaks_completeness(db):
    _seed_positions(db)
    portfolio_planning.replace_targets(db, 1, [(1, 5000), (2, 5000)])
    loader = _quotes({"AAPL": 100, "MSFT": 200})

    before = portfolio_planning.build_target_plan(db, 1, quote_loader=loader)
    assert before["complete"] is True
    assert before["drift_available"] is True
    assert [item["drift_bps"] for item in before["items"]] == [0, 0]

    db.query(Holding).filter(Holding.id == 1).one().shares = 20
    db.commit()
    changed = portfolio_planning.build_target_plan(db, 1, quote_loader=loader)
    assert changed["complete"] is True
    assert [item["actual_weight_bps"] for item in changed["items"]] == [6667, 3333]

    db.add(Holding(
        portfolio_id=1, ticker="GOOG", shares=1, avg_cost=100,
        is_active=True, is_watchlist=False,
    ))
    db.commit()
    incomplete = portfolio_planning.build_target_plan(
        db, 1, quote_loader=_quotes({"AAPL": 100, "MSFT": 200, "GOOG": 100})
    )
    assert incomplete["complete"] is False
    assert incomplete["drift_available"] is False


def test_complete_targets_hide_drift_for_missing_or_foreign_quotes(db):
    _seed_positions(db)
    portfolio_planning.replace_targets(db, 1, [(1, 5000), (2, 5000)])

    missing = portfolio_planning.build_target_plan(
        db, 1, quote_loader=_quotes({"AAPL": 100})
    )
    foreign = portfolio_planning.build_target_plan(
        db,
        1,
        quote_loader=_quotes({"AAPL": 100, "MSFT": 200}, {"MSFT": "GBP"}),
    )

    assert missing["drift_available"] is False
    assert missing["missing_tickers"] == ["MSFT"]
    assert foreign["drift_available"] is False
    assert foreign["foreign_currency_tickers"] == ["MSFT"]
    assert all(item["drift_bps"] is None for item in missing["items"])
    assert all(item["drift_bps"] is None for item in foreign["items"])


def test_buy_rehearsal_reuses_average_cost_math_without_writes(db):
    _seed_positions(db)
    before = {
        row.id: (row.shares, row.avg_cost, row.target_weight_bps)
        for row in db.query(Holding).all()
    }

    result = portfolio_planning.rehearse_buy(
        db,
        1,
        1,
        Decimal("500.00"),
        quote_loader=_quotes({"AAPL": 125, "MSFT": 200}),
    )

    assert result["available_quote_usd"] == 125
    assert result["buy_shares"] == 4
    assert result["projected_shares"] == 14
    assert result["projected_avg_cost_usd"] == pytest.approx(107.1429)
    assert result["projected_known_value_usd"] == 2750
    assert result["allocation_available"] is True
    assert db.query(PortfolioSnapshot).count() == 0
    assert {
        row.id: (row.shares, row.avg_cost, row.target_weight_bps)
        for row in db.query(Holding).all()
    } == before


def test_rehearsal_keeps_basis_math_but_hides_allocation_on_partial_book(db):
    _seed_positions(db)
    result = portfolio_planning.rehearse_buy(
        db, 1, 1, Decimal("25.00"), quote_loader=_quotes({"AAPL": 100})
    )
    assert result["projected_shares"] == 10.25
    assert result["allocation_available"] is False
    assert result["projected_selected_allocation_pct"] is None
    assert result["missing_tickers"] == ["MSFT"]

    with pytest.raises(ValueError, match="available USD quote"):
        portfolio_planning.rehearse_buy(
            db, 1, 1, Decimal("25.00"),
            quote_loader=_quotes({"AAPL": 100}, {"AAPL": "GBP"}),
        )
    with pytest.raises(ValueError, match="two decimal"):
        portfolio_planning.rehearse_buy(
            db, 1, 1, Decimal("1.001"), quote_loader=_quotes({"AAPL": 100})
        )


def test_rehearsal_rejects_nonfinite_and_out_of_scope_inputs_at_exact_ceiling(db):
    _seed_positions(db)
    for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(ValueError, match="positive finite"):
            portfolio_planning.rehearse_buy(
                db, 1, 1, value, quote_loader=_quotes({"AAPL": 100, "MSFT": 200})
            )
    with pytest.raises(ValueError, match="limit"):
        portfolio_planning.rehearse_buy(
            db,
            1,
            1,
            Decimal("100000000.01"),
            quote_loader=_quotes({"AAPL": 100, "MSFT": 200}),
        )
    with pytest.raises(ValueError, match="active held position"):
        portfolio_planning.rehearse_buy(
            db, 1, 3, Decimal("1"), quote_loader=_quotes({"WATCH": 1})
        )

    exact = portfolio_planning.rehearse_buy(
        db,
        1,
        1,
        Decimal("100000000.00"),
        quote_loader=_quotes({"AAPL": 100, "MSFT": 200}),
    )
    assert exact["cash_usd"] == 100_000_000


def test_all_books_sums_only_displayed_known_usd_and_isolates_failures(db):
    _seed_positions(db)
    db.add_all([
        Portfolio(id=2, name="Empty"),
        Portfolio(id=3, name="Broken quotes"),
        Holding(
            portfolio_id=3, ticker="FAIL", shares=1, avg_cost=1,
            is_active=True, is_watchlist=False,
        ),
    ])
    db.commit()

    def loader(tickers):
        if "FAIL" in tickers:
            raise RuntimeError("provider down")
        return _quotes({"AAPL": 100, "MSFT": 200})(tickers)

    result = portfolio_planning.build_all_books_overview(db, quote_loader=loader)
    by_name = {item["name"]: item for item in result["items"]}
    assert by_name["Test Portfolio"]["known_value_usd"] == 2000
    assert by_name["Empty"]["data_quality"] == "empty"
    assert by_name["Broken quotes"]["known_value_usd"] is None
    assert by_name["Broken quotes"]["error"] == "RuntimeError"
    assert result["known_value_usd"] == sum(
        item["known_value_usd"] or 0 for item in result["items"]
    )
    assert result["data_quality"] == "partial"
    assert db.query(PortfolioSnapshot).count() == 0
