"""Seed a throwaway SQLite database with a safe demo portfolio for screenshots.

Run against one TEMP profile only (set both FOLIOORB_DATA_DIR and DATABASE_URL).
The data here is deliberately fictional — public tickers with invented share counts
and cost bases — so nothing personal is ever captured in a landing-page screenshot.

Usage:
    FOLIOORB_DATA_DIR="$TMP_DIR/data" \
      DATABASE_URL="sqlite:///$TMP_DIR/data/demo.db" \
      python docs-site/scripts/seed_demo.py
"""

import os
import sys

# Make the repo root importable when run from anywhere.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# A fresh, demo-only portfolio: one core ETF, one mega-cap stock, one watchlist item.
DEMO_HOLDINGS = [
    # ticker, shares, avg_cost, is_watchlist, hold_class, target_weight_bps
    ("VOO", 18.0, 452.10, False, "anchor", 5500),
    ("MSFT", 22.0, 396.40, False, "auto", 3000),
    ("SCHD", 60.0, 27.85, False, "auto", 1500),
    ("NVDA", 0.0, 0.0, True, "auto", None),
]


def main() -> int:
    # Import after sys.path is set so the app package resolves.
    from app.database import SessionLocal, engine
    from app import models

    models.Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        # Wipe any prior rows so the seed is deterministic and repeatable.
        db.query(models.Holding).delete()
        db.query(models.Portfolio).delete()
        db.flush()

        portfolio = models.Portfolio(
            id=1, name="Demo Portfolio", description="Demo data only — not a real portfolio"
        )
        db.add(portfolio)
        db.flush()

        for ticker, shares, avg_cost, is_watchlist, hold_class, target_bps in DEMO_HOLDINGS:
            db.add(
                models.Holding(
                    portfolio_id=portfolio.id,
                    ticker=ticker,
                    shares=shares,
                    avg_cost=avg_cost,
                    is_watchlist=is_watchlist,
                    hold_class=hold_class,
                    target_weight_bps=target_bps,
                    is_active=True,
                )
            )

        long_horizon = models.Portfolio(
            id=2, name="Long Horizon", description="Second fictional book for demo data"
        )
        db.add(long_horizon)
        db.flush()
        db.add(
            models.Holding(
                portfolio_id=long_horizon.id,
                ticker="VTI",
                shares=14.0,
                avg_cost=241.30,
                is_watchlist=False,
                hold_class="anchor",
                target_weight_bps=10_000,
                is_active=True,
            )
        )
        db.commit()

    print(f"Seeded two demo portfolios with {len(DEMO_HOLDINGS) + 1} holdings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
