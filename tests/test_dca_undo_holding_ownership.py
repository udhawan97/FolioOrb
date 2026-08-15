"""Undoing a DCA buy may only touch a holding in the plan's own portfolio.

``DcaLedger._apply`` resolves the holding it books through
``holdings_repository.active_by_ticker(db, plan.portfolio_id, ...)``, so the
plan's portfolio scopes the write. ``_reverse`` did not match: it looked the
holding up by primary key alone::

    self.db.query(Holding).filter(Holding.id == contribution.applied_holding_id)

That is the id-only lookup ``holdings_repository.in_portfolio`` was extracted to
end — its docstring names the failure mode directly ("let a request scoped to
one portfolio edit another portfolio's row"). ``applied_holding_id`` is a plain
integer column with no foreign key and no portfolio of its own, so whenever it
points outside the plan's portfolio the undo silently rewrote a stranger's
shares and could deactivate it.

The buy is still returned to pending either way — an undo must never strand a
contribution in ``applied`` because its holding could not be found.
"""

from app.models import DcaContribution, DcaPlan, Holding, Portfolio
from app.services.dca_ledger import DcaLedger


def _seed_cross_portfolio_contribution(db):
    """An applied buy in portfolio 1 whose applied_holding_id points at portfolio 2."""
    db.add(Portfolio(id=2, name="Someone else's portfolio"))
    db.flush()

    stranger = Holding(
        portfolio_id=2, ticker="AAPL", shares=50.0, avg_cost=100.0, is_watchlist=False
    )
    db.add(stranger)

    plan = DcaPlan(
        portfolio_id=1,
        ticker="AAPL",
        amount=100.0,
        frequency="monthly",
        start_date="2026-01-01",
    )
    db.add(plan)
    db.flush()

    contribution = DcaContribution(
        plan_id=plan.id,
        scheduled_date="2026-01-01",
        exec_date="2026-01-02",
        price=50.0,
        shares=2.0,
        amount=100.0,
        status="applied",
        applied_holding_id=stranger.id,
    )
    db.add(contribution)
    db.commit()
    return contribution, stranger


def test_undo_does_not_touch_a_holding_in_another_portfolio(db):
    contribution, stranger = _seed_cross_portfolio_contribution(db)
    before_shares, before_cost = stranger.shares, stranger.avg_cost

    DcaLedger(db).undo_contribution(contribution.id)

    db.refresh(stranger)
    assert stranger.shares == before_shares, (
        "undo rewrote the share count of a holding owned by another portfolio"
    )
    assert stranger.avg_cost == before_cost
    assert stranger.is_active is True


def test_undo_still_returns_the_buy_to_pending(db):
    contribution, _stranger = _seed_cross_portfolio_contribution(db)

    result = DcaLedger(db).undo_contribution(contribution.id)

    db.refresh(contribution)
    assert contribution.status == "pending"
    assert contribution.applied_holding_id is None
    # The caller is told the holding could not be reversed rather than being
    # given a silent success. The wording must not claim the holding no longer
    # exists — in this case it exists and was deliberately left alone.
    assert "No matching holding in this portfolio" in result["message"]


def test_undo_still_reverses_a_holding_in_the_plans_own_portfolio(db):
    """The ownership check must not break the normal, same-portfolio undo."""
    own = Holding(
        portfolio_id=1, ticker="AAPL", shares=12.0, avg_cost=100.0, is_watchlist=False
    )
    db.add(own)
    plan = DcaPlan(
        portfolio_id=1,
        ticker="AAPL",
        amount=100.0,
        frequency="monthly",
        start_date="2026-01-01",
    )
    db.add(plan)
    db.flush()
    contribution = DcaContribution(
        plan_id=plan.id,
        scheduled_date="2026-01-01",
        exec_date="2026-01-02",
        price=50.0,
        shares=2.0,
        amount=100.0,
        status="applied",
        applied_holding_id=own.id,
    )
    db.add(contribution)
    db.commit()

    DcaLedger(db).undo_contribution(contribution.id)

    db.refresh(own)
    assert own.shares == 10.0  # 12 - 2, the buy reversed exactly
