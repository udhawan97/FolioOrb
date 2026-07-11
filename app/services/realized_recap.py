"""
Year-end realized-gains recap — group a portfolio's closed trades by calendar
year into a compact "what did I actually lock in this year?" summary.

Pure aggregation over stored ``RealizedTrade`` rows: no live quotes, no network,
no AI. The router queries the trades and hands them in, so this is trivially
unit-testable and can never lag or crash a request on external data.
"""
from __future__ import annotations


def _round2(value) -> float:
    return round(value or 0.0, 2)


def _empty_summary() -> dict:
    return {
        "realized_gain": 0.0,
        "proceeds": 0.0,
        "cost_basis": 0.0,
        "return_pct": None,
        "trade_count": 0,
        "tickers": 0,
        "winners": 0,
        "losers": 0,
    }


def build_realized_recap(trades, year: int | None = None) -> dict:
    """Summarize realized trades, bucketed by the calendar year of each sale.

    ``trades``: iterable of objects carrying ``ticker``, ``shares_sold``,
    ``sale_price``, ``avg_cost``, ``realized_gain``, and ``created_at`` (a
    ``datetime``). Rows without a ``created_at`` are skipped — they can't be
    dated into a year.

    ``year``: the calendar year to detail. Defaults to the most recent year
    that has any trades. An unknown year falls back to that default too, so the
    caller never has to pre-validate it. Returns zeros/empties when there are no
    dated trades at all.
    """
    by_year: dict[int, list] = {}
    for trade in trades:
        created = getattr(trade, "created_at", None)
        if created is None:
            continue
        by_year.setdefault(created.year, []).append(trade)

    years = sorted(by_year.keys(), reverse=True)
    if not years:
        return {
            "years": [],
            "year": None,
            "summary": _empty_summary(),
            "by_ticker": [],
            "best": None,
            "worst": None,
        }

    selected = year if year in by_year else years[0]
    rows = by_year[selected]

    per_ticker: dict[str, dict] = {}
    for trade in rows:
        item = per_ticker.setdefault(trade.ticker, {
            "ticker": trade.ticker,
            "shares_sold": 0.0,
            "proceeds": 0.0,
            "cost_basis": 0.0,
            "realized_gain": 0.0,
            "trade_count": 0,
        })
        shares = trade.shares_sold or 0.0
        item["shares_sold"] += shares
        item["proceeds"] += shares * (trade.sale_price or 0.0)
        item["cost_basis"] += shares * (trade.avg_cost or 0.0)
        item["realized_gain"] += trade.realized_gain or 0.0
        item["trade_count"] += 1

    by_ticker = []
    for item in per_ticker.values():
        item["return_pct"] = (
            round(item["realized_gain"] / item["cost_basis"] * 100, 2)
            if item["cost_basis"] > 0 else None
        )
        for key in ("shares_sold", "proceeds", "cost_basis", "realized_gain"):
            item[key] = _round2(item[key])
        by_ticker.append(item)
    # Sorted best-to-worst by realized P&L, so best = first, worst = last.
    by_ticker.sort(key=lambda i: i["realized_gain"], reverse=True)

    total_gain = _round2(sum(i["realized_gain"] for i in by_ticker))
    total_proceeds = _round2(sum(i["proceeds"] for i in by_ticker))
    total_cost = _round2(sum(i["cost_basis"] for i in by_ticker))
    winners = sum(1 for i in by_ticker if i["realized_gain"] > 0)
    losers = sum(1 for i in by_ticker if i["realized_gain"] < 0)

    return {
        "years": years,
        "year": selected,
        "summary": {
            "realized_gain": total_gain,
            "proceeds": total_proceeds,
            "cost_basis": total_cost,
            "return_pct": round(total_gain / total_cost * 100, 2) if total_cost > 0 else None,
            "trade_count": len(rows),
            "tickers": len(by_ticker),
            "winners": winners,
            "losers": losers,
        },
        # best only if there's an actual gainer; worst only if an actual loser.
        "best": by_ticker[0] if winners else None,
        "worst": by_ticker[-1] if losers else None,
        "by_ticker": by_ticker,
    }
