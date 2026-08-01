"""Return-series arithmetic shared by the analytics and projection modules.

Both modules turn a list of closes into daily log-returns and then annualise
them, and both had their own copy — byte-identical for `log_returns`, and the
same two formulas for the annualisation wrapped in different units and
fallbacks. The projection module's copy was the canonical one only by accident:
`portfolio_analytics` imported `TRADING_DAYS` *and the private*
`_portfolio_daily_returns` out of it, so a projection-shaped concern was
already leaking sideways into analytics through an underscore.

What lives here is the arithmetic with no policy attached: no rounding, no
percentage conversion, no floors, no defaults. Those differ between the two
callers on purpose — analytics reports percentages and falls back to zero,
while the projection needs decimals and a non-zero volatility floor so a
degenerate history can't collapse its growth cone to a line — so each keeps its
own thin wrapper and only the formulas are shared.
"""
from __future__ import annotations

import math

import numpy as np

# Trading days per year — the annualisation factor for both mean and variance.
TRADING_DAYS = 252

# Below this many observations the sample statistics are noise, not signal.
MIN_OBSERVATIONS = 5


def log_returns(closes: list[float]) -> np.ndarray:
    """Daily log-returns from a close series, with bad prices neutralised.

    A non-positive close — a delisted or halted ticker, or a data glitch —
    makes `log()` emit -inf/nan, which would silently contaminate every
    downstream statistic (annualised return and volatility, correlation, beta)
    with NaN. Such a day is treated as flat 0% instead of being allowed to
    propagate.
    """
    if len(closes) < 2:
        return np.array([], dtype=float)
    prices = np.asarray(closes, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        returns = np.diff(np.log(prices))
    return np.nan_to_num(returns, nan=0.0, posinf=0.0, neginf=0.0)


def annualized(daily_log_returns: np.ndarray) -> tuple[float, float] | None:
    """Annualised (mean, stdev) as decimals, or None on too little history.

    Returning None rather than a default is what lets the two callers keep
    their different fallbacks: there is no sensible shared answer for "not
    enough data", so this refuses to invent one.
    """
    if daily_log_returns.size < MIN_OBSERVATIONS:
        return None
    mu = float(np.mean(daily_log_returns)) * TRADING_DAYS
    sigma = float(np.std(daily_log_returns, ddof=1)) * math.sqrt(TRADING_DAYS)
    return mu, sigma


def weighted_daily_returns(
    holdings: list[tuple[str, float, list[tuple[str, float]]]],
) -> np.ndarray:
    """Weighted portfolio daily log-returns from per-holding close series.

    `holdings` is [(ticker, weight, [(date, close), ...]), ...]. Series are
    aligned on the union of their dates and forward-filled, so a holding that
    is missing a day contributes its previous close rather than a gap.
    """
    active = [(t, w, s) for t, w, s in holdings if w > 0 and len(s) >= 2]
    if not active:
        return np.array([], dtype=float)

    all_dates: set[str] = set()
    for _ticker, _weight, series in active:
        for day, _close in series:
            all_dates.add(day)
    dates = sorted(all_dates)
    if len(dates) < 2:
        return np.array([], dtype=float)

    date_idx = {day: i for i, day in enumerate(dates)}
    n = len(dates)
    port_rets = np.zeros(n - 1, dtype=float)
    # `active` only keeps weight > 0, so this is always positive.
    total_weight = sum(weight for _t, weight, _s in active)

    for _ticker, weight, series in active:
        closes = np.full(n, np.nan)
        for day, close in series:
            if day in date_idx:
                closes[date_idx[day]] = close
        for i in range(1, n):
            if np.isnan(closes[i]):
                closes[i] = closes[i - 1]
        if np.isnan(closes[0]):
            valid = np.where(~np.isnan(closes))[0]
            if valid.size:
                closes[: valid[0]] = closes[valid[0]]
        # A holding still carrying a gap or a non-positive close is dropped
        # rather than log()'d — that is what makes the plain np.log below safe.
        if np.any(np.isnan(closes)) or np.any(closes <= 0):
            continue
        port_rets += (weight / total_weight) * np.diff(np.log(closes))

    return port_rets
