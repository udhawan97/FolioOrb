"""Average-cost realized-sale facts and their transaction-safe lifecycle.

These rows are local bookkeeping facts, not tax lots, broker reconciliation,
or tax advice. A holding reduction and its sale fact share the caller's one
SQLAlchemy transaction; corrections and removals commit together with today's
derived snapshot state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
from typing import Callable

from sqlalchemy.orm import Session

from app.models import Holding, RealizedTrade
from app.services import financial_currency, portfolio_valuation
from app.services.stock_service import get_stock_data

logger = logging.getLogger(__name__)

QuoteLoader = Callable[[str], dict]
ValuationQuoteLoader = Callable[[list[str]], list[dict]]

SALE_SOURCE_LEGACY_UNKNOWN = financial_currency.LEGACY_UNKNOWN_PROVENANCE
SALE_SOURCE_MANUAL_ENTRY = "manual_entry"
SALE_SOURCE_MARKET_QUOTE = "market_quote"
SALE_SOURCE_COST_BASIS_FALLBACK = "cost_basis_fallback"


@dataclass(frozen=True)
class SaleCorrection:
    """Caller-validated fields that may change on one realized sale."""

    shares_sold: float | None = None
    sale_price: float | None = None
    avg_cost: float | None = None
    sale_date: str | None = None


class RealizedSaleNotFound(LookupError):
    """The requested sale does not belong to the active portfolio."""


class RealizedSaleLedger:
    """Own average-cost sale arithmetic, ownership, and derived history sync."""

    def __init__(
        self,
        db: Session,
        portfolio_id: int,
        *,
        quote_loader: QuoteLoader | None = None,
        valuation_quote_loader: ValuationQuoteLoader | None = None,
    ):
        self.db = db
        self.portfolio_id = portfolio_id
        self.quote_loader = quote_loader or get_stock_data
        self.valuation_quote_loader = valuation_quote_loader

    @staticmethod
    def _noon(iso_date: str) -> datetime:
        parsed = date.fromisoformat(iso_date)
        return datetime(parsed.year, parsed.month, parsed.day, 12, 0)

    def _owned_trade(self, trade_id: int) -> RealizedTrade:
        trade = (
            self.db.query(RealizedTrade)
            .filter(
                RealizedTrade.id == trade_id,
                RealizedTrade.portfolio_id == self.portfolio_id,
            )
            .first()
        )
        if trade is None:
            raise RealizedSaleNotFound(trade_id)
        return trade

    def stage_reduction(
        self,
        holding: Holding,
        new_shares: float,
        *,
        sale_price: float | None = None,
        sale_date: str | None = None,
    ) -> RealizedTrade | None:
        """Add a sale fact to the holding mutation's current transaction."""
        if holding.portfolio_id != self.portfolio_id:
            raise RealizedSaleNotFound(holding.id)
        if holding.is_watchlist:
            return None
        sold = round(float(holding.shares) - float(new_shares), 6)
        if sold <= 0:
            return None

        basis = float(holding.avg_cost or 0.0)
        if sale_price is not None and sale_price > 0:
            price = float(sale_price)
            sale_currency = financial_currency.REPORTING_CURRENCY
            sale_price_source = SALE_SOURCE_MANUAL_ENTRY
        else:
            quote = self.quote_loader(str(holding.ticker))
            live = float(quote.get("current_price") or 0.0)
            if live > 0:
                price = live
                # Missing currency is ambiguous at the persistence boundary,
                # even though quote-only views historically display it as USD.
                sale_currency = financial_currency.normalize_currency(
                    quote.get("currency")
                )
                sale_price_source = SALE_SOURCE_MARKET_QUOTE
            else:
                # DR-003 owns removal of this legacy behavior. Mark it plainly
                # so it cannot enter dollar totals in the meantime.
                price = basis
                sale_currency = None
                sale_price_source = SALE_SOURCE_COST_BASIS_FALLBACK

        stored_price = round(price, 2)
        stored_basis = round(basis, 2)
        trade = RealizedTrade(
            portfolio_id=holding.portfolio_id,
            ticker=holding.ticker,
            shares_sold=sold,
            sale_price=stored_price,
            avg_cost=stored_basis,
            realized_gain=round((stored_price - stored_basis) * sold, 2),
            sale_currency=sale_currency,
            sale_price_source=sale_price_source,
        )
        if sale_date:
            trade.created_at = self._noon(sale_date)
        self.db.add(trade)
        return trade

    def _commit_with_today_snapshot(self) -> None:
        """Commit the ledger mutation and trustworthy derived state together."""
        # Production sessions disable autoflush. Make the staged correction or
        # deletion visible to valuation before deriving today's snapshot, while
        # keeping both changes inside the same transaction.
        self.db.flush()
        try:
            valuation = portfolio_valuation.evaluate(
                self.db,
                self.portfolio_id,
                quote_loader=self.valuation_quote_loader,
                record_snapshot=False,
            )
        except Exception:  # pylint: disable=broad-except
            if not self.db.is_active:
                raise
            logger.exception(
                "Could not value portfolio %s after realized-sale change; "
                "discarding today's derived snapshot",
                self.portfolio_id,
            )
            portfolio_valuation.discard_today_snapshot(self.db, self.portfolio_id)
        else:
            if valuation.data_quality == "complete":
                portfolio_valuation.stage_today_snapshot(self.db, valuation)
            else:
                portfolio_valuation.discard_today_snapshot(self.db, self.portfolio_id)
        self.db.commit()

    def correct(self, trade_id: int, changes: SaleCorrection) -> RealizedTrade:
        """Correct one owned sale and re-derive gain plus today's snapshot."""
        trade = self._owned_trade(trade_id)
        if changes.shares_sold is not None:
            trade.shares_sold = changes.shares_sold
        if changes.sale_price is not None:
            trade.sale_price = round(changes.sale_price, 2)
            # The existing field is explicitly dollar-labelled at the API/UI
            # boundary, so this correction creates new, user-supplied USD
            # provenance rather than guessing the meaning of a legacy value.
            trade.sale_currency = financial_currency.REPORTING_CURRENCY
            trade.sale_price_source = SALE_SOURCE_MANUAL_ENTRY
        if changes.avg_cost is not None:
            trade.avg_cost = round(changes.avg_cost, 2)
        if changes.sale_date is not None:
            trade.created_at = self._noon(changes.sale_date)
        trade.realized_gain = round(
            (float(trade.sale_price) - float(trade.avg_cost))
            * float(trade.shares_sold),
            2,
        )
        self._commit_with_today_snapshot()
        return trade

    def remove(self, trade_id: int) -> str:
        """Remove one owned sale and commit today's consistent derived state."""
        trade = self._owned_trade(trade_id)
        ticker = str(trade.ticker)
        self.db.delete(trade)
        self._commit_with_today_snapshot()
        return ticker
