"""
models.py — Pydantic v2 Request/Response Schemas
=================================================
All API input and output shapes are defined here.
The calculator, rate_presets and rate_scraper modules are never imported
in this file — models are pure data contracts.

Decimal serialisation
---------------------
Pydantic v2 serialises Decimal as a string by default to preserve precision.
We override this for monetary values to emit JSON numbers with 2 d.p., and
for rates to emit numbers with up to 6 s.f. — matching what the front-end
expects without manual conversion at every call site.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Shared enums (mirrored from calculator.py — kept separate so models.py has
# no dependency on the engine)
# ---------------------------------------------------------------------------

from enum import Enum


class DayCountConvention(str, Enum):
    ACTUAL_365_FIXED = "Actual/365 Fixed"
    ANNIVERSARY_365  = "Anniversary/365"
    ACTUAL_ACTUAL    = "Actual/Actual"


class InterestType(str, Enum):
    SIMPLE   = "Simple"
    COMPOUND = "Compound"


class InterestBasis(str, Enum):
    INITIAL_PRINCIPAL = "Initial Principal"
    RUNNING_SUM       = "Running Sum"


class RateBasis(str, Enum):
    PER_ANNUM   = "Per annum"
    PER_MONTH   = "Per month"
    PER_QUARTER = "Per quarter"
    PER_DAY     = "Per day"


class CompoundingFreq(str, Enum):
    MONTHLY     = "Monthly"
    QUARTERLY   = "Quarterly"
    SEMI_ANNUAL = "Semi-annual"
    ANNUAL      = "Annual"


# ---------------------------------------------------------------------------
# Monetary / rate type aliases (for documentation & validation)
# ---------------------------------------------------------------------------

# A non-negative monetary amount with up to 2 d.p.
Money = Annotated[Decimal, Field(ge=Decimal("0"), decimal_places=2)]

# A rate expressed as a decimal fraction (e.g. 0.08 for 8%)
# Upper bound 100 allows absurd rates without crashing; UI validates further
RateFraction = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100"))]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PeriodRequest(BaseModel):
    """One interest period as submitted by the user."""
    end_date: date
    interest_type: InterestType = InterestType.SIMPLE
    interest_basis: InterestBasis = InterestBasis.INITIAL_PRINCIPAL
    nominal_rate: RateFraction = Field(
        ...,
        description="Rate as a decimal fraction, e.g. 0.08 for 8% pa"
    )
    rate_basis: RateBasis = RateBasis.PER_ANNUM
    compounding_freq: CompoundingFreq = CompoundingFreq.ANNUAL
    include_start_day: bool = True
    include_end_day: bool = True
    start_contribution: Decimal = Decimal("0")
    end_contribution: Decimal = Decimal("0")

    @field_validator("start_contribution", "end_contribution", mode="before")
    @classmethod
    def coerce_contribution(cls, v):
        return Decimal(str(v)) if v is not None else Decimal("0")


class CalculateRequest(BaseModel):
    """Full calculation request body."""
    case_name: str = Field(default="", max_length=200)
    principal: Decimal = Field(..., gt=Decimal("0"),
                               description="Initial principal in HKD")
    start_date: date
    day_count_convention: DayCountConvention = DayCountConvention.ACTUAL_365_FIXED
    periods: list[PeriodRequest] = Field(..., min_length=1, max_length=50)
    include_daily_series: bool = Field(
        default=True,
        description="Include per-day data points for chart rendering. "
                    "Set false for large date ranges to reduce payload size."
    )

    @model_validator(mode="after")
    def periods_must_be_forward(self) -> "CalculateRequest":
        """Each period end_date must be after the previous end (or start_date)."""
        prev = self.start_date
        for i, p in enumerate(self.periods):
            if p.end_date <= prev:
                raise ValueError(
                    f"Period {i+1}: end_date {p.end_date} must be after "
                    f"{'start_date' if i == 0 else f'period {i} end_date'} {prev}"
                )
            prev = p.end_date
        return self


class CjRateRequest(BaseModel):
    """Query params for the CJ rate preset lookup."""
    query_date: date = Field(..., description="The date to look up the applicable CJ rate for")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class PeriodResponse(BaseModel):
    """Per-period calculation output."""
    period_id: int
    start_date: date
    end_date: date
    days: int
    interest_type: InterestType
    interest_basis: InterestBasis
    nominal_rate: float             # fraction, e.g. 0.08
    rate_basis: RateBasis
    compounding_freq: CompoundingFreq
    include_start_day: bool
    include_end_day: bool
    annualised_rate: float
    year_fraction: float
    effective_period_rate: float
    effective_annual_rate: float
    whole_years: int
    stub_days: int
    principal_start: float
    interest: float
    principal_end: float
    cumulative_interest: float


class DayPointResponse(BaseModel):
    """One point in the daily series for chart rendering."""
    date: date
    principal: float
    prior_cumulative_interest: float
    current_period_accrual: float
    total_interest: float
    total_amount: float


class CalculateResponse(BaseModel):
    """Full calculation response."""
    case_name: str
    principal: float
    start_date: date
    day_count_convention: DayCountConvention
    total_interest: float
    final_amount: float
    periods: list[PeriodResponse]
    daily_series: list[DayPointResponse]
    explanation: list[str]
    generated_at: str


class CjRateResponse(BaseModel):
    """CJ rate lookup response."""
    query_date: date
    effective_date: date
    rate_pct: float          # e.g. 8.107
    rate_fraction: float     # e.g. 0.08107


class RateTableEntry(BaseModel):
    effective_date: date
    rate_pct: float


class RateTableResponse(BaseModel):
    """Full rate table for the Settings page."""
    count: int
    earliest_date: Optional[date]
    latest_date: Optional[date]
    latest_rate_pct: Optional[float]
    entries: list[RateTableEntry]


class RateDiffEntry(BaseModel):
    effective_date: date
    rate_pct: float


class RateRefreshResponse(BaseModel):
    """Response from POST /api/settings/rates/refresh (preview only, no write)."""
    new_entries: list[RateDiffEntry]
    new_count: int
    message: str


class RateApplyResponse(BaseModel):
    """Response from POST /api/settings/rates/apply."""
    applied: int
    total: int
    new_dates: list[str]
    message: str


# ---------------------------------------------------------------------------
# Case store models (for saved cases)
# ---------------------------------------------------------------------------

class CaseSummary(BaseModel):
    """Lightweight case listing item."""
    id: int
    name: str
    principal: float
    start_date: date
    period_count: int
    total_interest: Optional[float]
    created_at: str
    updated_at: str


class CaseDetail(CaseSummary):
    """Full saved case including the original request payload."""
    request_payload: dict        # the raw CalculateRequest as stored
    last_result: Optional[dict]  # the last CalculateResponse, if cached


class SaveCaseRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    request_payload: dict


class UpdateCaseRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    request_payload: Optional[dict] = None


# ---------------------------------------------------------------------------
# Error response
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None
