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
import math
from typing import Callable

from sqlalchemy.orm import Session

from app.models import Holding, RealizedTrade
from app.services import (
    financial_currency,
    holdings_repository,
    portfolio_valuation,
    write_serialization,
)
from app.services.stock_service import get_stock_data

logger = logging.getLogger(__name__)

QuoteLoader = Callable[[str], dict]
ValuationQuoteLoader = Callable[[list[str]], list[dict]]

SALE_SOURCE_LEGACY_UNKNOWN = financial_currency.LEGACY_UNKNOWN_PROVENANCE
SALE_SOURCE_MANUAL_ENTRY = "manual_entry"
SALE_SOURCE_MARKET_QUOTE = "market_quote"


@dataclass(frozen=True)
class SaleCorrection:
    """Caller-validated fields that may change on one realized sale."""

    shares_sold: float | None = None
    sale_price: float | None = None
    avg_cost: float | None = None
    sale_date: str | None = None


class RealizedSaleNotFound(LookupError):
    """The requested sale does not belong to the active portfolio."""


class SalePriceUnavailable(ValueError):
    """A reduction cannot be priced as a trustworthy USD sale."""

    def __init__(self, ticker: str):
        super().__init__(ticker)
        self.ticker = ticker


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
        if sale_price is not None:
            try:
                price = float(sale_price)
            except (TypeError, ValueError, OverflowError):
                raise SalePriceUnavailable(str(holding.ticker)) from None
            if not math.isfinite(price) or price <= 0:
                raise SalePriceUnavailable(str(holding.ticker))
            sale_currency = financial_currency.REPORTING_CURRENCY
            sale_price_source = SALE_SOURCE_MANUAL_ENTRY
        else:
            try:
                quote = self.quote_loader(str(holding.ticker)) or {}
                live = float(quote.get("current_price") or 0.0)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Sale quote unavailable; ticker=%s exception_type=%s",
                    holding.ticker,
                    type(exc).__name__,
                )
                raise SalePriceUnavailable(str(holding.ticker)) from None
            if not (
                math.isfinite(live)
                and live > 0
                # ``currency`` may be the quote adapter's USD display fallback.
                # Persist a market sale only when the provider itself supplied
                # matching USD provenance.
                and financial_currency.is_reporting_currency(quote.get("currency"))
                and financial_currency.is_reporting_currency(
                    quote.get("source_currency")
                )
            ):
                raise SalePriceUnavailable(str(holding.ticker))
            price = live
            sale_currency = financial_currency.REPORTING_CURRENCY
            sale_price_source = SALE_SOURCE_MARKET_QUOTE

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

    @staticmethod
    def _holding_fingerprint(holdings: list[Holding]) -> tuple:
        """Valuation inputs that must still match prefetched market quotes."""
        return tuple(
            sorted(
                (
                    holding.id,
                    str(holding.ticker),
                    float(holding.shares or 0.0),
                    float(holding.avg_cost or 0.0),
                    bool(holding.is_watchlist),
                    bool(holding.is_active),
                )
                for holding in holdings
            )
        )

    def _prefetch_valuation(self) -> tuple[tuple, list[dict] | None]:
        """Load market quotes before reserving SQLite's sole writer."""
        holdings = holdings_repository.active(self.db, self.portfolio_id)
        fingerprint = self._holding_fingerprint(holdings)
        tickers = [str(holding.ticker) for holding in holdings]
        self.db.rollback()
        try:
            loader = (
                self.valuation_quote_loader
                or portfolio_valuation.get_portfolio_quotes
            )
            return fingerprint, loader(tickers)
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "Could not prefetch valuation after realized-sale change for %s",
                self.portfolio_id,
            )
            return fingerprint, None

    def _commit_with_today_snapshot(
        self,
        expected_holdings: tuple,
        prefetched_quotes: list[dict] | None,
    ) -> None:
        """Commit the ledger mutation and trustworthy derived state together."""
        # Production sessions disable autoflush. Make the staged correction or
        # deletion visible to valuation before deriving today's snapshot, while
        # keeping both changes inside the same transaction.
        self.db.flush()
        current_holdings = holdings_repository.active(self.db, self.portfolio_id)
        if (
            prefetched_quotes is None
            or self._holding_fingerprint(current_holdings) != expected_holdings
        ):
            portfolio_valuation.discard_today_snapshot(self.db, self.portfolio_id)
            self.db.commit()
            return
        try:
            valuation = portfolio_valuation.evaluate(
                self.db,
                self.portfolio_id,
                quote_loader=lambda _tickers: prefetched_quotes,
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
        expected_holdings, quotes = self._prefetch_valuation()
        write_serialization.begin_financial_write(self.db)
        try:
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
            self._commit_with_today_snapshot(expected_holdings, quotes)
            return trade
        except Exception:
            self.db.rollback()
            raise

    def remove(self, trade_id: int) -> str:
        """Remove one owned sale and commit today's consistent derived state."""
        expected_holdings, quotes = self._prefetch_valuation()
        write_serialization.begin_financial_write(self.db)
        try:
            trade = self._owned_trade(trade_id)
            ticker = str(trade.ticker)
            self.db.delete(trade)
            self._commit_with_today_snapshot(expected_holdings, quotes)
            return ticker
        except Exception:
            self.db.rollback()
            raise
