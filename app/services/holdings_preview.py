"""Prepare an inspect-only CSV result without database, AI or logging access."""

from __future__ import annotations

import hashlib

from app.services import holdings_csv


def prepare_preview(raw, filename, content_type, existing_tickers, validate_fn):
    """Use the import validator while keeping provider uncertainty explicit."""
    header, rows = holdings_csv.parse_import_upload(raw, filename, content_type, strict=True)
    unknown = holdings_csv.unrecognized_columns(header)
    if unknown:
        raise holdings_csv.ImportFileError(
            400, "Preview CSV accepts template columns only. Use the template or immediate import."
        )

    def validate(ticker):
        result = validate_fn(ticker)
        if not result.get("valid"):
            return {
                **result,
                "message": (
                    "Could not validate: symbol may be invalid or the provider unavailable."
                ),
            }
        return result

    report, _candidates = holdings_csv.process_import_rows(
        rows, existing_tickers, validate, include_values=True
    )
    counts = holdings_csv.summarize(report)
    return {
        "mode": "local",
        "input_digest": hashlib.sha256(raw).hexdigest(),
        "saved": False,
        "would_add": counts["added"],
        "skipped": counts["skipped"],
        "errors": counts["errors"],
        "rows": [
            {**row, "status": "would_add" if row["status"] == "added" else row["status"]}
            for row in report
        ],
    }
