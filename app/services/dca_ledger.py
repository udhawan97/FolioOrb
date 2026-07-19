"""Transactional DCA plan ledger.

This module owns plan persistence, catch-up idempotency, contribution state
transitions, and the exact holding mutations for apply/undo.  HTTP callers only
translate domain errors; historical prices and ticker validation are injectable
external seams.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DcaContribution, DcaPlan, Holding
from app.services import dca_service, holdings_repository, portfolio_lifecycle
from app.services.stock_service import get_daily_closes, validate_ticker_symbol

TickerValidator = Callable[[str], dict]
PriceHistoryLoader = Callable[[str, str, str], dict[str, float]]
TodayFactory = Callable[[], date]

_ZERO_EPS = 1e-9


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

    def _plan(self, plan_id: int) -> DcaPlan:
        plan = self.db.query(DcaPlan).filter(DcaPlan.id == plan_id).first()
        if plan is None:
            raise DcaNotFoundError("DCA plan not found")
        return plan

    def _contribution(self, contribution_id: int) -> DcaContribution:
        contribution = (
            self.db.query(DcaContribution)
            .filter(DcaContribution.id == contribution_id)
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
            "next_date": next_date.isoformat() if plan.is_active and next_date else None,
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

    def _catch_up(self, plan: DcaPlan, today: date) -> tuple[int, bool]:
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
        closes = self._price_history_loader(
            plan.ticker, plan.start_date, today.isoformat()
        )
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
        plan = DcaPlan(
            portfolio_id=portfolio_id,
            ticker=ticker,
            amount=amount,
            frequency=frequency,
            start_date=start_date,
            is_active=True,
        )
        self.db.add(plan)
        self.db.flush()
        added, _ = self._catch_up(plan, self._today())
        self.db.commit()
        self.db.refresh(plan)
        return {"plan": self._plan_summary(plan), "buys_added": added}

    def list_plans(self, portfolio_id: int) -> list[dict]:
        portfolio_lifecycle.require_portfolio(self.db, portfolio_id)
        plans = (
            self.db.query(DcaPlan)
            .filter(DcaPlan.portfolio_id == portfolio_id)
            .order_by(DcaPlan.created_at.desc())
            .all()
        )
        return [self._plan_summary(plan) for plan in plans]

    def update_plan(
        self,
        plan_id: int,
        *,
        amount: float | None = None,
        is_active: bool | None = None,
    ) -> dict:
        plan = self._plan(plan_id)
        if amount is not None:
            plan.amount = amount
        if is_active is not None:
            if is_active and not plan.is_active:
                plan.catchup_floor = self._today().isoformat()
            plan.is_active = is_active
        self.db.commit()
        self.db.refresh(plan)
        return self._plan_summary(plan)

    def delete_plan(self, plan_id: int) -> str:
        plan = self._plan(plan_id)
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
        portfolio_lifecycle.require_portfolio(self.db, portfolio_id)
        plans = (
            self.db.query(DcaPlan)
            .filter(DcaPlan.portfolio_id == portfolio_id, DcaPlan.is_active.is_(True))
            .all()
        )
        results = []
        total = 0
        today = self._today()
        for plan in plans:
            added, priced = self._catch_up(plan, today)
            total += added
            results.append(
                {
                    "plan_id": plan.id,
                    "ticker": plan.ticker,
                    "buys_added": added,
                    "price_data": priced,
                }
            )
        self.db.commit()
        return {"buys_added": total, "plans_checked": len(plans), "plans": results}

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
        plan = contribution.plan
        holding = holdings_repository.active_by_ticker(
            self.db, plan.portfolio_id, plan.ticker
        )
        if holding is None:
            holding = Holding(
                portfolio_id=plan.portfolio_id,
                ticker=plan.ticker,
                shares=0.0,
                avg_cost=0.0,
                is_watchlist=False,
            )
            self.db.add(holding)
            self.db.flush()
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

    def apply_contribution(self, contribution_id: int) -> dict:
        contribution = self._contribution(contribution_id)
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

    def apply_all_pending(self, plan_id: int) -> dict:
        plan = self._plan(plan_id)
        pending = (
            self.db.query(DcaContribution)
            .filter(
                DcaContribution.plan_id == plan_id,
                DcaContribution.status == "pending",
            )
            .order_by(DcaContribution.exec_date.asc())
            .all()
        )
        for contribution in pending:
            self._apply(contribution)
        self.db.commit()
        return {"applied": len(pending), "ticker": plan.ticker}

    def skip_contribution(self, contribution_id: int) -> dict:
        contribution = self._contribution(contribution_id)
        if contribution.status != "pending":
            raise DcaConflictError(f"Buy is already {contribution.status}")
        contribution.status = "dismissed"
        self.db.commit()
        return {
            "message": "Buy skipped",
            "contribution": self._contribution_dict(contribution),
        }

    def skip_all_pending(self, plan_id: int) -> dict:
        plan = self._plan(plan_id)
        skipped = (
            self.db.query(DcaContribution)
            .filter(
                DcaContribution.plan_id == plan_id,
                DcaContribution.status == "pending",
            )
            .update({DcaContribution.status: "dismissed"}, synchronize_session=False)
        )
        self.db.commit()
        return {"skipped": skipped, "ticker": plan.ticker}

    def restore_contribution(self, contribution_id: int) -> dict:
        contribution = self._contribution(contribution_id)
        if contribution.status != "dismissed":
            raise DcaConflictError("Only skipped buys can be restored")
        contribution.status = "pending"
        self.db.commit()
        return {
            "message": "Buy restored to pending",
            "contribution": self._contribution_dict(contribution),
        }

    def _reverse(self, contribution: DcaContribution) -> str | None:
        holding = (
            self.db.query(Holding)
            .filter(Holding.id == contribution.applied_holding_id)
            .first()
            if contribution.applied_holding_id
            else None
        )
        note = None
        if holding is None:
            note = (
                "Holding no longer exists; buy returned to pending without "
                "changing holdings."
            )
        else:
            holding.shares, holding.avg_cost = dca_service.undo_from_holding(
                holding.shares or 0.0,
                holding.avg_cost or 0.0,
                contribution.shares,
                contribution.amount,
            )
            if holding.shares <= _ZERO_EPS:
                holding.is_active = False
        contribution.status = "pending"
        contribution.applied_holding_id = None
        return note

    def undo_contribution(self, contribution_id: int) -> dict:
        contribution = self._contribution(contribution_id)
        if contribution.status != "applied":
            raise DcaConflictError("Only applied buys can be undone")
        note = self._reverse(contribution)
        self.db.commit()
        return {
            "message": note or "Buy undone",
            "contribution": self._contribution_dict(contribution),
        }

    def undo_all_applied(self, plan_id: int) -> dict:
        plan = self._plan(plan_id)
        applied = (
            self.db.query(DcaContribution)
            .filter(
                DcaContribution.plan_id == plan_id,
                DcaContribution.status == "applied",
            )
            .order_by(DcaContribution.exec_date.desc())
            .all()
        )
        for contribution in applied:
            self._reverse(contribution)
        self.db.commit()
        return {"undone": len(applied), "ticker": plan.ticker}
