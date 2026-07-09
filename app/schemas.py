import re
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

_TICKER_PATTERN = re.compile(r"^[A-Z0-9.^-]{1,10}$")
_HOLD_CLASS_VALUES = {"auto", "anchor", "trade", "core"}


def _normalize_hold_class(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    hold_class = str(value).strip().lower()
    if hold_class not in _HOLD_CLASS_VALUES:
        raise ValueError("hold_class must be one of: auto, anchor, trade, core")
    return hold_class

class HoldingCreate(BaseModel):
    """Data required to add a new holding."""
    ticker: str = Field(..., min_length=1, max_length=10,
                        description="Stock ticker symbol, e.g. VOO")
    shares: Optional[float] = Field(
        default=0.0, ge=0, allow_inf_nan=False,
        description="Number of shares (must be > 0 for positions)",
    )
    avg_cost: Optional[float] = Field(
        None, gt=0, allow_inf_nan=False, description="Average purchase price per share"
    )
    notes: Optional[str] = Field(None, max_length=500)
    is_watchlist: Optional[bool] = False  # True = research-only, excluded from P&L
    hold_class: Optional[str] = Field(default="auto")

    @field_validator("ticker")
    @classmethod
    def uppercase_ticker(cls, v):
        # Normalize the ticker so "voo", "VOO", and " Voo " all become "VOO"
        ticker = v.upper().strip()
        if not _TICKER_PATTERN.fullmatch(ticker):
            raise ValueError(
                "Ticker may contain only letters, numbers, '.', '-', or '^'"
            )
        return ticker

    @field_validator("hold_class")
    @classmethod
    def valid_hold_class(cls, v):
        return _normalize_hold_class(v) or "auto"

    @model_validator(mode="after")
    def shares_required_for_positions(self):
        if not self.is_watchlist and (self.shares is None or self.shares <= 0):
            raise ValueError("shares must be greater than 0 unless research mode is on")
        return self


class HoldingUpdate(BaseModel):
    """Fields that can be changed on an existing holding. All fields are optional."""
    shares: Optional[float] = Field(None, gt=0)
    avg_cost: Optional[float] = Field(None, gt=0)
    notes: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None
    is_watchlist: Optional[bool] = None  # Toggle research mode without affecting P&L
    hold_class: Optional[str] = None

    @field_validator("hold_class")
    @classmethod
    def valid_hold_class(cls, v):
        return _normalize_hold_class(v)


class HoldingResponse(BaseModel):
    """Shape of a holding returned in API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    company_name: Optional[str]
    shares: float
    avg_cost: Optional[float]
    is_active: bool
    hold_class: str
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
