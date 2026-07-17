"""HTTP adapter for the transactional DCA plan ledger."""

from datetime import date
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import DcaPlanCreate, DcaPlanUpdate
from app.services import dca_ledger, portfolio_lifecycle
from app.services.stock_service import get_daily_closes, validate_ticker_symbol

router = APIRouter(prefix="/api/dca", tags=["dca"])


def _ledger(db: Session) -> dca_ledger.DcaLedger:
    """Construct the ledger with explicit external seams for easy HTTP tests."""
    return dca_ledger.DcaLedger(
        db,
        ticker_validator=validate_ticker_symbol,
        price_history_loader=get_daily_closes,
        today=date.today,
    )


def _call(operation: Callable, *args, **kwargs):
    """Translate domain errors into stable HTTP responses."""
    try:
        return operation(*args, **kwargs)
    except (dca_ledger.DcaNotFoundError, portfolio_lifecycle.PortfolioNotFoundError) as exc:
        detail = getattr(exc, "detail", str(exc))
        raise HTTPException(status_code=404, detail=detail) from exc
    except (dca_ledger.DcaConflictError, dca_ledger.DcaValidationError) as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc


@router.post("/plans")
async def create_plan(
    data: DcaPlanCreate,
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    """Create a DCA plan and backfill past buys into the pending bucket."""
    return _call(
        _ledger(db).create_plan,
        portfolio_id=portfolio_id,
        ticker=data.ticker,
        amount=data.amount,
        frequency=data.frequency,
        start_date=data.start_date,
    )


@router.get("/plans")
async def list_plans(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """List all DCA plans and rolled-up bucket totals for a Portfolio."""
    return {"plans": _call(_ledger(db).list_plans, portfolio_id)}


@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: int,
    data: DcaPlanUpdate,
    db: Session = Depends(get_db),
):
    """Pause, resume, or resize a DCA plan."""
    plan = _call(
        _ledger(db).update_plan,
        plan_id,
        amount=data.amount,
        is_active=data.is_active,
    )
    return {"plan": plan}


@router.delete("/plans/{plan_id}")
async def delete_plan(plan_id: int, db: Session = Depends(get_db)):
    """Delete a plan and its bucket; already-applied holding changes remain."""
    return {"message": _call(_ledger(db).delete_plan, plan_id)}


@router.post("/run")
async def run_catchup(portfolio_id: int = 1, db: Session = Depends(get_db)):
    """Fill every active plan's missing scheduled buys idempotently."""
    return _call(_ledger(db).run_catchup, portfolio_id)


@router.get("/contributions")
async def list_contributions(
    portfolio_id: int = 1,
    status: str = Query("pending"),
    db: Session = Depends(get_db),
):
    """List a Portfolio's DCA buys, filtered by ledger state."""
    return {
        "contributions": _call(
            _ledger(db).list_contributions,
            portfolio_id,
            status,
        )
    }


@router.post("/contributions/{contribution_id}/apply")
async def apply_contribution(
    contribution_id: int,
    db: Session = Depends(get_db),
):
    """Apply one pending buy to its Portfolio holding."""
    return _call(_ledger(db).apply_contribution, contribution_id)


@router.post("/plans/{plan_id}/apply-pending")
async def apply_all_pending(plan_id: int, db: Session = Depends(get_db)):
    """Apply every pending buy in a plan."""
    return _call(_ledger(db).apply_all_pending, plan_id)


@router.post("/contributions/{contribution_id}/skip")
async def skip_contribution(
    contribution_id: int,
    db: Session = Depends(get_db),
):
    """Dismiss one pending buy without mutating a holding."""
    return _call(_ledger(db).skip_contribution, contribution_id)


@router.post("/plans/{plan_id}/skip-pending")
async def skip_all_pending(plan_id: int, db: Session = Depends(get_db)):
    """Dismiss every pending buy in a plan."""
    return _call(_ledger(db).skip_all_pending, plan_id)


@router.post("/contributions/{contribution_id}/restore")
async def restore_contribution(
    contribution_id: int,
    db: Session = Depends(get_db),
):
    """Return one dismissed buy to pending."""
    return _call(_ledger(db).restore_contribution, contribution_id)


@router.post("/contributions/{contribution_id}/undo")
async def undo_contribution(
    contribution_id: int,
    db: Session = Depends(get_db),
):
    """Reverse one applied buy exactly and return it to pending."""
    return _call(_ledger(db).undo_contribution, contribution_id)


@router.post("/plans/{plan_id}/undo-applied")
async def undo_all_applied(plan_id: int, db: Session = Depends(get_db)):
    """Reverse every applied buy in a plan."""
    return _call(_ledger(db).undo_all_applied, plan_id)
