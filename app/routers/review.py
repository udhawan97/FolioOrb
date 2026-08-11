"""HTTP surface for FolioOrb's local Review Orbit workflows."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import app_settings, paths
from app.database import get_db
from app.routers.deps import require_portfolio as _require_portfolio
from app.services import (
    backup_service,
    holdings_repository,
    portfolio_planning,
    portfolio_records,
    portfolio_review,
    update_installer,
)

router = APIRouter(prefix="/api/review", tags=["review"])


class ThesisReviewIn(BaseModel):
    notes: str = Field(default="", max_length=500)
    review_interval_days: int | None = Field(default=None, ge=7, le=730)


class RestoreIn(BaseModel):
    name: str


class TargetAssignmentIn(BaseModel):
    holding_id: int = Field(..., ge=1)
    target_weight_bps: int | None = Field(default=None, ge=0, le=10_000, strict=True)


class TargetSetIn(BaseModel):
    items: list[TargetAssignmentIn] = Field(default_factory=list, max_length=500)


class BuyRehearsalIn(BaseModel):
    holding_id: int = Field(..., ge=1)
    cash_usd: Decimal = Field(..., gt=0, le=portfolio_planning.MAX_REHEARSAL_CASH)


class AutomaticBackupIn(BaseModel):
    enabled: bool


def _domain_call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/trust")
def trust_center(portfolio_id: int = 1, db: Session = Depends(get_db)):
    _require_portfolio(portfolio_id, db)
    return portfolio_review.build_trust_center(db, portfolio_id)


@router.get("/inbox")
def review_inbox(portfolio_id: int = 1, db: Session = Depends(get_db)):
    _require_portfolio(portfolio_id, db)
    return portfolio_review.build_review_inbox(db, portfolio_id)


@router.get("/report")
def review_report(
    period: str = Query("month", pattern="^(month|quarter)$"),
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    _require_portfolio(portfolio_id, db)
    return _domain_call(portfolio_review.build_review_report, db, portfolio_id, period)


@router.get("/report/export")
def export_review_report(
    period: str = Query("month", pattern="^(month|quarter)$"),
    format: str = Query("html", pattern="^(html|csv)$"),  # pylint: disable=redefined-builtin
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    _require_portfolio(portfolio_id, db)
    report = _domain_call(portfolio_review.build_review_report, db, portfolio_id, period)
    stamp = report["period_end"]
    if format == "csv":
        content = portfolio_review.report_csv(report)
        media_type = "text/csv; charset=utf-8"
    else:
        content = portfolio_review.report_html(report)
        media_type = "text/html; charset=utf-8"
    filename = f"folioorb-{period}-review-{stamp}.{format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/watchlist")
def review_watchlist(portfolio_id: int = 1, db: Session = Depends(get_db)):
    _require_portfolio(portfolio_id, db)
    return {
        "portfolio_id": portfolio_id,
        "items": portfolio_review.watchlist_catalog(db, portfolio_id),
    }


@router.get("/plan")
def plan_portfolio(portfolio_id: int = 1, db: Session = Depends(get_db)):
    _require_portfolio(portfolio_id, db)
    return _domain_call(portfolio_planning.build_target_plan, db, portfolio_id)


@router.put("/plan/targets")
def replace_plan_targets(
    payload: TargetSetIn,
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    _require_portfolio(portfolio_id, db)
    assignments = [
        (item.holding_id, item.target_weight_bps) for item in payload.items
    ]
    return _domain_call(
        portfolio_planning.replace_targets, db, portfolio_id, assignments
    )


@router.post("/plan/rehearsal")
def rehearse_plan_buy(
    payload: BuyRehearsalIn,
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    _require_portfolio(portfolio_id, db)
    return _domain_call(
        portfolio_planning.rehearse_buy,
        db,
        portfolio_id,
        payload.holding_id,
        payload.cash_usd,
    )


@router.get("/overview")
def all_books_overview(db: Session = Depends(get_db)):
    return portfolio_planning.build_all_books_overview(db)


@router.get("/records/realized.csv")
def export_realized_records(
    year: int = Query(..., ge=portfolio_records.MIN_RECAP_YEAR),
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    _require_portfolio(portfolio_id, db)
    content = _domain_call(
        portfolio_records.build_realized_recap_csv, db, portfolio_id, year
    )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="folioorb-average-cost-recap-{year}-p{portfolio_id}.csv"'
            )
        },
    )


@router.get("/records/archive")
def export_portable_records(db: Session = Depends(get_db)):
    content = _domain_call(portfolio_records.build_portable_archive, db)
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="folioorb-portable-export.zip"'
        },
    )


@router.get("/compare")
def compare_watchlist(
    tickers: str = Query(..., min_length=3, max_length=40),
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    _require_portfolio(portfolio_id, db)
    selected = [ticker for ticker in tickers.split(",") if ticker.strip()]
    return _domain_call(
        portfolio_review.compare_watchlist, db, portfolio_id, selected
    )


@router.put("/thesis/{holding_id}")
def review_thesis(
    holding_id: int,
    payload: ThesisReviewIn,
    portfolio_id: int = 1,
    db: Session = Depends(get_db),
):
    _require_portfolio(portfolio_id, db)
    holding = holdings_repository.in_portfolio(
        db, portfolio_id, holding_id, active_only=True
    )
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    holding.notes = payload.notes.strip() or None
    holding.thesis_review_interval_days = payload.review_interval_days
    holding.thesis_reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(holding)
    return portfolio_review.thesis_state(holding)


@router.get("/backups")
def list_backups():
    settings = app_settings.load_settings()
    return {
        "items": backup_service.list_backups(),
        "pending_restore": settings.get("pending_db_restore"),
        "last_restore": settings.get("last_db_restore"),
        "protection": backup_service.backup_protection_status(),
    }


@router.post("/backups")
def create_backup():
    return _domain_call(backup_service.create_manual_backup)


@router.get("/backups/policy")
def get_backup_policy():
    return backup_service.backup_protection_status()


@router.put("/backups/policy")
def update_backup_policy(payload: AutomaticBackupIn):
    backup_service.set_auto_backup_enabled(payload.enabled)
    return backup_service.backup_protection_status()


@router.get("/backups/{name}/download")
def download_backup(name: str):
    path = _domain_call(backup_service.resolve_backup_name, name)
    if not path.exists() or not backup_service.verify_vault_backup(path):
        raise HTTPException(status_code=404, detail="Verified backup not found")
    return FileResponse(path, media_type="application/vnd.sqlite3", filename=path.name)


@router.post("/backups/restore")
def queue_restore(payload: RestoreIn):
    pending = _domain_call(backup_service.queue_restore, payload.name)
    will_quit = paths.is_frozen()
    if will_quit:
        update_installer.schedule_exit()
    return {
        "status": "queued",
        "pending": pending,
        "will_quit": will_quit,
        "message": (
            "Restore queued. FolioOrb will quit; reopen it to finish."
            if will_quit else
            "Restore queued. Stop and restart FolioOrb to finish."
        ),
    }
