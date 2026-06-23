from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
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

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    ticker = Column(String(10), nullable=False)             # e.g. "VOO"
    company_name = Column(String(200), nullable=True)
    shares = Column(Float, nullable=False, default=0.0)
    avg_cost = Column(Float, nullable=False, default=0.0)   # Average purchase price per share
    is_active = Column(Boolean, default=True)               # False means soft-deleted
    is_watchlist = Column(Boolean, default=False, server_default="0")  # True = research-only, excluded from P&L and snapshots
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
    model_used = Column(String(50), default="claude-3-haiku-20240307")


class RealizedTrade(Base):
    """
    A realized gain/loss event, recorded whenever a holding's share count is
    reduced (a sell). The sale price is the live market price at update time.
    Summing realized_gain across all rows gives cumulative realized P&L.
    """
    __tablename__ = "realized_trades"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    ticker = Column(String(10), nullable=False, index=True)
    shares_sold = Column(Float, nullable=False)
    sale_price = Column(Float, nullable=False)      # Live price at the time of the reduction
    avg_cost = Column(Float, nullable=False)        # Cost basis per share at the time
    realized_gain = Column(Float, nullable=False)   # (sale_price - avg_cost) * shares_sold
    created_at = Column(DateTime, default=func.now())


class PortfolioSnapshot(Base):
    """
    A point-in-time snapshot of portfolio totals, used to chart cumulative
    gain/loss over time. One row per calendar day (upserted), so repeated
    updates on the same day refresh that day's figures rather than duplicating.
    """
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False)
    snapshot_date = Column(String(10), nullable=False, index=True)  # "YYYY-MM-DD"
    total_value = Column(Float, nullable=False)
    total_cost_basis = Column(Float, nullable=False)
    unrealized_gain = Column(Float, nullable=False)
    realized_gain = Column(Float, nullable=False)   # Cumulative realized as of this snapshot
    total_return = Column(Float, nullable=False)     # unrealized + cumulative realized
    created_at = Column(DateTime, default=func.now())
