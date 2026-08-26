"""Explicit, backup-first recovery for legacy duplicate active holdings.

Schema v7 refuses to guess which financial row should remain active. The frozen
desktop shell uses this module before normal application startup: it presents
every conflicting row, requires one keep decision per normalized ticker, makes
a verified SQLite backup, and then archives only the rejected rows. Archiving
does not create a realized trade or alter shares, cost basis, notes, or history.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class DuplicateResolutionError(RuntimeError):
    """The requested duplicate resolution was incomplete, stale, or unsafe."""

    def __init__(self, message: str, *, backup_name: str | None = None):
        super().__init__(message)
        self.backup_name = backup_name


def _optional_column(columns: set[str], name: str) -> str:
    return f"h.{name}" if name in columns else f"NULL AS {name}"


def _groups(connection: sqlite3.Connection) -> list[dict]:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='holdings'"
    ).fetchone()
    if table is None:
        return []
    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(holdings)")
    }
    required = {"id", "portfolio_id", "ticker", "is_active"}
    if not required.issubset(columns):
        raise DuplicateResolutionError("The holdings table is missing required fields.")

    selected = ", ".join(
        [
            "h.id",
            "h.portfolio_id",
            "h.ticker",
            _optional_column(columns, "shares"),
            _optional_column(columns, "avg_cost"),
            _optional_column(columns, "is_watchlist"),
            _optional_column(columns, "hold_class"),
            _optional_column(columns, "notes"),
            _optional_column(columns, "company_name"),
            _optional_column(columns, "thesis_reviewed_at"),
            _optional_column(columns, "thesis_review_interval_days"),
            _optional_column(columns, "target_weight_bps"),
            _optional_column(columns, "added_at"),
        ]
    )
    rows = connection.execute(
        f"SELECT {selected} FROM holdings AS h "  # noqa: S608 -- fixed identifiers only
        "JOIN ("
        " SELECT portfolio_id, UPPER(TRIM(ticker)) AS normalized_ticker"
        " FROM holdings WHERE is_active = 1"
        " GROUP BY portfolio_id, UPPER(TRIM(ticker)) HAVING COUNT(*) > 1"
        ") AS conflicts"
        " ON conflicts.portfolio_id = h.portfolio_id"
        " AND conflicts.normalized_ticker = UPPER(TRIM(h.ticker))"
        " WHERE h.is_active = 1"
        " ORDER BY h.portfolio_id, conflicts.normalized_ticker, h.id"
    ).fetchall()

    grouped: dict[tuple[int, str], dict] = {}
    for row in rows:
        portfolio_id = int(row[1])
        ticker = str(row[2] or "").strip().upper()
        group = grouped.setdefault(
            (portfolio_id, ticker),
            {"portfolio_id": portfolio_id, "ticker": ticker, "rows": []},
        )
        group["rows"].append(
            {
                "id": int(row[0]),
                "stored_ticker": str(row[2] or ""),
                "shares": row[3],
                "avg_cost": row[4],
                "is_watchlist": bool(row[5]) if row[5] is not None else None,
                "hold_class": row[6],
                "notes": row[7],
                "company_name": row[8],
                "thesis_reviewed_at": row[9],
                "thesis_review_interval_days": row[10],
                "target_weight_bps": row[11],
                "added_at": row[12],
            }
        )
    return list(grouped.values())


def list_duplicate_groups(database_path: Path) -> list[dict]:
    """Read the current conflict inventory without creating the database."""
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        return []
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        return _groups(connection)
    finally:
        connection.close()


def _decision_map(decisions: list[dict]) -> dict[tuple[int, str], int]:
    selected: dict[tuple[int, str], int] = {}
    for decision in decisions:
        try:
            key = (
                int(decision["portfolio_id"]),
                str(decision["ticker"]).strip().upper(),
            )
            keep_id = int(decision["keep_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DuplicateResolutionError("Every conflict needs one valid choice.") from exc
        if key in selected:
            raise DuplicateResolutionError("Each conflict may be resolved only once.")
        selected[key] = keep_id
    return selected


def _inventory_signature(groups: list[dict]) -> dict[tuple[int, str], tuple[tuple, ...]]:
    """Bind a decision to every financial/workflow value shown in the window."""
    return {
        (int(group["portfolio_id"]), str(group["ticker"])): tuple(
            (
                int(row["id"]),
                str(row.get("stored_ticker") or ""),
                row.get("shares"),
                row.get("avg_cost"),
                row.get("is_watchlist"),
                row.get("hold_class"),
                row.get("notes"),
                row.get("company_name"),
                row.get("thesis_reviewed_at"),
                row.get("thesis_review_interval_days"),
                row.get("target_weight_bps"),
                row.get("added_at"),
            )
            for row in group["rows"]
        )
        for group in groups
    }


def resolve_duplicates(
    database_path: Path,
    data_root: Path,
    decisions: list[dict],
    *,
    displayed_groups: list[dict] | None = None,
) -> dict:
    """Archive rejected duplicate rows after a verified, explicit keep decision."""
    database = Path(database_path).expanduser().resolve()
    root = Path(data_root).expanduser().resolve()
    try:
        database.relative_to(root)
    except ValueError as exc:
        raise DuplicateResolutionError("The database is outside the active profile.") from exc

    initial = list_duplicate_groups(database)
    if not initial:
        raise DuplicateResolutionError("No active holding duplicates remain.")
    displayed = displayed_groups if displayed_groups is not None else initial
    expected = _inventory_signature(displayed)
    current = _inventory_signature(initial)
    if current != expected:
        raise DuplicateResolutionError(
            "Holdings changed after the choices were shown. Close and retry."
        )
    selected = _decision_map(decisions)
    if set(selected) != set(expected):
        raise DuplicateResolutionError("Choose one row to keep for every listed ticker.")
    if any(selected[key] not in {row[0] for row in rows} for key, rows in expected.items()):
        raise DuplicateResolutionError("A selected holding is not part of its conflict.")

    connection = sqlite3.connect(database, timeout=5, isolation_level=None)
    archived = 0
    backup = None
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        # Hold SQLite's cross-process writer reservation across the second
        # preflight, verified backup, and archive transaction. An older
        # FolioOrb process can finish a write before this lock is acquired, but
        # then the fresh signature below detects it. No writer can slip in
        # after the signature and before the archive commits.
        connection.execute("BEGIN IMMEDIATE")
        fresh = _inventory_signature(_groups(connection))
        if fresh != expected:
            raise DuplicateResolutionError(
                "Holdings changed after the choices were shown. Close and retry."
            )

        from app.services import backup_service

        backup = backup_service.create_verified_backup(
            label="pre-duplicate-resolution",
            source_db=database,
            dest_dir=root / backup_service.BACKUP_DIRNAME,
            require_vault_schema=True,
        )
        for (portfolio_id, ticker), keep_id in selected.items():
            cursor = connection.execute(
                "UPDATE holdings SET is_active = 0 "
                "WHERE portfolio_id = ? AND is_active = 1 "
                "AND UPPER(TRIM(ticker)) = ? AND id <> ?",
                (portfolio_id, ticker, keep_id),
            )
            archived += int(cursor.rowcount)
        if _groups(connection):
            raise DuplicateResolutionError("Duplicate holdings remain; no changes committed.")
        connection.commit()
    except Exception as exc:
        connection.rollback()
        backup_name = backup.database.name if backup is not None else None
        if isinstance(exc, DuplicateResolutionError):
            if exc.backup_name:
                raise
            raise DuplicateResolutionError(
                str(exc), backup_name=backup_name
            ) from exc
        raise DuplicateResolutionError(
            str(exc) or type(exc).__name__, backup_name=backup_name
        ) from exc
    finally:
        connection.close()

    return {"archived": archived, "backup": backup.database.name}
