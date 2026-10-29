"""Bounded, process-local reviewed imports and read-only uncertain-outcome comparison."""
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import threading
import time

from sqlalchemy.exc import OperationalError

from app.models import Holding, Portfolio
from app.schemas import HoldingCreate
from app.services import (
    database_generation, holdings_csv, holdings_repository, portfolio_valuation,
    write_serialization,
)

TTL_SECONDS = 15 * 60
MAX_PREVIEWS = 16
FIELDS = ("ticker", "shares", "avg_cost", "is_watchlist", "hold_class", "notes",
          "thesis_review_interval_days")
FINGERPRINT_FIELDS = ("id", *FIELDS, "is_active", "thesis_reviewed_at", "target_weight_bps",
                      "added_at")


class ConfirmationError(Exception):
    """Public failure details contain no tokens or financial row values."""
    def __init__(self, status, code, message, record=None):
        super().__init__(message)
        self.status = status
        self.detail = {"code": code, "message": message}
        if record is not None:
            self.detail.update(saved=False, not_executed=True,
                               portfolio_id=record["portfolio"]["id"],
                               normalized_digest=record.get("normalized_digest"),
                               reviewed_rows=record.get("reviewed_rows", []))


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False,
                      default=lambda item: item.isoformat())


def proposal_digest(rows):
    return hashlib.sha256(_json({"mode": "local", "rows": rows}).encode()).hexdigest()


def persisted_values(create):
    """Make the existing ORM defaults explicit before the user reviews them."""
    values = create.model_dump(include=set(FIELDS))
    values["shares"] = create.shares or 0.0
    values["avg_cost"] = create.avg_cost if create.avg_cost is not None else 0.0
    values["is_watchlist"] = create.is_watchlist or False
    values["hold_class"] = create.hold_class or "auto"
    return values


def _values(holding, fields=FIELDS):
    return {field: getattr(holding, field) for field in fields}


def _read_state(db, portfolio_id):
    with db.no_autoflush:
        portfolio = db.get(Portfolio, portfolio_id)
        if portfolio is None:
            return None, [], None
        identity = {field: getattr(portfolio, field) for field in
                    ("id", "name", "description", "created_at", "updated_at")}
        holdings = holdings_repository.active(db, portfolio_id)
        payload = {"portfolio": identity,
                   "holdings": [_values(h, FINGERPRINT_FIELDS) for h in holdings]}
        fingerprint = hashlib.sha256(_json(payload).encode()).hexdigest()
        return identity, holdings, fingerprint


class PreviewStore:
    """Capabilities require consume/replay transitions, unlike a network TTL cache."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.pending = OrderedDict()
        self.receipts = OrderedDict()
        self._lock = threading.RLock()
        self._engine = None

    def _prune(self):
        now = self.clock()
        for entries in (self.pending, self.receipts):
            for token, record in list(entries.items()):
                if record["deadline"] <= now:
                    entries.pop(token)
            while len(entries) > MAX_PREVIEWS:
                entries.popitem(last=False)

    @contextmanager
    def _context(self, db):
        with database_generation.guard(), self._lock:
            engine = db.get_bind().engine
            try:
                current = database_generation.identity(engine)
                if (getattr(engine, "_folio_csv_blocked", False)
                        or database_generation.origin(engine) != current):
                    raise OSError("Database generation changed")
            except OSError as exc:
                setattr(engine, "_folio_csv_blocked", True)
                self.pending.clear()
                self.receipts.clear()
                raise ConfirmationError(
                    503, "generation", "Restart FolioOrb after database replacement or restore, "
                    "then reconcile the outcome."
                ) from exc
            if self._engine is not engine:
                self.pending.clear()
                self.receipts.clear()
                self._engine = engine
            yield current

    def discard(self, token):
        with self._lock:
            self.pending.pop(token, None)

    def revoke_portfolio(self, portfolio_id):
        with self._lock:
            for entries in (self.pending, self.receipts):
                for token, record in list(entries.items()):
                    if record["portfolio"]["id"] == portfolio_id:
                        entries.pop(token)

    def reserve(self, db, portfolio_id):
        """Reserve before external work, so lifecycle revocation includes preparations."""
        with self._context(db) as generation:
            self._prune()
            try:
                portfolio, holdings, fingerprint = _read_state(db, portfolio_id)
                if portfolio is None:
                    raise ConfirmationError(404, "missing", "Portfolio not found")
                existing = {str(h.ticker).strip().upper() for h in holdings}
            except (TypeError, ValueError) as exc:
                raise ConfirmationError(503, "unknown", "Current financial state cannot be "
                                        "verified. Inspect the selected portfolio.") from exc
            finally:
                db.rollback()
            token = secrets.token_urlsafe(32)
            self.pending[token] = {"state": "preparing", "portfolio": portfolio,
                                   "fingerprint": fingerprint, "generation": generation,
                                   "deadline": self.clock() + TTL_SECONDS,
                                   "snapshot_at": datetime.now(timezone.utc).isoformat()}
            self._prune()
            return token, existing

    def issue(self, db, token, prepared):
        with self._context(db) as generation:
            self._prune()
            record = self.pending.get(token)
            if record is None or record["state"] != "preparing":
                raise ConfirmationError(409, "stale", "Preview changed while validation ran. "
                                        "Choose the file again for a fresh preview.")
            if record["generation"] != generation:
                self.discard(token)
                raise ConfirmationError(409, "stale", "Database changed; preview again.")
            report = deepcopy(prepared)
            inputs, proposals = [], []
            for row in report["rows"]:
                if row["status"] == "would_add":
                    create = HoldingCreate(**row["values"])
                    values = persisted_values(create)
                    inputs.append(create.model_dump())
                    proposals.append({"row": row["row"], "values": values})
                    row["proposed_values"] = values
            report.update(portfolio_id=record["portfolio"]["id"],
                          portfolio={k: record["portfolio"][k] for k in ("id", "name")},
                          snapshot_at=record["snapshot_at"],
                          proposal_json=_json({"mode": "local", "rows": proposals}),
                          normalized_digest=proposal_digest(proposals),
                          reviewed_rows=[row["row"] for row in proposals])
            record.update(state="pending", report=deepcopy(report), inputs=inputs,
                          proposals=proposals, normalized_digest=report["normalized_digest"],
                          reviewed_rows=report["reviewed_rows"])
            if not proposals:
                self.discard(token)
                report["confirmation"] = None
            else:
                remaining = max(0, record["deadline"] - self.clock())
                report["confirmation"] = {
                    "token": token,
                    "expires_at": (datetime.now(timezone.utc)
                                   + timedelta(seconds=remaining)).isoformat(),
                }
            return deepcopy(report)

    def confirm(self, db, portfolio_id, token, normalized_digest):
        with self._context(db):
            pending = self.pending.get(token)
            self._prune()
            if pending and pending["deadline"] <= self.clock():
                raise ConfirmationError(410, "expired", "Preview expired; review a fresh CSV.",
                                        pending)
            receipt = self.receipts.get(token)
            if (receipt is not None and receipt["portfolio"]["id"] == portfolio_id
                    and receipt["result"]["normalized_digest"] == normalized_digest):
                return deepcopy(receipt["result"])
            record = self.pending.get(token)
            if record is None or record["state"] != "pending":
                raise ConfirmationError(409, "reconcile", "Outcome needs reconciliation. "
                                        "Do not repeat the import automatically.")
            if record["portfolio"]["id"] != portfolio_id:
                raise ConfirmationError(409, "scope", "Preview belongs to another portfolio.")
            try:
                write_serialization.begin_financial_write(db)
            except OperationalError as exc:
                db.rollback()
                if "locked" in str(exc.orig).lower() or "busy" in str(exc.orig).lower():
                    raise ConfirmationError(
                        503, "busy", "Database busy; no confirmation was executed. "
                        "You may retry explicitly.", record
                    ) from exc
                self.discard(token)
                raise ConfirmationError(503, "reconcile", "Current outcome cannot be verified. "
                                        "Refresh and compare reviewed records.") from exc
            try:
                with self._context(db):
                    pass  # generation can change during an external writer's reservation wait
                db.expire_all()
                if record["deadline"] <= self.clock():
                    self.discard(token)
                    raise ConfirmationError(410, "expired", "Preview expired while waiting. "
                                            "Review a fresh CSV.", record)
                _portfolio, _holdings, fingerprint = _read_state(db, portfolio_id)
                rebuilt = [{"row": row["row"], "values": persisted_values(HoldingCreate(**values))}
                           for row, values in zip(record["proposals"], record["inputs"])]
                if (normalized_digest != record["normalized_digest"]
                        or fingerprint != record["fingerprint"] or rebuilt != record["proposals"]
                        or proposal_digest(rebuilt) != record["normalized_digest"]):
                    self.discard(token)
                    raise ConfirmationError(409, "stale", "Portfolio or reviewed values changed. "
                                            "Nothing confirmed; review a fresh CSV.", record)
                # A failed commit acknowledgement may follow a real commit. Revoke before writes.
                self.discard(token)
                result = self._save(db, record)
            except ConfirmationError:
                db.rollback()
                raise
            except Exception as exc:
                db.rollback()
                self.discard(token)
                raise ConfirmationError(
                    409, "reconcile", "Outcome needs reconciliation. Refresh and compare "
                    "reviewed records; do not retry."
                ) from exc
            self.receipts[token] = {"deadline": self.clock() + TTL_SECONDS,
                                    "portfolio": record["portfolio"], "result": deepcopy(result)}
            self._prune()
            return result

    def _save(self, db, record):
        additions = [Holding(portfolio_id=record["portfolio"]["id"], **row["values"])
                     for row in record["proposals"]]
        db.add_all(additions)
        db.flush()
        for holding, row in zip(additions, record["proposals"]):
            db.refresh(holding)
            if _values(holding) != row["values"]:
                raise ValueError("Persisted fields differ from reviewed values")
        portfolio_valuation.validate_stored_financial_totals(db, record["portfolio"]["id"])
        with self._context(db):
            pass  # fail closed on an observed file replacement before commit
        result = deepcopy(record["report"])
        result.pop("would_add")
        result.update(saved=True, added=len(additions),
                      inserted_ids=[h.id for h in additions])
        for row in result["rows"]:
            if row["status"] == "would_add":
                row["status"] = "added"
        db.commit()
        return result

    def compare(self, db, portfolio_id, expected, metadata):
        """A matching record proves current fields, not who created the record."""
        with self._context(db):
            # Fence a delayed original POST before comparing: either it already committed
            # under this guard, or its matching capability can no longer execute afterward.
            for token, record in list(self.pending.items()):
                if (record["portfolio"]["id"] == portfolio_id
                        and record.get("normalized_digest") == metadata.normalized_digest
                        and record.get("report", {}).get("input_digest") == metadata.input_digest):
                    self.pending.pop(token)
            try:
                db.expire_all()
                if db.get(Portfolio, portfolio_id) is None:
                    raise ConfirmationError(404, "missing", "Portfolio not found; outcome unknown.")
                current = holdings_repository.active(db, portfolio_id)
                rows = []
                for reviewed in expected:
                    matches = [h for h in current if str(h.ticker).strip().upper()
                               == reviewed["values"]["ticker"]]
                    actual = _values(matches[0]) if len(matches) == 1 else None
                    status = "matching" if actual == reviewed["values"] else "mismatching"
                    reason = "No active holding" if not matches else "Compare all fields"
                    try:
                        _json(actual)
                    except (ValueError, TypeError):
                        actual = None
                        status, reason = "unknown", "Stored fields cannot be verified"
                    if len(matches) > 1:
                        status, reason = "unknown", "Multiple active records cannot be reconciled"
                    rows.append({"row": reviewed["row"], "status": status,
                                 "expected": reviewed["values"], "current": actual,
                                 "reason": reason})
                return {"portfolio_id": portfolio_id, "saved": False, "rows": rows,
                        "input_digest": metadata.input_digest,
                        "normalized_digest": metadata.normalized_digest,
                        **{status: sum(row["status"] == status for row in rows)
                           for status in ("matching", "mismatching", "unknown")}}
            finally:
                db.rollback()


def reviewed_rows(raw, filename, content_type, manifest):
    """Rehydrate reviewed fields for comparison only; never validate with a provider."""
    if hashlib.sha256(raw).hexdigest() != manifest.input_digest:
        raise ConfirmationError(400, "file", "Choose the original reviewed CSV file.")
    _header, rows = holdings_csv.parse_import_upload(raw, filename, content_type, strict=True)
    selected = []
    for row_number in manifest.reviewed_rows:
        if row_number - 2 >= len(rows):
            raise ConfirmationError(
                400, "manifest", "Reviewed row metadata does not match the CSV."
            )
        create = HoldingCreate(**holdings_csv.strict_row_to_create_kwargs(rows[row_number - 2]))
        selected.append({"row": row_number, "values": persisted_values(create)})
    if proposal_digest(selected) != manifest.normalized_digest:
        raise ConfirmationError(400, "manifest", "Reviewed values could not be verified.")
    return selected


store = PreviewStore()
