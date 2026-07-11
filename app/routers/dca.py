"""Dollar-cost-averaging (DCA) plan endpoints.

A DCA plan mirrors a brokerage auto-invest locally: invest a fixed dollar amount
in a ticker every interval. The plan never touches a holding on its own — it
fills a *simulated bucket* of computed buys (using real historical closes) that
the user reviews and applies one by one, with full undo.

Pure date/price/cost math lives in ``app/services/dca_service.py``; this module
handles persistence, ticker validation, and the price fetch.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DcaPlan, DcaContribution, Holding
from app.schemas import DcaPlanCreate, DcaPlanUpdate
from app.services import dca_service
from app.services.stock_service import get_daily_closes, validate_ticker_symbol
from app.routers.portfolio import _get_portfolio_or_404

router = APIRouter(prefix="/api/dca", tags=["dca"])


# ── Serialization ──────────────────────────────────────────────────────

def _plan_summary(plan: DcaPlan, db: Session) -> dict:
    """Serialize a plan with rolled-up bucket stats for the list view."""
    rows = (
        db.query(
            DcaContribution.status,
            func.count(DcaContribution.id),
            func.coalesce(func.sum(DcaContribution.amount), 0.0),
            func.coalesce(func.sum(DcaContribution.shares), 0.0),
        )
        .filter(DcaContribution.plan_id == plan.id)
        .group_by(DcaContribution.status)
        .all()
    )
    by_status = {status: (count, amt, sh) for status, count, amt, sh in rows}
    applied_count, applied_amount, applied_shares = by_status.get("applied", (0, 0.0, 0.0))
    pending_count = by_status.get("pending", (0, 0.0, 0.0))[0]

    next_date = dca_service.next_scheduled_date(
        plan.frequency, date.fromisoformat(plan.start_date), date.today()
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
        "applied_amount": round(applied_amount, 2),
        "applied_shares": round(applied_shares, 6),
        "applied_avg_cost": round(applied_amount / applied_shares, 4)
        if applied_shares > 0
        else None,
        "next_date": next_date.isoformat() if (plan.is_active and next_date) else None,
    }


def _contribution_dict(c: DcaContribution) -> dict:
    return {
        "id": c.id,
        "plan_id": c.plan_id,
        "ticker": c.plan.ticker if c.plan else None,
        "scheduled_date": c.scheduled_date,
        "exec_date": c.exec_date,
        "price": round(c.price, 4),
        "shares": round(c.shares, 6),
        "amount": round(c.amount, 2),
        "status": c.status,
    }


# ── Catch-up (generate pending buys) ───────────────────────────────────

def _run_plan_catchup_status(
    plan: DcaPlan, today: date, db: Session
) -> tuple[int, bool]:
    """Book any not-yet-recorded buys for ``plan`` up to ``today`` as *pending*.

    Idempotent: contributions already present for a scheduled date are skipped,
    so this is safe to call on every app open (fills gaps after the app was
    closed for days or weeks). Returns ``(buys_added, price_data_ok)`` —
    ``price_data_ok`` is False when the price fetch returned nothing, so the UI
    can tell "nothing was due" apart from "couldn't price the ticker".
    """
    start = date.fromisoformat(plan.start_date)
    if start > today:
        return 0, True
    closes = get_daily_closes(plan.ticker, plan.start_date, today.isoformat())
    if not closes:
        return 0, False
    closes_sorted = sorted((date.fromisoformat(d), px) for d, px in closes.items())
    computed = dca_service.plan_contributions(
        plan.frequency, plan.amount, start, today, closes_sorted
    )
    existing = {
        row[0]
        for row in db.query(DcaContribution.scheduled_date)
        .filter(DcaContribution.plan_id == plan.id)
        .all()
    }
    added = 0
    for c in computed:
        sched = c["scheduled_date"].isoformat()
        if sched in existing:
            continue
        db.add(
            DcaContribution(
                plan_id=plan.id,
                scheduled_date=sched,
                exec_date=c["exec_date"].isoformat(),
                price=c["price"],
                shares=c["shares"],
                amount=c["amount"],
                status="pending",
            )
        )
        added += 1
    return added, True


def _run_plan_catchup(plan: DcaPlan, today: date, db: Session) -> int:
    """Convenience wrapper returning just the number of buys added."""
    added, _ = _run_plan_catchup_status(plan, today, db)
    return added


# ── Plan CRUD ──────────────────────────────────────────────────────────

@router.post("/plans")
async def create_plan(
    data: DcaPlanCreate, portfolio_id: int = 1, db: Session = Depends(get_db)
):
    """Create a DCA plan and backfill its past buys into the pending bucket."""
    _get_portfolio_or_404(portfolio_id, db)

    # Network check: reject an invalid symbol before storing the plan.
    validation = validate_ticker_symbol(data.ticker)
    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": validation["message"],
                "suggestions": validation["suggestions"],
            },
        )

    plan = DcaPlan(
        portfolio_id=portfolio_id,
        ticker=data.ticker,
        amount=data.amount,
        frequency=data.frequency,
        start_date=data.start_date,
        is_active=True,
    )
    db.add(plan)
    db.flush()  # assign plan.id before generating contributions

    added = _run_plan_catchup(plan, date.today(), db)
    db.commit()
    db.refresh(plan)
    return {"plan": _plan_summary(plan, db), "buys_added": added}


@router.get("/plans")
async def list_plans(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """List all DCA plans for a portfolio with their bucket summaries."""
    _get_portfolio_or_404(portfolio_id, db)
    plans = (
        db.query(DcaPlan)
        .filter(DcaPlan.portfolio_id == portfolio_id)
        .order_by(DcaPlan.created_at.desc())
        .all()
    )
    return {"plans": [_plan_summary(p, db) for p in plans]}


@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: int, data: DcaPlanUpdate, db: Session = Depends(get_db)
):
    """Pause/resume a plan or change its per-interval amount."""
    plan = db.query(DcaPlan).filter(DcaPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="DCA plan not found")
    if data.amount is not None:
        plan.amount = data.amount
    if data.is_active is not None:
        plan.is_active = data.is_active
    db.commit()
    db.refresh(plan)
    return {"plan": _plan_summary(plan, db)}


@router.delete("/plans/{plan_id}")
async def delete_plan(plan_id: int, db: Session = Depends(get_db)):
    """Delete a plan and its bucket. Already-applied buys stay in your holdings
    (undo them first if you want them reversed)."""
    plan = db.query(DcaPlan).filter(DcaPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="DCA plan not found")
    db.delete(plan)  # cascade removes its contributions
    db.commit()
    return {"message": f"DCA plan for {plan.ticker} deleted"}


# ── Catch-up endpoints ─────────────────────────────────────────────────

@router.post("/run")
async def run_catchup(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Fill in any missed buys for every active plan (called on app open).

    Returns per-plan results so the UI can badge new buys and surface plans
    whose price data could not be fetched (``price_data: false``).
    """
    _get_portfolio_or_404(portfolio_id, db)
    plans = (
        db.query(DcaPlan)
        .filter(DcaPlan.portfolio_id == portfolio_id, DcaPlan.is_active.is_(True))
        .all()
    )
    today = date.today()
    results = []
    total = 0
    for plan in plans:
        added, priced = _run_plan_catchup_status(plan, today, db)
        total += added
        results.append(
            {
                "plan_id": plan.id,
                "ticker": plan.ticker,
                "buys_added": added,
                "price_data": priced,
            }
        )
    db.commit()
    return {"buys_added": total, "plans_checked": len(plans), "plans": results}


# ── Bucket review: list / apply / skip / undo ──────────────────────────

@router.get("/contributions")
async def list_contributions(
    portfolio_id: int = 1,
    status: str = Query("pending"),
    db: Session = Depends(get_db),
):
    """List bucket buys for a portfolio, filtered by status (default pending)."""
    _get_portfolio_or_404(portfolio_id, db)
    q = (
        db.query(DcaContribution)
        .join(DcaPlan, DcaContribution.plan_id == DcaPlan.id)
        .filter(DcaPlan.portfolio_id == portfolio_id)
    )
    if status != "all":
        q = q.filter(DcaContribution.status == status)
    rows = q.order_by(DcaContribution.exec_date.desc()).all()
    return {"contributions": [_contribution_dict(c) for c in rows]}


def _get_contribution_or_404(cid: int, db: Session) -> DcaContribution:
    c = db.query(DcaContribution).filter(DcaContribution.id == cid).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contribution not found")
    return c


def _apply_contribution(c: DcaContribution, db: Session) -> Holding:
    """Add one pending buy to the plan's ticker holding, creating it if needed."""
    plan = c.plan
    holding = (
        db.query(Holding)
        .filter(
            Holding.portfolio_id == plan.portfolio_id,
            Holding.ticker == plan.ticker,
            Holding.is_active.is_(True),
        )
        .first()
    )
    if holding is None:
        holding = Holding(
            portfolio_id=plan.portfolio_id,
            ticker=plan.ticker,
            shares=0.0,
            avg_cost=0.0,
            is_watchlist=False,
        )
        db.add(holding)
        db.flush()
    new_shares, new_avg = dca_service.apply_to_holding(
        holding.shares or 0.0, holding.avg_cost or 0.0, c.shares, c.amount
    )
    holding.shares = new_shares
    holding.avg_cost = new_avg
    holding.is_watchlist = False  # a real buy makes this a position, not research-only
    c.status = "applied"
    c.applied_holding_id = holding.id
    return holding


@router.post("/contributions/{cid}/apply")
async def apply_contribution(cid: int, db: Session = Depends(get_db)):
    """Apply a pending buy to the real holding (updates shares + avg cost)."""
    c = _get_contribution_or_404(cid, db)
    if c.status != "pending":
        raise HTTPException(status_code=400, detail=f"Buy is already {c.status}")
    holding = _apply_contribution(c, db)
    db.commit()
    return {
        "message": f"Applied {c.shares:.4f} {c.plan.ticker} @ ${c.price:.2f}",
        "contribution": _contribution_dict(c),
        "holding": {"id": holding.id, "shares": holding.shares, "avg_cost": holding.avg_cost},
    }


@router.post("/plans/{plan_id}/apply-pending")
async def apply_all_pending(plan_id: int, db: Session = Depends(get_db)):
    """Apply every pending buy for a plan at once (handy after a backfill)."""
    plan = db.query(DcaPlan).filter(DcaPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="DCA plan not found")
    pending = (
        db.query(DcaContribution)
        .filter(DcaContribution.plan_id == plan_id, DcaContribution.status == "pending")
        .order_by(DcaContribution.exec_date.asc())
        .all()
    )
    for c in pending:
        _apply_contribution(c, db)
    db.commit()
    return {"applied": len(pending), "ticker": plan.ticker}


@router.post("/contributions/{cid}/skip")
async def skip_contribution(cid: int, db: Session = Depends(get_db)):
    """Dismiss a pending buy — it stays out of your holdings and won't reappear."""
    c = _get_contribution_or_404(cid, db)
    if c.status != "pending":
        raise HTTPException(status_code=400, detail=f"Buy is already {c.status}")
    c.status = "dismissed"
    db.commit()
    return {"message": "Buy skipped", "contribution": _contribution_dict(c)}


@router.post("/plans/{plan_id}/skip-pending")
async def skip_all_pending(plan_id: int, db: Session = Depends(get_db)):
    """Dismiss every pending buy for a plan at once (e.g. after a backfill the
    user's holding already reflects)."""
    plan = db.query(DcaPlan).filter(DcaPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="DCA plan not found")
    skipped = (
        db.query(DcaContribution)
        .filter(DcaContribution.plan_id == plan_id, DcaContribution.status == "pending")
        .update({DcaContribution.status: "dismissed"}, synchronize_session=False)
    )
    db.commit()
    return {"skipped": skipped, "ticker": plan.ticker}


@router.post("/contributions/{cid}/restore")
async def restore_contribution(cid: int, db: Session = Depends(get_db)):
    """Return a dismissed buy to the pending bucket (undo a mistaken skip)."""
    c = _get_contribution_or_404(cid, db)
    if c.status != "dismissed":
        raise HTTPException(status_code=400, detail="Only skipped buys can be restored")
    c.status = "pending"
    db.commit()
    return {"message": "Buy restored to pending", "contribution": _contribution_dict(c)}


@router.post("/contributions/{cid}/undo")
async def undo_contribution(cid: int, db: Session = Depends(get_db)):
    """Reverse an applied buy exactly and return it to the pending bucket."""
    c = _get_contribution_or_404(cid, db)
    if c.status != "applied":
        raise HTTPException(status_code=400, detail="Only applied buys can be undone")
    holding = (
        db.query(Holding).filter(Holding.id == c.applied_holding_id).first()
        if c.applied_holding_id
        else None
    )
    note = None
    if holding is not None:
        new_shares, new_avg = dca_service.undo_from_holding(
            holding.shares or 0.0, holding.avg_cost or 0.0, c.shares, c.amount
        )
        holding.shares = new_shares
        holding.avg_cost = new_avg
    else:
        note = "Holding no longer exists; buy returned to pending without changing holdings."
    c.status = "pending"
    c.applied_holding_id = None
    db.commit()
    return {"message": note or "Buy undone", "contribution": _contribution_dict(c)}
