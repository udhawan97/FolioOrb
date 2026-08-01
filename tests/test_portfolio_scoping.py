"""Holdings and trades may only be mutated through the portfolio that owns them.

The regression this pins: `PUT`/`DELETE /api/portfolio/holdings/{id}` and
`DELETE /api/portfolio/trades/{id}` used to look their row up by primary key
alone. The frontend scopes every /api/portfolio/ request with `portfolio_id`,
but the handlers ignored it, so a request scoped to one portfolio could edit or
soft-delete another portfolio's holding — silently, and with the wrong
portfolio's realized-trade ledger picking up the sale.
"""
# pylint: disable=redefined-outer-name
import pytest

from app.models import Holding, Portfolio, RealizedTrade
from app.routers import portfolio as portfolio_router
from app.services import holdings_repository


@pytest.fixture
def two_books(db):
    """Portfolio 1 holds AAA, portfolio 2 holds BBB. Same schema, different owners."""
    db.add(Portfolio(id=2, name="Second"))
    db.add(Holding(portfolio_id=1, ticker="AAA", shares=10, avg_cost=100,
                   is_active=True, is_watchlist=False))
    db.add(Holding(portfolio_id=2, ticker="BBB", shares=20, avg_cost=200,
                   is_active=True, is_watchlist=False))
    db.commit()
    return db


def _holding(db, ticker):
    return db.query(Holding).filter(Holding.ticker == ticker).one()


class TestRepositoryLookup:
    def test_finds_a_holding_through_its_own_portfolio(self, two_books):
        target = _holding(two_books, "BBB")
        found = holdings_repository.in_portfolio(two_books, 2, target.id)
        assert found is not None and found.ticker == "BBB"

    def test_refuses_to_find_it_through_another_portfolio(self, two_books):
        target = _holding(two_books, "BBB")
        assert holdings_repository.in_portfolio(two_books, 1, target.id) is None

    def test_finds_a_soft_deleted_row_by_default(self, two_books):
        target = _holding(two_books, "AAA")
        target.is_active = False
        two_books.commit()
        # The edit endpoint can re-activate, so it must still be findable.
        assert holdings_repository.in_portfolio(two_books, 1, target.id) is not None

    def test_active_only_hides_a_soft_deleted_row(self, two_books):
        target = _holding(two_books, "AAA")
        target.is_active = False
        two_books.commit()
        assert holdings_repository.in_portfolio(
            two_books, 1, target.id, active_only=True
        ) is None


class TestUpdateHolding:
    def test_updates_through_the_owning_portfolio(self, two_books):
        target = _holding(two_books, "BBB")

        portfolio_router.update_holding(
            target.id,
            portfolio_router.HoldingUpdate(hold_class="anchor"),
            two_books,
            portfolio_id=2,
        )

        two_books.refresh(target)
        assert target.hold_class == "anchor"

    def test_a_foreign_portfolio_gets_a_404_and_changes_nothing(self, two_books):
        target = _holding(two_books, "BBB")

        with pytest.raises(portfolio_router.HTTPException) as caught:
            portfolio_router.update_holding(
                target.id,
                portfolio_router.HoldingUpdate(hold_class="anchor"),
                two_books,
                portfolio_id=1,
            )

        assert caught.value.status_code == 404
        two_books.refresh(target)
        assert target.hold_class != "anchor"


class TestRemoveHolding:
    def test_a_foreign_portfolio_cannot_soft_delete(self, two_books):
        target = _holding(two_books, "BBB")

        with pytest.raises(portfolio_router.HTTPException) as caught:
            portfolio_router.remove_holding(target.id, two_books, portfolio_id=1)

        assert caught.value.status_code == 404
        two_books.refresh(target)
        assert target.is_active is True

    def test_the_owning_portfolio_can(self, two_books):
        target = _holding(two_books, "BBB")

        portfolio_router.remove_holding(target.id, two_books, portfolio_id=2)

        two_books.refresh(target)
        assert target.is_active is False


class TestRemoveRealizedTrade:
    def test_a_foreign_portfolio_cannot_delete_a_trade(self, two_books):
        trade = RealizedTrade(
            portfolio_id=2, ticker="BBB", shares_sold=1,
            sale_price=250, avg_cost=200, realized_gain=50,
        )
        two_books.add(trade)
        two_books.commit()

        with pytest.raises(portfolio_router.HTTPException) as caught:
            portfolio_router.remove_realized_trade(trade.id, two_books, portfolio_id=1)

        assert caught.value.status_code == 404
        assert two_books.query(RealizedTrade).count() == 1
