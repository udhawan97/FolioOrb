from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


# Each class below maps to one table in the SQLite database.
# SQLAlchemy reads these class definitions and creates the matching tables automatically.


class Portfolio(Base):
    """A named portfolio that groups a set of stock holdings."""
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, default="My Portfolio")
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # One portfolio contains many holdings.
    # cascade="all, delete-orphan" means deleting a portfolio also deletes its holdings.
    holdings = relationship("Holding", back_populates="portfolio", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Portfolio {self.name}>"


class Holding(Base):
    """
    A single stock position inside a portfolio.
    Tracks how many shares were bought and at what average price.
    """
    __tablename__ = "holdings"
    # Every dashboard read filters on (portfolio_id, is_active).
    __table_args__ = (
        Index("ix_holdings_portfolio_active", "portfolio_id", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    ticker = Column(String(10), nullable=False)             # e.g. "VOO"
    company_name = Column(String(200), nullable=True)
    shares = Column(Float, nullable=False, default=0.0)
    avg_cost = Column(Float, nullable=False, default=0.0)   # Average purchase price per share
    is_active = Column(Boolean, default=True)               # False means soft-deleted
    # True = research-only, excluded from P&L and snapshots
    is_watchlist = Column(Boolean, default=False, server_default="0")
    # auto = FolioOrb decides core/tactical; anchor = long-horizon never-trim hold
    hold_class = Column(String(20), nullable=False, default="auto", server_default="auto")
    notes = Column(Text, nullable=True)
    added_at = Column(DateTime, default=func.now())

    portfolio = relationship("Portfolio", back_populates="holdings")
    # A holding can have many price snapshots recorded over time
    price_history = relationship(
        "PriceSnapshot", back_populates="holding", cascade="all, delete-orphan"
    )


class PriceSnapshot(Base):
    """
    A point-in-time price record for a holding.
    Used to track how the stock price changes over time.
    """
    __tablename__ = "price_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    holding_id = Column(Integer, ForeignKey("holdings.id"), nullable=False)
    price = Column(Float, nullable=False)
    day_change_pct = Column(Float, nullable=True)   # Percentage change from previous close
    recorded_at = Column(DateTime, default=func.now())

    holding = relationship("Holding", back_populates="price_history")


class AISummary(Base):
    """
    Stores AI-generated summaries for individual stocks or the whole portfolio.
    Caching summaries here avoids making repeated API calls for the same data.
    """
    __tablename__ = "ai_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    summary_type = Column(String(20), default="stock")      # "stock" or "portfolio"
    summary_text = Column(Text, nullable=False)
    price_when_generated = Column(Float, nullable=True)     # Stock price at generation time
    generated_at = Column(DateTime, default=func.now())
    model_used = Column(String(50), default="claude-haiku-4-5-20251001")


class RealizedTrade(Base):
    """
    A realized gain/loss event, recorded whenever a holding's share count is
    reduced (a sell). The sale price is the live market price at update time.
    Summing realized_gain across all rows gives cumulative realized P&L.
    """
    __tablename__ = "realized_trades"
    # Realized stats are read per portfolio and grouped by ticker.
    __table_args__ = (
        Index("ix_realized_trades_pid_ticker", "portfolio_id", "ticker"),
    )

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    ticker = Column(String(10), nullable=False, index=True)
    shares_sold = Column(Float, nullable=False)
    sale_price = Column(Float, nullable=False)      # Live price at the time of the reduction
    avg_cost = Column(Float, nullable=False)        # Cost basis per share at the time
    realized_gain = Column(Float, nullable=False)   # (sale_price - avg_cost) * shares_sold
    created_at = Column(DateTime, default=func.now())


class VerdictSnapshot(Base):
    """
    Point-in-time verdict log for calibration — one row per ticker per scan.
    """
    __tablename__ = "verdict_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    # Which portfolio this verdict was logged for. Nullable for rows written
    # before per-portfolio scoping (backfilled to the default portfolio 1).
    portfolio_id = Column(Integer, nullable=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    action = Column(String(20), nullable=False)
    confidence = Column(Integer, nullable=False, default=0)
    local_score = Column(Integer, nullable=True)
    ai_score = Column(Integer, nullable=True)
    price_at_scan = Column(Float, nullable=True)
    hold_class = Column(String(20), nullable=False, default="auto")
    generated_at = Column(DateTime, default=func.now(), index=True)


class PortfolioSnapshot(Base):
    """
    A point-in-time snapshot of portfolio totals, used to chart cumulative
    gain/loss over time. One row per calendar day (upserted), so repeated
    updates on the same day refresh that day's figures rather than duplicating.
    """
    __tablename__ = "portfolio_snapshots"
    # One snapshot row per portfolio per calendar day (upserted on refresh).
    __table_args__ = (
        Index(
            "ux_portfolio_snapshots_pid_date",
            "portfolio_id",
            "snapshot_date",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    snapshot_date = Column(String(10), nullable=False)  # "YYYY-MM-DD"
    total_value = Column(Float, nullable=False)
    total_cost_basis = Column(Float, nullable=False)
    unrealized_gain = Column(Float, nullable=False)
    realized_gain = Column(Float, nullable=False)   # Cumulative realized as of this snapshot
    total_return = Column(Float, nullable=False)     # unrealized + cumulative realized
    created_at = Column(DateTime, default=func.now())


class DcaPlan(Base):
    """
    A recurring dollar-cost-averaging plan that mirrors a brokerage auto-invest
    locally: invest a fixed dollar ``amount`` in ``ticker`` every interval.

    The plan itself never mutates a holding. It only generates DcaContribution
    rows (a "simulated bucket") that the user reviews and chooses to apply, so a
    manually-maintained portfolio stays clean until the user confirms each buy.
    """
    __tablename__ = "dca_plans"
    __table_args__ = (
        Index("ix_dca_plans_portfolio_active", "portfolio_id", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    ticker = Column(String(10), nullable=False)
    amount = Column(Float, nullable=False)               # dollars invested per interval
    frequency = Column(String(10), nullable=False)       # daily | weekly | monthly
    start_date = Column(String(10), nullable=False)      # "YYYY-MM-DD"
    is_active = Column(Boolean, default=True, server_default="1")  # False = paused
    # Earliest date catch-up may book from ("YYYY-MM-DD"); null means the start
    # date (full backfill). Advanced to the resume date when a paused plan is
    # resumed, so the paused stretch is not retroactively bought.
    catchup_floor = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=func.now())

    contributions = relationship(
        "DcaContribution", back_populates="plan", cascade="all, delete-orphan"
    )


class DcaContribution(Base):
    """
    One computed buy in a DCA plan's simulated bucket.

    ``status`` is one of:
      * ``pending``   — computed, awaiting the user's review.
      * ``applied``   — added to the real holding (reversible via undo).
      * ``dismissed`` — skipped; never counted.

    The unique (plan_id, scheduled_date) pair makes catch-up idempotent: rerunning
    it after the app was closed never double-books the same interval.
    """
    __tablename__ = "dca_contributions"
    __table_args__ = (
        Index("ux_dca_contrib_plan_sched", "plan_id", "scheduled_date", unique=True),
        Index("ix_dca_contrib_plan_status", "plan_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("dca_plans.id"), nullable=False)
    scheduled_date = Column(String(10), nullable=False)   # cadence's intended buy date
    exec_date = Column(String(10), nullable=False)        # trading day actually priced
    price = Column(Float, nullable=False)                 # close used for the buy
    shares = Column(Float, nullable=False)                # amount / price (fractional)
    amount = Column(Float, nullable=False)                # dollars invested
    status = Column(
        String(10), nullable=False, default="pending", server_default="pending"
    )
    # Holding updated when this buy was applied, so undo can reverse the exact row.
    applied_holding_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=func.now())

    plan = relationship("DcaPlan", back_populates="contributions")
