"""Transactional DCA plan ledger.

This module owns plan persistence, catch-up idempotency, contribution state
transitions, and the exact holding mutations for apply/undo.  HTTP callers only
translate domain errors; historical prices and ticker validation are injectable
external seams.
"""

from __future__ import annotations

from datetime import date
from functools import wraps
from typing import Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DcaContribution, DcaPlan, Holding
from app.services import (
    dca_service,
    financial_currency,
    holdings_repository,
    portfolio_lifecycle,
    write_serialization,
)
from app.services.stock_service import (
    get_daily_closes,
    normalize_ticker,
    validate_ticker_symbol,
)

TickerValidator = Callable[[str], dict]
PriceHistoryLoader = Callable[[str, str, str], dict[str, float]]
TodayFactory = Callable[[], date]

_ZERO_EPS = 1e-9
_PLAN_CURRENCY_SOURCES = financial_currency.TRUSTED_DCA_PLAN_CURRENCY_SOURCES
_CONTRIBUTION_CURRENCY_SOURCES = (
    financial_currency.TRUSTED_DCA_CONTRIBUTION_CURRENCY_SOURCES
)
_PLAN_CURRENCY_SOURCE = next(iter(_PLAN_CURRENCY_SOURCES))
_CONTRIBUTION_CURRENCY_SOURCE = next(iter(_CONTRIBUTION_CURRENCY_SOURCES))


def _serialized_write(method):
    """Run one DCA state transition behind SQLite's writer reservation."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        write_serialization.begin_financial_write(self.db)
        try:
            return method(self, *args, **kwargs)
        except Exception:
            self.db.rollback()
            raise

    return guarded


class DcaLedgerError(Exception):
    """Base error carrying a user-safe detail payload."""

    def __init__(self, detail: str | dict):
        super().__init__(str(detail))
        self.detail = detail


class DcaNotFoundError(DcaLedgerError):
    """Requested DCA record does not exist."""


class DcaConflictError(DcaLedgerError):
    """Requested transition conflicts with current ledger state."""


class DcaValidationError(DcaLedgerError):
    """External ticker validation rejected a proposed plan."""


class DcaLedger:
    """One coherent interface for a Portfolio's recurring-investment ledger."""

    def __init__(
        self,
        db: Session,
        *,
        ticker_validator: TickerValidator | None = None,
        price_history_loader: PriceHistoryLoader | None = None,
        today: TodayFactory | None = None,
    ):
        self.db = db
        self._ticker_validator = ticker_validator or validate_ticker_symbol
        self._price_history_loader = price_history_loader or get_daily_closes
        self._today = today or date.today

    def _plan(self, plan_id: int, *, portfolio_id: int) -> DcaPlan:
        plan = (
            self.db.query(DcaPlan)
            .filter(
                DcaPlan.id == plan_id,
                DcaPlan.portfolio_id == portfolio_id,
            )
            .first()
        )
        if plan is None:
            raise DcaNotFoundError("DCA plan not found")
        return plan

    @staticmethod
    def _validated_source_currency(validation: dict) -> str | None:
        """Read provider currency without mistaking a display fallback for proof."""
        quote = validation.get("quote")
        if isinstance(quote, dict):
            raw = quote.get("source_currency")
        else:
            raw = validation.get("source_currency")
        return financial_currency.normalize_currency(raw)

    @staticmethod
    def _plan_has_trusted_usd(plan: DcaPlan) -> bool:
        source = financial_currency.normalize_currency(plan.quote_currency_source)
        return bool(
            financial_currency.is_reporting_currency(plan.quote_currency)
            and source
            and source.lower() in _PLAN_CURRENCY_SOURCES
        )

    @staticmethod
    def _untrusted_plan_reason(plan: DcaPlan) -> str:
        currency = financial_currency.normalize_currency(plan.quote_currency)
        if currency and not financial_currency.is_reporting_currency(currency):
            return f"is recorded in {currency}, not USD"
        return "has no explicit trusted USD currency provenance"

    @classmethod
    def _untrusted_plan_message(cls, plan: DcaPlan) -> str:
        return (
            f"This DCA plan {cls._untrusted_plan_reason(plan)}. "
            "No contributions or holdings were changed; "
            "recreate it after FolioOrb verifies an explicit USD quote."
        )

    @classmethod
    def _plan_currency_message(cls, plan: DcaPlan) -> str:
        return (
            f"This plan {cls._untrusted_plan_reason(plan)}. Future buys cannot be "
            "created or applied. Undo applied buys if needed, then delete this plan. "
            "Create a replacement only after FolioOrb verifies an explicit USD quote."
        )

    @staticmethod
    def _contribution_has_trusted_usd(contribution: DcaContribution) -> bool:
        source = financial_currency.normalize_currency(
            contribution.price_currency_source
        )
        return bool(
            financial_currency.is_reporting_currency(contribution.price_currency)
            and source
            and source.lower() in _CONTRIBUTION_CURRENCY_SOURCES
        )

    @classmethod
    def _require_trusted_plan(cls, plan: DcaPlan) -> None:
        if cls._plan_has_trusted_usd(plan):
            return
        raise DcaConflictError(cls._untrusted_plan_message(plan))

    @classmethod
    def _require_trusted_contribution(
        cls, contribution: DcaContribution
    ) -> None:
        cls._require_trusted_plan(contribution.plan)
        if cls._contribution_has_trusted_usd(contribution):
            return
        currency = financial_currency.normalize_currency(
            contribution.price_currency
        )
        if currency and not financial_currency.is_reporting_currency(currency):
            reason = f"is recorded in {currency}, not USD"
        else:
            reason = "has no explicit trusted USD currency provenance"
        raise DcaConflictError(
            f"This DCA contribution {reason}. The holding and DCA ledger were "
            "left unchanged."
        )

    def _contribution(
        self, contribution_id: int, *, portfolio_id: int
    ) -> DcaContribution:
        contribution = (
            self.db.query(DcaContribution)
            .join(DcaPlan, DcaContribution.plan_id == DcaPlan.id)
            .filter(
                DcaContribution.id == contribution_id,
                DcaPlan.portfolio_id == portfolio_id,
            )
            .first()
        )
        if contribution is None:
            raise DcaNotFoundError("Contribution not found")
        return contribution

    def _plan_summary(self, plan: DcaPlan) -> dict:
        rows = (
            self.db.query(
                DcaContribution.status,
                func.count(DcaContribution.id),
                func.coalesce(func.sum(DcaContribution.amount), 0.0),
                func.coalesce(func.sum(DcaContribution.shares), 0.0),
            )
            .filter(DcaContribution.plan_id == plan.id)
            .group_by(DcaContribution.status)
            .all()
        )
        by_status = {status: (count, amount, shares) for status, count, amount, shares in rows}
        applied_count, applied_amount, applied_shares = by_status.get(
            "applied", (0, 0.0, 0.0)
        )
        pending_count = by_status.get("pending", (0, 0.0, 0.0))[0]
        trusted_usd = self._plan_has_trusted_usd(plan)
        next_date = dca_service.next_scheduled_date(
            plan.frequency,
            date.fromisoformat(plan.start_date),
            self._today(),
        )
        return {
            "id": plan.id,
            "portfolio_id": plan.portfolio_id,
            "ticker": plan.ticker,
            "amount": plan.amount,
            "quote_currency": plan.quote_currency,
            "quote_currency_source": plan.quote_currency_source,
            "currency_status": "trusted_usd" if trusted_usd else "needs_currency",
            "currency_message": (
                None if trusted_usd else self._plan_currency_message(plan)
            ),
            "frequency": plan.frequency,
            "start_date": plan.start_date,
            "is_active": plan.is_active,
            "pending_count": pending_count,
            "applied_count": applied_count,
            "applied_amount": round(float(applied_amount), 2),
            "applied_shares": round(float(applied_shares), 6),
            "applied_avg_cost": (
                round(float(applied_amount) / float(applied_shares), 4)
                if applied_shares > 0
                else None
            ),
            "next_date": (
                next_date.isoformat()
                if trusted_usd and plan.is_active and next_date
                else None
            ),
        }

    @staticmethod
    def _contribution_dict(contribution: DcaContribution) -> dict:
        return {
            "id": contribution.id,
            "plan_id": contribution.plan_id,
            "ticker": contribution.plan.ticker if contribution.plan else None,
            "scheduled_date": contribution.scheduled_date,
            "exec_date": contribution.exec_date,
            "price": round(float(contribution.price), 4),
            "shares": round(float(contribution.shares), 6),
            "amount": round(float(contribution.amount), 2),
            "price_currency": contribution.price_currency,
            "price_currency_source": contribution.price_currency_source,
            "status": contribution.status,
        }

    @staticmethod
    def _has_unbooked_dates(
        plan: DcaPlan,
        start: date,
        today: date,
        existing: set[str],
        floor: date,
    ) -> bool:
        """Could this plan owe a buy? Answered without touching market data.

        Weekly and monthly cadences step by calendar date — ``scheduled_dates``
        ignores the trading calendar for both — so the intended dates are known
        from the plan alone, and comparing them against what is already booked
        says whether pricing is worth doing.

        A daily cadence *is* the trading calendar, so it can't be answered here;
        those plans report True and pay for the fetch as before.

        Deliberately one-sided: True only means a fetch is warranted, not that a
        buy will be added. ``plan_contributions`` still drops intended dates with
        no trading day yet, so the caller may price a window and add nothing.
        """
        if plan.frequency == "daily":
            return True
        intended = dca_service.scheduled_dates(plan.frequency, start, today, [])
        return any(
            day >= floor and day.isoformat() not in existing for day in intended
        )

    @staticmethod
    def _catch_up_fingerprint(plan: DcaPlan) -> tuple:
        """Facts that must still match after price discovery completes."""
        return (
            plan.ticker,
            float(plan.amount),
            plan.frequency,
            plan.start_date,
            plan.catchup_floor,
            plan.quote_currency,
            plan.quote_currency_source,
            bool(plan.is_active),
        )

    def _catch_up_needs_prices(self, plan: DcaPlan, today: date) -> bool:
        """Preview whether catch-up needs an external price-history request."""
        start = date.fromisoformat(plan.start_date)
        if start > today:
            return False
        existing = {
            row[0]
            for row in self.db.query(DcaContribution.scheduled_date)
            .filter(DcaContribution.plan_id == plan.id)
            .all()
        }
        floor = date.fromisoformat(plan.catchup_floor) if plan.catchup_floor else start
        return self._has_unbooked_dates(plan, start, today, existing, floor)

    def _catch_up(
        self,
        plan: DcaPlan,
        today: date,
        closes: dict[str, float] | None,
    ) -> tuple[int, bool]:
        """Persist due buys using prices fetched before the writer reservation."""
        self._require_trusted_plan(plan)
        start = date.fromisoformat(plan.start_date)
        if start > today:
            return 0, True
        existing = {
            row[0]
            for row in self.db.query(DcaContribution.scheduled_date)
            .filter(DcaContribution.plan_id == plan.id)
            .all()
        }
        floor = date.fromisoformat(plan.catchup_floor) if plan.catchup_floor else start
        if not self._has_unbooked_dates(plan, start, today, existing, floor):
            # Nothing is due, which is the steady state on every page load. The
            # window would be the plan's whole history, so not fetching it is
            # the difference between a no-op and years of daily bars per plan.
            return 0, True
        if not closes:
            return 0, False
        computed = dca_service.plan_contributions(
            plan.frequency,
            plan.amount,
            start,
            today,
            sorted((date.fromisoformat(day), price) for day, price in closes.items()),
        )
        added = 0
        for item in computed:
            scheduled = item["scheduled_date"].isoformat()
            if scheduled in existing or item["scheduled_date"] < floor:
                continue
            self.db.add(
                DcaContribution(
                    plan_id=plan.id,
                    scheduled_date=scheduled,
                    exec_date=item["exec_date"].isoformat(),
                    price=item["price"],
                    shares=item["shares"],
                    amount=item["amount"],
                    price_currency=plan.quote_currency,
                    price_currency_source=_CONTRIBUTION_CURRENCY_SOURCE,
                    status="pending",
                )
            )
            added += 1
        return added, True

    def create_plan(
        self,
        *,
        portfolio_id: int,
        ticker: str,
        amount: float,
        frequency: str,
        start_date: str,
    ) -> dict:
        """Create a validated plan and backfill due buys atomically."""
        # Local ownership and duplicate previews avoid unnecessary provider work.
        # Neither preview authorizes the write; both are repeated after reserving
        # SQLite's sole writer below.
        portfolio_lifecycle.require_portfolio(self.db, portfolio_id)
        duplicate = (
            self.db.query(DcaPlan)
            .filter(
                DcaPlan.portfolio_id == portfolio_id,
                DcaPlan.ticker == ticker,
                DcaPlan.frequency == frequency,
                DcaPlan.amount == amount,
                DcaPlan.is_active.is_(True),
            )
            .first()
        )
        if duplicate:
            raise DcaConflictError(
                f"You already have an active {frequency} ${amount:g} {ticker} plan."
            )
        validation = self._ticker_validator(ticker)
        if not validation["valid"]:
            raise DcaValidationError(
                {
                    "message": validation["message"],
                    "suggestions": validation["suggestions"],
                }
            )
        currency = self._validated_source_currency(validation)
        if not currency:
            raise DcaValidationError(
                {
                    "message": (
                        f"Could not verify that {ticker} is quoted in USD. "
                        "No DCA plan was created because missing currency cannot "
                        "be treated as dollar provenance."
                    ),
                    "suggestions": validation.get("suggestions", []),
                }
            )
        if not financial_currency.is_reporting_currency(currency):
            raise DcaValidationError(
                {
                    "message": (
                        f"{ticker} is quoted in {currency}. FolioOrb DCA plans "
                        "support USD quotes only because no FX conversion is applied."
                    ),
                    "suggestions": validation.get("suggestions", []),
                }
            )
        plan = DcaPlan(
            portfolio_id=portfolio_id,
            ticker=ticker,
            amount=amount,
            frequency=frequency,
            start_date=start_date,
            quote_currency=currency,
            quote_currency_source=_PLAN_CURRENCY_SOURCE,
            is_active=True,
        )
        today = self._today()
        needs_prices = (
            date.fromisoformat(start_date) <= today
            and self._has_unbooked_dates(
                plan,
                date.fromisoformat(start_date),
                today,
                set(),
                date.fromisoformat(start_date),
            )
        )
        # End discovery reads before waiting on a provider or a writer lock.
        self.db.rollback()
        closes = (
            self._price_history_loader(ticker, start_date, today.isoformat())
            if needs_prices
            else None
        )

        write_serialization.begin_financial_write(self.db)
        try:
            portfolio_lifecycle.require_portfolio(self.db, portfolio_id)
            duplicate = (
                self.db.query(DcaPlan)
                .filter(
                    DcaPlan.portfolio_id == portfolio_id,
                    DcaPlan.ticker == ticker,
                    DcaPlan.frequency == frequency,
                    DcaPlan.amount == amount,
                    DcaPlan.is_active.is_(True),
                )
                .first()
            )
            if duplicate:
                raise DcaConflictError(
                    f"You already have an active {frequency} ${amount:g} "
                    f"{ticker} plan."
                )
            self.db.add(plan)
            self.db.flush()
            added, _ = self._catch_up(plan, today, closes)
            self.db.commit()
            self.db.refresh(plan)
            return {"plan": self._plan_summary(plan), "buys_added": added}
        except Exception:
            self.db.rollback()
            raise

    def list_plans(self, portfolio_id: int) -> list[dict]:
        portfolio_lifecycle.require_portfolio(self.db, portfolio_id)
        plans = (
            self.db.query(DcaPlan)
            .filter(DcaPlan.portfolio_id == portfolio_id)
            .order_by(DcaPlan.created_at.desc())
            .all()
        )
        return [self._plan_summary(plan) for plan in plans]

    @_serialized_write
    def update_plan(
        self,
        plan_id: int,
        *,
        portfolio_id: int,
        amount: float | None = None,
        is_active: bool | None = None,
    ) -> dict:
        plan = self._plan(plan_id, portfolio_id=portfolio_id)
        if amount is not None:
            plan.amount = amount
        if is_active is not None:
            if is_active and not plan.is_active:
                plan.catchup_floor = self._today().isoformat()
            plan.is_active = is_active
        self.db.commit()
        self.db.refresh(plan)
        return self._plan_summary(plan)

    @_serialized_write
    def delete_plan(self, plan_id: int, *, portfolio_id: int) -> str:
        plan = self._plan(plan_id, portfolio_id=portfolio_id)
        applied_count = (
            self.db.query(DcaContribution)
            .filter(
                DcaContribution.plan_id == plan_id,
                DcaContribution.status == "applied",
            )
            .count()
        )
        if applied_count:
            raise DcaConflictError(
                "Undo applied buys before deleting this plan so its holding changes "
                "remain traceable."
            )
        ticker = plan.ticker
        self.db.delete(plan)
        self.db.commit()
        return f"DCA plan for {ticker} deleted"

    def run_catchup(self, portfolio_id: int) -> dict:
        """Discover prices outside the lock, then revalidate and persist once."""
        portfolio_lifecycle.require_portfolio(self.db, portfolio_id)
        preview_plans = (
            self.db.query(DcaPlan)
            .filter(DcaPlan.portfolio_id == portfolio_id, DcaPlan.is_active.is_(True))
            .all()
        )
        today = self._today()
        previews = {}
        for plan in preview_plans:
            trusted = self._plan_has_trusted_usd(plan)
            previews[plan.id] = {
                "fingerprint": self._catch_up_fingerprint(plan),
                "load": trusted and self._catch_up_needs_prices(plan, today),
                "ticker": plan.ticker,
                "start_date": plan.start_date,
            }
        self.db.rollback()

        for preview in previews.values():
            preview["closes"] = (
                self._price_history_loader(
                    preview["ticker"], preview["start_date"], today.isoformat()
                )
                if preview["load"]
                else None
            )

        write_serialization.begin_financial_write(self.db)
        try:
            portfolio_lifecycle.require_portfolio(self.db, portfolio_id)
            plans = (
                self.db.query(DcaPlan)
                .filter(
                    DcaPlan.portfolio_id == portfolio_id,
                    DcaPlan.is_active.is_(True),
                )
                .all()
            )
            results = []
            total = 0
            blocked = 0
            for plan in plans:
                preview = previews.get(plan.id)
                if (
                    preview is None
                    or preview["fingerprint"] != self._catch_up_fingerprint(plan)
                ):
                    blocked += 1
                    results.append(
                        {
                            "plan_id": plan.id,
                            "ticker": plan.ticker,
                            "buys_added": 0,
                            "price_data": None,
                            "status": "changed",
                            "message": (
                                "This plan changed while prices were loading. "
                                "No buys were added; run catch-up again."
                            ),
                        }
                    )
                    continue
                # Legacy and foreign-currency plans remain fail-closed, but their
                # migration state is local to the plan. One such row must not prevent
                # an unrelated, explicitly verified USD plan from catching up.
                if not self._plan_has_trusted_usd(plan):
                    blocked += 1
                    results.append(
                        {
                            "plan_id": plan.id,
                            "ticker": plan.ticker,
                            "buys_added": 0,
                            "price_data": None,
                            "status": "needs_currency",
                            "message": self._untrusted_plan_message(plan),
                        }
                    )
                    continue
                added, priced = self._catch_up(plan, today, preview["closes"])
                total += added
                results.append(
                    {
                        "plan_id": plan.id,
                        "ticker": plan.ticker,
                        "buys_added": added,
                        "price_data": priced,
                        "status": "ready" if priced else "price_unavailable",
                    }
                )
            self.db.commit()
            return {
                "buys_added": total,
                "plans_checked": len(plans),
                "plans_blocked": blocked,
                "plans": results,
            }
        except Exception:
            self.db.rollback()
            raise

    def list_contributions(self, portfolio_id: int, status: str = "pending") -> list[dict]:
        portfolio_lifecycle.require_portfolio(self.db, portfolio_id)
        query = (
            self.db.query(DcaContribution)
            .join(DcaPlan, DcaContribution.plan_id == DcaPlan.id)
            .filter(DcaPlan.portfolio_id == portfolio_id)
        )
        if status != "all":
            query = query.filter(DcaContribution.status == status)
        return [
            self._contribution_dict(item)
            for item in query.order_by(DcaContribution.exec_date.desc()).all()
        ]

    def _apply(self, contribution: DcaContribution) -> Holding:
        self._require_trusted_contribution(contribution)
        plan = contribution.plan
        holding = holdings_repository.active_by_ticker(
            self.db, plan.portfolio_id, plan.ticker
        )
        if holding is None:
            candidate = Holding(
                portfolio_id=plan.portfolio_id,
                ticker=plan.ticker,
                shares=0.0,
                avg_cost=0.0,
                is_watchlist=False,
            )
            holding = holdings_repository.add_active(self.db, candidate)
            if holding is None:
                holding = holdings_repository.active_by_ticker(
                    self.db, plan.portfolio_id, plan.ticker
                )
            if holding is None:
                raise DcaConflictError("The holding changed while applying this buy")
        holding.shares, holding.avg_cost = dca_service.apply_to_holding(
            holding.shares or 0.0,
            holding.avg_cost or 0.0,
            contribution.shares,
            contribution.amount,
        )
        holding.is_watchlist = False
        contribution.status = "applied"
        contribution.applied_holding_id = holding.id
        return holding

    @_serialized_write
    def apply_contribution(self, contribution_id: int, *, portfolio_id: int) -> dict:
        contribution = self._contribution(
            contribution_id, portfolio_id=portfolio_id
        )
        if contribution.status != "pending":
            raise DcaConflictError(f"Buy is already {contribution.status}")
        holding = self._apply(contribution)
        self.db.commit()
        return {
            "message": (
                f"Applied {contribution.shares:.4f} "
                f"{contribution.plan.ticker} @ ${contribution.price:.2f}"
            ),
            "contribution": self._contribution_dict(contribution),
            "holding": {
                "id": holding.id,
                "shares": holding.shares,
                "avg_cost": holding.avg_cost,
            },
        }

    def _bulk_contributions(
        self,
        plan_id: int,
        contribution_ids: list[int],
        *,
        expected_status: str,
        newest_first: bool = False,
    ) -> list[DcaContribution]:
        """Resolve one reviewed ID set or reject the whole stale operation."""
        ids = [int(contribution_id) for contribution_id in contribution_ids]
        if not ids or any(contribution_id <= 0 for contribution_id in ids):
            raise DcaConflictError("Select at least one valid DCA buy")
        if len(ids) != len(set(ids)):
            raise DcaConflictError("The selected DCA buys must be unique")
        rows = (
            self.db.query(DcaContribution)
            .filter(DcaContribution.id.in_(ids))
            .all()
        )
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(ids) or any(
            row.plan_id != plan_id or row.status != expected_status
            for row in rows
        ):
            raise DcaConflictError(
                "The selected DCA buys changed. Refresh and review the action again."
            )
        return sorted(
            rows,
            key=lambda row: (row.exec_date, row.id),
            reverse=newest_first,
        )

    @_serialized_write
    def apply_all_pending(
        self,
        plan_id: int,
        *,
        portfolio_id: int,
        contribution_ids: list[int],
    ) -> dict:
        plan = self._plan(plan_id, portfolio_id=portfolio_id)
        pending = self._bulk_contributions(
            plan_id,
            contribution_ids,
            expected_status="pending",
        )
        # Bulk apply is one financial transaction. Preflight every row before
        # touching the holding so a later ambiguous/foreign contribution cannot
        # leave earlier rows staged in the session.
        for contribution in pending:
            self._require_trusted_contribution(contribution)
        for contribution in pending:
            self._apply(contribution)
        self.db.commit()
        return {"applied": len(pending), "ticker": plan.ticker}

    @_serialized_write
    def skip_contribution(self, contribution_id: int, *, portfolio_id: int) -> dict:
        contribution = self._contribution(
            contribution_id, portfolio_id=portfolio_id
        )
        if contribution.status != "pending":
            raise DcaConflictError(f"Buy is already {contribution.status}")
        contribution.status = "dismissed"
        self.db.commit()
        return {
            "message": "Buy skipped",
            "contribution": self._contribution_dict(contribution),
        }

    @_serialized_write
    def skip_all_pending(
        self,
        plan_id: int,
        *,
        portfolio_id: int,
        contribution_ids: list[int],
    ) -> dict:
        plan = self._plan(plan_id, portfolio_id=portfolio_id)
        pending = self._bulk_contributions(
            plan_id,
            contribution_ids,
            expected_status="pending",
        )
        for contribution in pending:
            contribution.status = "dismissed"
        self.db.commit()
        return {"skipped": len(pending), "ticker": plan.ticker}

    @_serialized_write
    def restore_contribution(
        self, contribution_id: int, *, portfolio_id: int
    ) -> dict:
        contribution = self._contribution(
            contribution_id, portfolio_id=portfolio_id
        )
        if contribution.status != "dismissed":
            raise DcaConflictError("Only skipped buys can be restored")
        contribution.status = "pending"
        self.db.commit()
        return {
            "message": "Buy restored to pending",
            "contribution": self._contribution_dict(contribution),
        }

    def _reverse(self, contribution: DcaContribution) -> None:
        # Scoped by the plan's portfolio, mirroring `_apply`. `applied_holding_id`
        # is a bare integer with no foreign key, so resolving it by primary key
        # alone let an undo rewrite a holding owned by a different portfolio.
        holding = (
            holdings_repository.in_portfolio(
                self.db,
                contribution.plan.portfolio_id,
                contribution.applied_holding_id,
                active_only=True,
            )
            if contribution.applied_holding_id
            else None
        )
        if (
            holding is None
            or normalize_ticker(holding.ticker)
            != normalize_ticker(contribution.plan.ticker)
        ):
            # Missing, foreign, and wrong-ticker links are integrity failures:
            # clearing the ledger would make a later re-apply duplicate shares
            # or basis while mutating the wrong position is worse.
            raise DcaConflictError(
                "This buy cannot be safely undone because its linked holding is "
                "not the matching position in this portfolio. The holding and "
                "DCA ledger were left unchanged."
            )
        try:
            new_shares, new_avg = dca_service.undo_from_holding(
                holding.shares or 0.0,
                holding.avg_cost or 0.0,
                contribution.shares,
                contribution.amount,
            )
        except ValueError as exc:
            raise DcaConflictError(
                "This buy cannot be safely undone after later holding changes. "
                "The holding and DCA ledger were left unchanged."
            ) from exc
        holding.shares, holding.avg_cost = new_shares, new_avg
        if holding.shares <= _ZERO_EPS:
            holding.is_active = False
        contribution.status = "pending"
        contribution.applied_holding_id = None

    @_serialized_write
    def undo_contribution(self, contribution_id: int, *, portfolio_id: int) -> dict:
        contribution = self._contribution(
            contribution_id, portfolio_id=portfolio_id
        )
        if contribution.status != "applied":
            raise DcaConflictError("Only applied buys can be undone")
        self._reverse(contribution)
        self.db.commit()
        return {
            "message": "Buy undone",
            "contribution": self._contribution_dict(contribution),
        }

    @_serialized_write
    def undo_all_applied(
        self,
        plan_id: int,
        *,
        portfolio_id: int,
        contribution_ids: list[int],
    ) -> dict:
        plan = self._plan(plan_id, portfolio_id=portfolio_id)
        applied = self._bulk_contributions(
            plan_id,
            contribution_ids,
            expected_status="applied",
            newest_first=True,
        )
        try:
            for contribution in applied:
                self._reverse(contribution)
        except DcaConflictError:
            # A prior iteration may already have staged a safe reversal. Bulk
            # undo is one operation, so restore every holding/contribution row.
            self.db.rollback()
            raise
        self.db.commit()
        return {"undone": len(applied), "ticker": plan.ticker}
