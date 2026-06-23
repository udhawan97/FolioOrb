from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


# Pydantic schemas define the shape of data coming IN (requests) and going OUT (responses).
# They are separate from the SQLAlchemy models in models.py.
#
# - "Create" schemas = data the client sends to us (request body)
# - "Update" schemas = data the client sends to modify an existing record
# - "Response" schemas = data we send back to the client
#
# Pydantic validates data automatically — e.g. it rejects negative share counts
# before the request even reaches our route function.


# ── Holding Schemas ────────────────────────────────────────────────────

class HoldingCreate(BaseModel):
    """Data required to add a new holding."""
    ticker: str = Field(..., min_length=1, max_length=10,
                        description="Stock ticker symbol, e.g. VOO")
    shares: float = Field(..., gt=0, description="Number of shares (must be > 0)")
    avg_cost: Optional[float] = Field(None, gt=0, description="Average purchase price per share")
    notes: Optional[str] = Field(None, max_length=500)
    is_watchlist: Optional[bool] = False  # True = research-only, excluded from P&L

    @field_validator("ticker")
    @classmethod
    def uppercase_ticker(cls, v):
        # Normalize the ticker so "voo", "VOO", and " Voo " all become "VOO"
        return v.upper().strip()


class HoldingUpdate(BaseModel):
    """Fields that can be changed on an existing holding. All fields are optional."""
    shares: Optional[float] = Field(None, gt=0)
    avg_cost: Optional[float] = Field(None, gt=0)
    notes: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None
    is_watchlist: Optional[bool] = None  # Toggle research mode without affecting P&L


class HoldingResponse(BaseModel):
    """Shape of a holding returned in API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    company_name: Optional[str]
    shares: float
    avg_cost: Optional[float]
    is_active: bool
    notes: Optional[str]
    added_at: datetime


# ── Portfolio Schemas ──────────────────────────────────────────────────

class PortfolioCreate(BaseModel):
    """Data required to create a new portfolio."""
    name: str = Field(default="My Portfolio", max_length=100)
    description: Optional[str] = None


class PortfolioResponse(BaseModel):
    """Shape of a portfolio returned in API responses, including its list of holdings."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    created_at: datetime
    holdings: list[HoldingResponse] = []
