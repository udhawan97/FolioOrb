"""Local-first portfolio review workflows behind the Review Orbit.

This module is deliberately orchestration-only: valuation remains owned by
``portfolio_valuation``, fees/income/overlap keep their existing financial
contracts, and market data enters through injectable loaders. The review layer
adds prioritisation, provenance and export shapes without inventing a second
set of portfolio math.
"""
from __future__ import annotations

import csv
import html as html_lib
import io
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.models import DcaContribution, DcaPlan, Holding
from app.services import portfolio_valuation
from app.services.dividend_income import compute_portfolio_income
from app.services.earnings_radar import get_earnings_events
from app.services.etf_overlap import compute_etf_overlap, overlap_between
from app.services.fund_costs import compute_fee_drag
from app.services.holding_intelligence import (
    get_holding_intelligence,
    intelligence_to_dict,
)
from app.services.security_type import SecurityType, classify_security
from app.services.stock_service import get_all_quotes, get_stock_data
from app.services.verdict_calibration import calibration_summary

QuoteListLoader = Callable[[list[str]], list[dict]]
QuoteLoader = Callable[[str], dict]
EarningsLoader = Callable[[list[str], int], list[dict]]

_QUALITY_RANK = {"complete": 0, "not_applicable": 0, "partial": 1, "unavailable": 2}
_PERIOD_DAYS = {"month": 31, "quarter": 92}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def thesis_state(holding: Holding, *, today: date | None = None) -> dict:
    """Return an honest cadence state for one holding thesis."""
    current = today or date.today()
    notes = str(holding.notes or "").strip()
    interval = holding.thesis_review_interval_days
    reviewed = holding.thesis_reviewed_at
    if not notes:
        status = "missing"
        due_date = None
    elif not interval:
        status = "uncadenced"
        due_date = None
    else:
        baseline = (reviewed or holding.added_at or datetime.combine(current, datetime.min.time()))
        due = baseline.date() + timedelta(days=int(interval))
        due_date = due.isoformat()
        status = (
            "overdue"
            if due < current
            else ("due_soon" if due <= current + timedelta(days=14) else "current")
        )
    return {
        "holding_id": holding.id,
        "ticker": str(holding.ticker),
        "notes": holding.notes,
        "status": status,
        "reviewed_at": _iso(reviewed),
        "review_interval_days": interval,
        "due_date": due_date,
        "is_watchlist": bool(holding.is_watchlist),
    }


def _active_holdings(db: Session, portfolio_id: int) -> list[Holding]:
    return (
        db.query(Holding)
        .filter(Holding.portfolio_id == portfolio_id, Holding.is_active.is_(True))
        .order_by(Holding.ticker.asc())
        .all()
    )


def _merged_quotes(
    holdings: list[Holding],
    valuation_rows: list[dict],
    *,
    quote_loader: QuoteListLoader = get_all_quotes,
) -> tuple[list[dict], set[str]]:
    """Merge full quotes over every active row, including an unpriced holding."""
    tickers = [str(row.ticker) for row in holdings]
    quotes = quote_loader(tickers) if tickers else []
    usable = {
        str(quote.get("ticker") or ""): quote
        for quote in quotes
        if not quote.get("error")
    }
    valued = {str(row["ticker"]): row for row in valuation_rows}
    merged = []
    for holding in holdings:
        ticker = str(holding.ticker)
        base = {
            "ticker": ticker,
            "id": holding.id,
            "name": holding.company_name or ticker,
            "shares": float(holding.shares or 0.0),
            "current_value": 0.0,
            "is_watchlist": bool(holding.is_watchlist),
        }
        merged.append({**base, **usable.get(ticker, {}), **valued.get(ticker, {})})
    return merged, set(usable)


def build_trust_center(
    db: Session,
    portfolio_id: int,
    *,
    quote_loader: QuoteListLoader = get_all_quotes,
) -> dict:
    """Unify freshness and coverage for the app's major financial surfaces."""
    holdings = _active_holdings(db, portfolio_id)
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    merged, quoted_tickers = _merged_quotes(
        holdings, valuation.holdings, quote_loader=quote_loader
    )
    fee = compute_fee_drag(merged)
    income = compute_portfolio_income(merged)
    overlap = compute_etf_overlap(merged)
    theses = [thesis_state(row) for row in holdings]
    history = portfolio_valuation.load_performance(db, portfolio_id, trade_limit=0).history
    latest_snapshot = history[-1]["date"] if history else None

    quote_expected = len(merged)
    metadata_tickers = {
        row["ticker"]
        for row in merged
        if row["ticker"] in quoted_tickers
        and any(
            row.get(key) not in (None, "")
            for key in ("quote_type", "security_type", "sector")
        )
    }
    usable_quote_count = len(metadata_tickers)
    if quote_expected == 0:
        quote_quality = "not_applicable"
    elif usable_quote_count == quote_expected:
        quote_quality = "complete"
    else:
        quote_quality = "partial" if usable_quote_count else "unavailable"
    thesis_covered = sum(bool(str(item.get("notes") or "").strip()) for item in theses)
    thesis_quality = (
        "complete"
        if thesis_covered == len(theses)
        else ("partial" if thesis_covered else "unavailable")
    )
    if not theses:
        thesis_quality = "not_applicable"

    areas = [
        {
            "key": "prices",
            "label": "Position prices",
            "quality": valuation.data_quality,
            "covered": valuation.priced_position_count,
            "expected": valuation.expected_position_count,
            "missing": list(valuation.missing_tickers),
            "source": "Yahoo Finance via the local market-data cache",
        },
        {
            "key": "fundamentals",
            "label": "Quote metadata",
            "quality": quote_quality,
            "covered": usable_quote_count,
            "expected": quote_expected,
            "missing": [
                row["ticker"] for row in merged
                if row["ticker"] not in metadata_tickers
            ],
            "source": "Yahoo Finance via yfinance",
        },
        {
            "key": "fees",
            "label": "Fund fees",
            "quality": (
                fee["data_quality"] if fee["coverage"]["fund_count"] else "not_applicable"
            ),
            "covered": fee["coverage"]["covered_count"],
            "expected": fee["coverage"]["fund_count"],
            "missing": fee["coverage"]["uncovered_tickers"],
            "source": "Provider expense-ratio fields",
        },
        {
            "key": "income",
            "label": "Dividend classification",
            "quality": quote_quality,
            "covered": usable_quote_count,
            "expected": quote_expected,
            "missing": [],
            "source": "Provider forward dividend fields; non-payers remain explicit",
        },
        {
            "key": "overlap",
            "label": "ETF overlap",
            "quality": (
                overlap["data_quality"] if overlap["etf_count"] else "not_applicable"
            ),
            "covered": len(overlap["covered_tickers"]),
            "expected": overlap["etf_count"],
            "missing": overlap["uncovered_tickers"],
            "source": "Published top-10 fund holdings only",
            "caveat": overlap["caveat"],
        },
        {
            "key": "theses",
            "label": "Holding theses",
            "quality": thesis_quality,
            "covered": thesis_covered,
            "expected": len(theses),
            "missing": [
                item["ticker"] for item in theses if item["status"] == "missing"
            ],
            "source": "Local holding notes",
        },
        {
            "key": "history",
            "label": "Stored daily history",
            "quality": "complete" if history else "unavailable",
            "covered": len(history),
            "expected": None,
            "missing": [],
            "source": "Local portfolio snapshots",
            "latest": latest_snapshot,
        },
    ]
    overall = max(areas, key=lambda area: _QUALITY_RANK[area["quality"]])["quality"]
    return {
        "portfolio_id": portfolio_id,
        "generated_at": _utc_now().isoformat(),
        "overall_quality": overall,
        "areas": areas,
        "snapshot_count": len(history),
        "latest_snapshot": latest_snapshot,
        "income_summary": {
            "payer_count": income["coverage"]["payer_count"],
            "non_payer_count": income["coverage"]["non_payer_count"],
        },
        "principle": "Missing data stays missing; it is never filled with zero.",
    }


def build_review_inbox(
    db: Session,
    portfolio_id: int,
    *,
    earnings_loader: EarningsLoader = get_earnings_events,
) -> dict:
    """Prioritise review work without making portfolio mutations."""
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    holdings = _active_holdings(db, portfolio_id)
    items: list[dict] = []

    for ticker in valuation.missing_tickers:
        items.append({
            "id": f"price-{ticker}",
            "type": "data",
            "tone": "urgent",
            "ticker": ticker,
            "title": f"{ticker} has no usable price",
            "detail": "Totals exclude this position until a valid quote is available.",
            "action": {"kind": "trust", "label": "Inspect coverage"},
        })

    pending = (
        db.query(DcaContribution)
        .join(DcaPlan, DcaContribution.plan_id == DcaPlan.id)
        .filter(
            DcaPlan.portfolio_id == portfolio_id,
            DcaContribution.status == "pending",
        )
        .count()
    )
    if pending:
        items.append({
            "id": "dca-pending",
            "type": "dca",
            "tone": "attention",
            "ticker": None,
            "title": f"{pending} simulated DCA buy{'s' if pending != 1 else ''} await review",
            "detail": "Nothing touches owned positions until you apply a buy.",
            "action": {"kind": "manage-dca", "label": "Open DCA ledger"},
        })

    thesis_rows = [thesis_state(holding) for holding in holdings]
    for thesis in thesis_rows:
        if thesis["status"] not in {"missing", "overdue", "due_soon"}:
            continue
        labels = {
            "missing": "needs a thesis",
            "overdue": "thesis review is overdue",
            "due_soon": "thesis review is due soon",
        }
        items.append({
            "id": f"thesis-{thesis['holding_id']}",
            "type": "thesis",
            "tone": "attention" if thesis["status"] != "due_soon" else "quiet",
            "ticker": thesis["ticker"],
            "title": f"{thesis['ticker']} {labels[thesis['status']]}",
            "detail": (
                f"Due {thesis['due_date']}" if thesis["due_date"]
                else "Add a reason to own or watch it, then choose a cadence."
            ),
            "action": {
                "kind": "thesis",
                "label": "Review thesis",
                "holding_id": thesis["holding_id"],
            },
        })

    events = earnings_loader([str(row.ticker) for row in holdings], 30)
    for event in events:
        items.append({
            "id": f"earnings-{event['ticker']}",
            "type": "event",
            "tone": "quiet",
            "ticker": event["ticker"],
            "title": f"{event['ticker']} earnings {event['label'].lower()}",
            "detail": f"Expected around {event['date']}; estimates remain provider-reported.",
            "action": {"kind": "holding", "label": "View holding"},
        })

    calibration = calibration_summary(db, portfolio_id)
    if calibration["total_snapshots"]:
        items.append({
            "id": "calibration",
            "type": "calibration",
            "tone": "quiet",
            "ticker": None,
            "title": f"{calibration['total_snapshots']} verdict snapshots are calibrating",
            "detail": "Forward-price backfill is still pending; no hit rate is claimed yet.",
            "action": {"kind": "report", "label": "Open review pack"},
        })

    tone_order = {"urgent": 0, "attention": 1, "quiet": 2}
    items.sort(key=lambda item: (tone_order[item["tone"]], item["id"]))
    return {
        "portfolio_id": portfolio_id,
        "generated_at": _utc_now().isoformat(),
        "count": len(items),
        "counts": {
            tone: sum(item["tone"] == tone for item in items)
            for tone in ("urgent", "attention", "quiet")
        },
        "items": items,
        "theses": thesis_rows,
        "valuation_quality": valuation.data_quality,
    }


def build_review_report(db: Session, portfolio_id: int, period: str) -> dict:
    """Create a period review pack from stored history plus one current valuation."""
    if period not in _PERIOD_DAYS:
        raise ValueError("period must be month or quarter")
    today = date.today()
    cutoff = today - timedelta(days=_PERIOD_DAYS[period])
    valuation = portfolio_valuation.evaluate(db, portfolio_id)
    performance = portfolio_valuation.load_performance(db, portfolio_id)
    within = [
        row for row in performance.history
        if row["date"] >= cutoff.isoformat()
    ]
    before_or_at_cutoff = [
        row for row in performance.history
        if row["date"] <= cutoff.isoformat()
    ]
    opening = before_or_at_cutoff[-1] if before_or_at_cutoff else (
        within[0] if within else None
    )
    trades = [
        row for row in performance.trades
        if row.get("date") and row["date"][:10] >= cutoff.isoformat()
    ]
    realized_period = round(sum(float(row["realized_gain"]) for row in trades), 2)
    closing_value = valuation.total_value
    value_change = (
        round(closing_value - float(opening["total_value"]), 2)
        if opening else None
    )
    theses = [thesis_state(row) for row in _active_holdings(db, portfolio_id)]
    attention = [
        item for item in theses
        if item["status"] in {"missing", "overdue", "due_soon"}
    ]
    movers = sorted(
        [
            {
                "ticker": row["ticker"],
                "total_return_pct": row["total_return_pct"],
                "unrealized_gain": row["unrealized_gain"],
            }
            for row in valuation.holdings
            if not row["is_watchlist"] and row["total_return_pct"] is not None
        ],
        key=lambda row: abs(float(row["unrealized_gain"])),
        reverse=True,
    )[:5]
    if opening is None:
        history_quality = "unavailable"
        history_gap_days = None
    else:
        history_gap_days = abs(
            (date.fromisoformat(opening["date"]) - cutoff).days
        )
        history_quality = "complete" if history_gap_days <= 3 else "partial"
    return {
        "portfolio_id": portfolio_id,
        "generated_at": _utc_now().isoformat(),
        "period": period,
        "period_start": cutoff.isoformat(),
        "period_end": today.isoformat(),
        "data_quality": {
            "valuation": valuation.data_quality,
            "history": history_quality,
            "missing_prices": list(valuation.missing_tickers),
        },
        "opening_snapshot": opening,
        "observed_start": opening["date"] if opening else None,
        "history_start_gap_days": history_gap_days,
        "snapshot_count": len(within),
        "current": {
            "total_value": closing_value,
            "total_cost_basis": valuation.total_cost_basis,
            "unrealized_gain": valuation.total_unrealized_gain,
            "realized_gain_all_time": valuation.realized_gain,
            "total_return": valuation.total_return,
            "total_return_pct": valuation.total_return_pct,
        },
        "period_activity": {
            "value_change": value_change,
            "value_change_caveat": (
                (
                    f"Measured from the stored {opening['date']} snapshot. "
                    if opening else
                    "No stored opening snapshot is available. "
                )
                + "Value change includes contributions and withdrawals; it is "
                "not a time-weighted investment return."
            ),
            "realized_gain": realized_period,
            "realized_trade_count": len(trades),
        },
        "movers": movers,
        "thesis_attention": attention,
        "disclaimer": (
            "Review material only. FolioOrb does not place trades or give "
            "financial advice."
        ),
    }


def report_csv(report: dict) -> str:
    """Flatten the stable report summary to Excel-friendly CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "metric", "value"])
    for key, value in report["current"].items():
        writer.writerow(["current", key, value])
    for key, value in report["period_activity"].items():
        writer.writerow(["period_activity", key, value])
    writer.writerow(["coverage", "valuation", report["data_quality"]["valuation"]])
    writer.writerow(["coverage", "history", report["data_quality"]["history"]])
    writer.writerow(["coverage", "observed_start", report["observed_start"]])
    for row in report["movers"]:
        writer.writerow(["mover", row["ticker"], row["total_return_pct"]])
    for row in report["thesis_attention"]:
        writer.writerow(["thesis_attention", row["ticker"], row["status"]])
    return "\ufeff" + output.getvalue()


def report_html(report: dict) -> str:
    """Create a self-contained, print-ready review document."""
    def esc(value) -> str:
        return html_lib.escape(str(value if value is not None else "Unavailable"))

    movers = "".join(
        f"<tr><td>{esc(row['ticker'])}</td><td>{esc(row['total_return_pct'])}%</td>"
        f"<td>${esc(row['unrealized_gain'])}</td></tr>"
        for row in report["movers"]
    ) or "<tr><td colspan='3'>No priced positions available.</td></tr>"
    theses = "".join(
        f"<li><strong>{esc(row['ticker'])}</strong> — {esc(row['status'])}</li>"
        for row in report["thesis_attention"]
    ) or "<li>No theses need attention.</li>"
    current = report["current"]
    activity = report["period_activity"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>FolioOrb {esc(report['period'])} review</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;color:#17202b;max-width:860px;
margin:48px auto;padding:0 24px}}
h1{{font-size:30px;margin-bottom:4px}}
.muted{{color:#687180}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:28px 0}}
.metric{{border:1px solid #d9dee7;border-radius:12px;padding:16px}}
.metric b{{display:block;font-size:20px;margin-top:6px}}
table{{width:100%;border-collapse:collapse}}
th,td{{text-align:left;padding:10px;border-bottom:1px solid #e5e8ee}}
.notice{{background:#f4f6f9;border-radius:12px;padding:14px;margin:22px 0}}
@media print{{body{{margin:0;max-width:none}}}}
</style></head><body>
<p class="muted">FolioOrb Review Pack · {esc(report['period_start'])}
to {esc(report['period_end'])}</p>
<h1>Your portfolio, reviewed</h1>
<p class="muted">Generated locally at {esc(report['generated_at'])}.
Valuation coverage: {esc(report['data_quality']['valuation'])}.</p>
<section class="grid">
<div class="metric">Current value<b>${esc(current['total_value'])}</b></div>
<div class="metric">Total return
<b>${esc(current['total_return'])} · {esc(current['total_return_pct'])}%</b></div>
<div class="metric">Period realized P&amp;L<b>${esc(activity['realized_gain'])}</b></div>
</section>
<div class="notice"><strong>Value change:</strong> {esc(activity['value_change'])}.
{esc(activity['value_change_caveat'])}</div>
<h2>Largest current P&amp;L contributors</h2>
<table><thead><tr><th>Ticker</th><th>Total return</th>
<th>Unrealized P&amp;L</th></tr></thead><tbody>{movers}</tbody></table>
<h2>Thesis attention</h2><ul>{theses}</ul>
<p class="muted">{esc(report['disclaimer'])}</p>
</body></html>"""


def watchlist_catalog(
    db: Session,
    portfolio_id: int,
    *,
    quote_loader: QuoteListLoader = get_all_quotes,
) -> list[dict]:
    """Research-mode tickers available for type-safe comparison."""
    rows = [
        row for row in _active_holdings(db, portfolio_id)
        if row.is_watchlist
    ]
    tickers = [str(row.ticker) for row in rows]
    quotes = {
        str(item.get("ticker") or ""): item
        for item in (quote_loader(tickers) if tickers else [])
    }
    return [
        {
            "holding_id": row.id,
            "ticker": str(row.ticker),
            "name": quotes.get(str(row.ticker), {}).get("name") or row.company_name or row.ticker,
            "security_type": classify_security(
                str(row.ticker), quotes.get(str(row.ticker))
            ).value,
            "thesis": thesis_state(row),
        }
        for row in rows
    ]


def compare_watchlist(
    db: Session,
    portfolio_id: int,
    tickers: list[str],
    *,
    quote_loader: QuoteLoader = get_stock_data,
) -> dict:
    """Compare two or three owned research tickers using type-relevant fields."""
    selected = [str(value).strip().upper() for value in tickers]
    if len(selected) not in {2, 3} or len(set(selected)) != len(selected):
        raise ValueError("Choose two or three different research tickers")
    rows = (
        db.query(Holding)
        .filter(
            Holding.portfolio_id == portfolio_id,
            Holding.is_active.is_(True),
            Holding.is_watchlist.is_(True),
            Holding.ticker.in_(selected),
        )
        .all()
    )
    by_ticker = {str(row.ticker): row for row in rows}
    missing = [ticker for ticker in selected if ticker not in by_ticker]
    if missing:
        raise ValueError(
            f"Compare is limited to research-mode tickers: {', '.join(missing)}"
        )

    quotes = {ticker: quote_loader(ticker) for ticker in selected}
    kinds = {
        classify_security(ticker, quotes[ticker])
        for ticker in selected
    }
    if len(kinds) != 1 or next(iter(kinds)) not in {SecurityType.STOCK, SecurityType.ETF}:
        raise ValueError("Compare stocks with stocks or ETFs with ETFs")
    kind = next(iter(kinds))

    items = []
    intelligences = {}
    for ticker in selected:
        quote = quotes[ticker]
        intel = intelligence_to_dict(get_holding_intelligence(ticker, quote))
        intelligences[ticker] = intel
        common = {
            "ticker": ticker,
            "name": quote.get("name") or ticker,
            "current_price": quote.get("current_price"),
            "day_change_pct": quote.get("day_change_pct"),
            "fifty_two_week_high": quote.get("fifty_two_week_high"),
            "fifty_two_week_low": quote.get("fifty_two_week_low"),
            "thesis": thesis_state(by_ticker[ticker]),
            "data_quality": "unavailable" if quote.get("error") else "live",
        }
        if kind is SecurityType.STOCK:
            metrics = {
                "market_cap": quote.get("market_cap"),
                "pe_ratio": quote.get("pe_ratio"),
                "forward_pe": quote.get("forward_pe"),
                "revenue_growth": quote.get("revenue_growth"),
                "gross_margin": quote.get("gross_margin"),
                "operating_margin": quote.get("operating_margin"),
                "fcf_yield": quote.get("fcf_yield"),
                "dividend_yield": quote.get("dividend_yield"),
            }
        else:
            metrics = {
                "aum": quote.get("aum"),
                "expense_ratio": quote.get("expense_ratio") or intel.get("expense_ratio"),
                "holdings_count": quote.get("holdings_count"),
                "category": quote.get("sector"),
                "concentration": intel.get("concentration_label"),
                "top_holdings": intel.get("top_holdings", [])[:5],
            }
        items.append({**common, "metrics": metrics})

    overlap = None
    if kind is SecurityType.ETF and len(selected) == 2:
        left = {
            row["ticker"]: float(row["weight"])
            for row in intelligences[selected[0]]["top_holdings"]
        }
        right = {
            row["ticker"]: float(row["weight"])
            for row in intelligences[selected[1]]["top_holdings"]
        }
        overlap = {
            **overlap_between(left, right),
            "basis": "published_top_holdings",
            "caveat": "A floor based only on the published top holdings.",
        }
    return {
        "portfolio_id": portfolio_id,
        "generated_at": _utc_now().isoformat(),
        "security_type": kind.value,
        "items": items,
        "overlap": overlap,
        "source": "Yahoo Finance via yfinance plus FolioOrb's local fund metadata",
    }
