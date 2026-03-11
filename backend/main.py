"""
main.py — FastAPI Application
==============================
Wires together the calculator engine, rate presets, rate scraper, and
case store into a single ASGI app served by Uvicorn.

Endpoints
---------
  POST   /api/calculate                     Run a calculation
  GET    /api/rate-presets/cj               Look up the CJ rate for a date
  GET    /api/cases                         List saved cases
  POST   /api/cases                         Save a new case
  GET    /api/cases/{id}                    Get a saved case
  PUT    /api/cases/{id}                    Update a saved case
  DELETE /api/cases/{id}                    Delete a saved case
  GET    /api/settings/rates                Full CJ rate table
  POST   /api/settings/rates/refresh        Scrape + return diff (no write)
  POST   /api/settings/rates/apply          Write diff to disk

Authentication
--------------
  All /api/* routes require the header:
    X-API-Key: <value of APP_API_KEY env var>

  Set APP_API_KEY in your environment before starting the server.
  If not set, the app refuses to start.

Static files
------------
  The frontend/ directory is served at /.
  index.html is served for /, /index.html and any unmatched path (SPA fallback).
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Internal modules
# ---------------------------------------------------------------------------

import calculator as calc
import rate_presets as rp
import rate_scraper as rs
from models import (
    CalculateRequest, CalculateResponse,
    CjRateRequest, CjRateResponse,
    RateTableResponse, RateTableEntry,
    RateRefreshResponse, RateApplyResponse, RateDiffEntry,
    CaseSummary, CaseDetail, SaveCaseRequest, UpdateCaseRequest,
    PeriodResponse, DayPointResponse,
    ErrorResponse,
    DayCountConvention as ModelDCC,
    InterestType as ModelIT,
    InterestBasis as ModelIB,
    RateBasis as ModelRB,
    CompoundingFreq as ModelCF,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HK Judgment Interest Calculator",
    version="0.1.0",
    description="Calculates post-judgment interest under Hong Kong law.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _get_api_key() -> str:
    key = os.environ.get("APP_API_KEY", "")
    if not key:
        raise RuntimeError(
            "APP_API_KEY environment variable is not set. "
            "Set it before starting the server."
        )
    return key


async def require_api_key(
    request: Request,
    header_key: Optional[str] = Security(_API_KEY_HEADER),
) -> None:
    """Dependency: validate the X-API-Key header."""
    try:
        expected = _get_api_key()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    if header_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Supply X-API-Key header.",
        )


# ---------------------------------------------------------------------------
# Helpers: convert between model enums and calculator enums
# ---------------------------------------------------------------------------

def _calc_dcc(v: ModelDCC) -> calc.DayCountConvention:
    return calc.DayCountConvention(v.value)

def _calc_it(v: ModelIT) -> calc.InterestType:
    return calc.InterestType(v.value)

def _calc_ib(v: ModelIB) -> calc.InterestBasis:
    return calc.InterestBasis(v.value)

def _calc_rb(v: ModelRB) -> calc.RateBasis:
    return calc.RateBasis(v.value)

def _calc_cf(v: ModelCF) -> calc.CompoundingFreq:
    return calc.CompoundingFreq(v.value)


def _to_calc_request(req: CalculateRequest):
    """Convert API request models to calculator data structures."""
    gs = calc.GlobalSettings(
        principal=Decimal(str(req.principal)),
        start_date=req.start_date,
        day_count_convention=_calc_dcc(req.day_count_convention),
    )
    periods = [
        calc.PeriodInput(
            end_date=p.end_date,
            interest_type=_calc_it(p.interest_type),
            interest_basis=_calc_ib(p.interest_basis),
            nominal_rate=Decimal(str(p.nominal_rate)),
            rate_basis=_calc_rb(p.rate_basis),
            compounding_freq=_calc_cf(p.compounding_freq),
            include_start_day=p.include_start_day,
            include_end_day=p.include_end_day,
            start_contribution=Decimal(str(p.start_contribution)),
            end_contribution=Decimal(str(p.end_contribution)),
        )
        for p in req.periods
    ]
    return gs, periods


def _period_result_to_response(pr: calc.PeriodResult) -> PeriodResponse:
    return PeriodResponse(
        period_id=pr.period_id,
        start_date=pr.start_date,
        end_date=pr.end_date,
        days=pr.days,
        interest_type=ModelIT(pr.interest_type.value),
        interest_basis=ModelIB(pr.interest_basis.value),
        nominal_rate=float(pr.nominal_rate),
        rate_basis=ModelRB(pr.rate_basis.value),
        compounding_freq=ModelCF(pr.compounding_freq.value),
        include_start_day=pr.include_start_day,
        include_end_day=pr.include_end_day,
        annualised_rate=float(pr.annualised_rate),
        year_fraction=float(pr.year_fraction),
        effective_period_rate=float(pr.effective_period_rate),
        effective_annual_rate=float(pr.effective_annual_rate),
        whole_years=pr.whole_years,
        stub_days=pr.stub_days,
        principal_start=float(pr.principal_start),
        interest=float(pr.interest),
        principal_end=float(pr.principal_end),
        cumulative_interest=float(pr.cumulative_interest),
    )


def _day_point_to_response(dp: calc.DayPoint) -> DayPointResponse:
    return DayPointResponse(
        date=dp.date,
        principal=float(dp.principal),
        prior_cumulative_interest=float(dp.prior_cumulative_interest),
        current_period_accrual=float(dp.current_period_accrual),
        total_interest=float(dp.total_interest),
        total_amount=float(dp.total_amount),
    )


# ---------------------------------------------------------------------------
# Routes: /api/calculate
# ---------------------------------------------------------------------------

@app.post(
    "/api/calculate",
    response_model=CalculateResponse,
    dependencies=[Depends(require_api_key)],
    summary="Run a multi-period interest calculation",
)
async def calculate(req: CalculateRequest) -> CalculateResponse:
    try:
        gs, periods = _to_calc_request(req)
        result = calc.run_case(req.case_name or "Unnamed", gs, periods)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Calculation error: {exc}",
        )

    daily = (
        [_day_point_to_response(dp) for dp in result.daily_series]
        if req.include_daily_series
        else []
    )

    return CalculateResponse(
        case_name=result.case_name,
        principal=float(result.global_settings.principal),
        start_date=result.global_settings.start_date,
        day_count_convention=ModelDCC(result.global_settings.day_count_convention.value),
        total_interest=float(result.total_interest),
        final_amount=float(result.final_amount),
        periods=[_period_result_to_response(pr) for pr in result.periods],
        daily_series=daily,
        explanation=result.explanation,
        generated_at=result.generated_at,
    )


# ---------------------------------------------------------------------------
# Routes: /api/rate-presets
# ---------------------------------------------------------------------------

@app.get(
    "/api/rate-presets/cj",
    response_model=CjRateResponse,
    dependencies=[Depends(require_api_key)],
    summary="Look up the CJ judgment interest rate applicable on a given date",
)
async def get_cj_rate(query_date: date) -> CjRateResponse:
    """
    Returns the CJ judgment interest rate (% per annum) applicable on
    `query_date`.  Pass as a query parameter: ?query_date=2025-06-15
    """
    try:
        rate_fraction = rp.get_cj_rate(query_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    # Find the effective_date of this rate by locating its table entry
    table = rp.get_rate_table()
    effective_date = query_date  # fallback
    for entry in table:
        if entry.effective_date <= query_date:
            effective_date = entry.effective_date
            break

    return CjRateResponse(
        query_date=query_date,
        effective_date=effective_date,
        rate_pct=float(rate_fraction * 100),
        rate_fraction=float(rate_fraction),
    )


# ---------------------------------------------------------------------------
# Routes: /api/cases  (CRUD — backed by case_store)
# ---------------------------------------------------------------------------

def _get_case_store():
    """Lazy import so case_store.py can be developed independently."""
    try:
        import case_store
        return case_store
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Case store not yet initialised. Run database migrations.",
        )


@app.get(
    "/api/cases",
    response_model=list[CaseSummary],
    dependencies=[Depends(require_api_key)],
    summary="List all saved cases",
)
async def list_cases():
    store = _get_case_store()
    return store.list_cases()


@app.post(
    "/api/cases",
    response_model=CaseDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key)],
    summary="Save a new case",
)
async def create_case(body: SaveCaseRequest):
    store = _get_case_store()
    return store.create_case(body.name, body.request_payload)


@app.get(
    "/api/cases/{case_id}",
    response_model=CaseDetail,
    dependencies=[Depends(require_api_key)],
    summary="Get a saved case by ID",
)
async def get_case(case_id: int):
    store = _get_case_store()
    case = store.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return case


@app.put(
    "/api/cases/{case_id}",
    response_model=CaseDetail,
    dependencies=[Depends(require_api_key)],
    summary="Update a saved case",
)
async def update_case(case_id: int, body: UpdateCaseRequest):
    store = _get_case_store()
    case = store.update_case(case_id, body.name, body.request_payload)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return case


@app.delete(
    "/api/cases/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_key)],
    summary="Delete a saved case",
)
async def delete_case(case_id: int):
    store = _get_case_store()
    deleted = store.delete_case(case_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")


# ---------------------------------------------------------------------------
# Routes: /api/settings/rates
# ---------------------------------------------------------------------------

@app.get(
    "/api/settings/rates",
    response_model=RateTableResponse,
    dependencies=[Depends(require_api_key)],
    summary="Return the full CJ rate table",
)
async def get_rate_table() -> RateTableResponse:
    summary = rp.rate_summary()
    return RateTableResponse(
        count=summary["count"],
        earliest_date=date.fromisoformat(summary["earliest_date"]) if summary["earliest_date"] else None,
        latest_date=date.fromisoformat(summary["latest_date"]) if summary["latest_date"] else None,
        latest_rate_pct=summary["latest_rate_pct"],
        entries=[
            RateTableEntry(
                effective_date=date.fromisoformat(e["effective_date"]),
                rate_pct=e["rate_pct"],
            )
            for e in summary["entries"]
        ],
    )


@app.post(
    "/api/settings/rates/refresh",
    response_model=RateRefreshResponse,
    dependencies=[Depends(require_api_key)],
    summary="Scrape the Judiciary website and return new entries (preview only)",
)
async def refresh_rates() -> RateRefreshResponse:
    """
    Fetches the Judiciary interest rate page, computes a diff against the
    local rate table, and returns new entries without writing to disk.

    Call /api/settings/rates/apply to persist the changes.
    """
    try:
        _all, diff = rs.scrape_rates()
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Scraper dependencies missing: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch rates from Judiciary website: {exc}",
        )

    new_entries = [
        RateDiffEntry(
            effective_date=e.effective_date,
            rate_pct=float(e.rate_pct),
        )
        for e in diff
    ]

    if diff:
        msg = (
            f"Found {len(diff)} new rate entr{'y' if len(diff)==1 else 'ies'}. "
            f"Call /api/settings/rates/apply to save them."
        )
    else:
        msg = "Rate table is already up to date."

    return RateRefreshResponse(
        new_entries=new_entries,
        new_count=len(new_entries),
        message=msg,
    )


@app.post(
    "/api/settings/rates/apply",
    response_model=RateApplyResponse,
    dependencies=[Depends(require_api_key)],
    summary="Write previously-scraped new rate entries to disk",
)
async def apply_rates(body: RateRefreshResponse) -> RateApplyResponse:
    """
    Accepts the RateRefreshResponse from /refresh and writes the new entries
    to cj_rates.json, then reloads the in-memory cache.

    This two-step design (refresh → review → apply) prevents accidental
    overwrites and gives the user a chance to inspect changes first.
    """
    new_scraped = [
        rs.ScrapedEntry(
            effective_date=e.effective_date,
            rate_pct=Decimal(str(e.rate_pct)),
        )
        for e in body.new_entries
    ]

    try:
        result = rs.apply_diff(new_scraped)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write rate table: {exc}",
        )

    return RateApplyResponse(
        applied=result["applied"],
        total=result["total"],
        new_dates=result["new_dates"],
        message=(
            f"Applied {result['applied']} new entr{'y' if result['applied']==1 else 'ies'}. "
            f"Rate table now has {result['total']} entries."
        ) if result["applied"] else "Nothing to apply — rate table is already up to date.",
    )


# ---------------------------------------------------------------------------
# Static file serving (frontend)
# ---------------------------------------------------------------------------

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
_INDEX_HTML = os.path.join(_FRONTEND_DIR, "index.html")


def _setup_static():
    """Mount the frontend directory if it exists (skip in test environments)."""
    if os.path.isdir(_FRONTEND_DIR):
        app.mount(
            "/static",
            StaticFiles(directory=_FRONTEND_DIR),
            name="static",
        )


_setup_static()


def _render_index() -> "HTMLResponse":
    """
    Read index.html and inject window.__API_KEY__ so the browser JS
    can authenticate against the API without any manual configuration.
    """
    from fastapi.responses import HTMLResponse
    try:
        key = _get_api_key()
    except RuntimeError:
        key = ""
    html = open(_INDEX_HTML, encoding="utf-8").read()
    injection = f'<script>window.__API_KEY__="{key}";</script>'
    html = html.replace("</head>", injection + "\n</head>", 1)
    return HTMLResponse(html)


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
async def serve_index():
    if os.path.exists(_INDEX_HTML):
        return _render_index()
    return JSONResponse(
        {"message": "Frontend not yet built. API docs at /api/docs"},
        status_code=200,
    )


# SPA catch-all: unknown paths serve index.html so client-side routing works
@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    # Don't intercept /api routes (they 404 normally)
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)
    if os.path.exists(_INDEX_HTML):
        return _render_index()
    raise HTTPException(status_code=404)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=os.environ.get("RELOAD", "false").lower() == "true",
    )
