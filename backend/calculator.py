"""
calculator.py — Judgment Interest Calculation Engine
=====================================================
Pure Python, zero web/framework dependencies.
All monetary values use Decimal for precision.
All functions are stateless and independently testable.

Mathematical model
------------------
For each period:

  1. Days = (end − start) + include_start + include_end − 1

  2. Annualised Rate:
       Per annum   → r
       Per month   → r × 12
       Per quarter → r × 4
       Per day     → r × 365

  3. Year Fraction (t):
       Actual/365 Fixed   → days / 365
       Anniversary/365    → whole_years + stub_days / 365
       Actual/Actual      → ISDA Actual/Actual (splits at 1 Jan each year)

  4. Effective Period Rate (EPR):
       Simple   → r_annual × t
       Compound → (1 + r_annual / m) ^ (m × t) − 1
         where m = compounding frequency per year

  5. Interest:
       Initial Principal basis → P₀ × EPR
       Running Sum basis       → Principal_Start × EPR

  6. Principal_End = Principal_Start + Interest + End_Contribution
     Cumulative_Interest += Interest
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

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
    MONTHLY     = "Monthly"      # m = 12
    QUARTERLY   = "Quarterly"    # m = 4
    SEMI_ANNUAL = "Semi-annual"  # m = 2
    ANNUAL      = "Annual"       # m = 1


# ---------------------------------------------------------------------------
# Input / output data structures
# ---------------------------------------------------------------------------

@dataclass
class GlobalSettings:
    principal: Decimal
    start_date: date
    day_count_convention: DayCountConvention


@dataclass
class PeriodInput:
    end_date: date
    interest_type: InterestType
    interest_basis: InterestBasis
    nominal_rate: Decimal                     # e.g. Decimal("0.24") for 24%
    rate_basis: RateBasis = RateBasis.PER_ANNUM
    compounding_freq: CompoundingFreq = CompoundingFreq.ANNUAL
    include_start_day: bool = True
    include_end_day: bool = True
    start_contribution: Decimal = field(default_factory=lambda: Decimal("0"))
    end_contribution: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class PeriodResult:
    period_id: int
    start_date: date
    end_date: date
    days: int
    interest_type: InterestType
    interest_basis: InterestBasis
    nominal_rate: Decimal
    rate_basis: RateBasis
    compounding_freq: CompoundingFreq
    include_start_day: bool
    include_end_day: bool
    annualised_rate: Decimal
    year_fraction: Decimal
    effective_period_rate: Decimal
    effective_annual_rate: Decimal
    principal_start: Decimal
    interest: Decimal
    principal_end: Decimal
    cumulative_interest: Decimal
    whole_years: int = 0
    stub_days: int = 0


@dataclass
class DayPoint:
    date: date
    principal: Decimal
    prior_cumulative_interest: Decimal
    current_period_accrual: Decimal

    @property
    def total_interest(self) -> Decimal:
        return self.prior_cumulative_interest + self.current_period_accrual

    @property
    def total_amount(self) -> Decimal:
        return self.principal + self.total_interest


@dataclass
class CaseResult:
    case_name: str
    global_settings: GlobalSettings
    periods: list
    total_interest: Decimal
    final_amount: Decimal
    daily_series: list
    explanation: list
    generated_at: str


# ---------------------------------------------------------------------------
# Step 1 — Effective days
# ---------------------------------------------------------------------------

def compute_days(
    start: date,
    end: date,
    include_start: bool,
    include_end: bool,
) -> int:
    """
    Count interest-bearing days.

    Formula: (end − start) + include_start + include_end − 1

    Boundary examples
    -----------------
    Both included  : (end − start) + 1   ← default, counts both endpoints
    Start only     : (end − start)
    End only       : (end − start)
    Neither        : (end − start) − 1
    """
    raw = (end - start).days
    days = raw + (1 if include_start else 0) + (1 if include_end else 0) - 1
    return max(days, 0)


# ---------------------------------------------------------------------------
# Step 2 — Annualised nominal rate
# ---------------------------------------------------------------------------

def annualise_rate(nominal_rate: Decimal, rate_basis: RateBasis) -> Decimal:
    """Convert any rate basis to its per-annum equivalent."""
    multipliers = {
        RateBasis.PER_ANNUM:   Decimal("1"),
        RateBasis.PER_MONTH:   Decimal("12"),
        RateBasis.PER_QUARTER: Decimal("4"),
        RateBasis.PER_DAY:     Decimal("365"),
    }
    return nominal_rate * multipliers[rate_basis]


# ---------------------------------------------------------------------------
# Step 3 — Year fraction
# ---------------------------------------------------------------------------

def _compounding_freq_to_int(freq: CompoundingFreq) -> int:
    return {
        CompoundingFreq.MONTHLY:     12,
        CompoundingFreq.QUARTERLY:   4,
        CompoundingFreq.SEMI_ANNUAL: 2,
        CompoundingFreq.ANNUAL:      1,
    }[freq]


def _is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def _anniversary_yf(eff_start: date, eff_end: date):
    """
    Anniversary/365 convention.

    Count full calendar years from eff_start; divide the remaining stub
    by 365.  Returns (year_fraction, whole_years, stub_days).
    """
    if eff_start >= eff_end:
        return Decimal("0"), 0, 0

    # Count whole years by walking forward anniversary dates
    whole_years = 0
    anniversary = eff_start
    while True:
        # Next anniversary: same month/day, one year later
        # (handles 29 Feb by clamping to 28 Feb in non-leap years)
        next_year = anniversary.year + 1
        try:
            next_ann = date(next_year, anniversary.month, anniversary.day)
        except ValueError:
            # 29 Feb → 28 Feb in non-leap year
            next_ann = date(next_year, anniversary.month, 28)

        if next_ann > eff_end:
            break
        anniversary = next_ann
        whole_years += 1

    stub_days = (eff_end - anniversary).days
    yf = Decimal(whole_years) + Decimal(stub_days) / Decimal("365")
    return yf, whole_years, stub_days


def _actual_actual_yf(eff_start: date, eff_end: date) -> Decimal:
    """
    Actual/Actual (ISDA) convention.
    Split at each 1 Jan; weight days by whether they fall in a leap year.
    """
    if eff_start >= eff_end:
        return Decimal("0")

    total = Decimal("0")
    cursor = eff_start
    while cursor < eff_end:
        year_end = date(cursor.year + 1, 1, 1)
        segment_end = min(eff_end, year_end)
        days_in_segment = (segment_end - cursor).days
        days_in_year = 366 if _is_leap(cursor.year) else 365
        total += Decimal(days_in_segment) / Decimal(days_in_year)
        cursor = segment_end

    return total


def year_fraction(
    eff_start: date,
    eff_end: date,
    convention: DayCountConvention,
):
    """
    Compute (year_fraction, whole_years, stub_days) for a period.

    Effective dates are the calendar dates after applying include-day flags:
        eff_start = start_date if include_start else start_date + 1 day
        eff_end   = end_date + 1 day if include_end else end_date

    whole_years and stub_days are non-zero only for Anniversary/365.
    """
    if eff_start >= eff_end:
        return Decimal("0"), 0, 0

    if convention == DayCountConvention.ACTUAL_365_FIXED:
        days = (eff_end - eff_start).days
        return Decimal(days) / Decimal("365"), 0, 0

    elif convention == DayCountConvention.ANNIVERSARY_365:
        return _anniversary_yf(eff_start, eff_end)

    elif convention == DayCountConvention.ACTUAL_ACTUAL:
        return _actual_actual_yf(eff_start, eff_end), 0, 0

    else:
        raise ValueError(f"Unknown day count convention: {convention}")


# ---------------------------------------------------------------------------
# Step 4 — Effective period rate
# ---------------------------------------------------------------------------

def effective_period_rate(
    annualised_rate: Decimal,
    yf: Decimal,
    interest_type: InterestType,
    compounding_freq: CompoundingFreq,
) -> Decimal:
    """
    Compute the interest factor for one period.

    Simple:   EPR = r × t
    Compound: EPR = (1 + r/m)^(m×t) − 1

    Float arithmetic is used for exponentiation; the result is immediately
    rounded back to Decimal via str() to avoid binary float representation
    errors accumulating in further Decimal arithmetic.
    """
    r = float(annualised_rate)
    t = float(yf)

    if interest_type == InterestType.SIMPLE:
        epr = r * t
    else:
        m = _compounding_freq_to_int(compounding_freq)
        epr = (1.0 + r / m) ** (m * t) - 1.0

    return Decimal(str(epr))


def effective_annual_rate(
    annualised_rate: Decimal,
    interest_type: InterestType,
    compounding_freq: CompoundingFreq,
) -> Decimal:
    """Informational EAR (not used in interest computation)."""
    if interest_type == InterestType.SIMPLE:
        return annualised_rate
    m = _compounding_freq_to_int(compounding_freq)
    r = float(annualised_rate)
    return Decimal(str((1.0 + r / m) ** m - 1.0))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hkd(value: Decimal) -> Decimal:
    """Round to 2 decimal places (HKD cents), half-up."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _eff_start(start: date, include_start: bool) -> date:
    return start if include_start else start + timedelta(days=1)


def _eff_end(end: date, include_end: bool) -> date:
    return end + timedelta(days=1) if include_end else end


# ---------------------------------------------------------------------------
# Step 5 — Single period
# ---------------------------------------------------------------------------

def compute_period(
    period_id: int,
    start_date: date,
    period_input: PeriodInput,
    principal_start: Decimal,
    initial_principal: Decimal,
    cumulative_interest_before: Decimal,
    convention: DayCountConvention,
) -> PeriodResult:
    """
    Compute all output values for one period.

    The start_date is supplied by the caller (= previous period end_date,
    or global start_date for the first period).
    """
    pi = period_input

    # Effective boundary dates for year-fraction
    eff_s = _eff_start(start_date,  pi.include_start_day)
    eff_e = _eff_end(pi.end_date,   pi.include_end_day)

    # 1. Days
    days = compute_days(start_date, pi.end_date, pi.include_start_day, pi.include_end_day)

    # 2. Annualised rate
    ann_rate = annualise_rate(pi.nominal_rate, pi.rate_basis)

    # 3. Year fraction
    yf, whole_years, stub_days = year_fraction(eff_s, eff_e, convention)

    # 4. Rates
    epr = effective_period_rate(ann_rate, yf, pi.interest_type, pi.compounding_freq)
    ear = effective_annual_rate(ann_rate, pi.interest_type, pi.compounding_freq)

    # 5. Interest
    ps = _hkd(principal_start + pi.start_contribution)
    interest_base = (
        initial_principal
        if pi.interest_basis == InterestBasis.INITIAL_PRINCIPAL
        else ps
    )
    interest = _hkd(interest_base * epr)

    # 6. Chain
    principal_end       = _hkd(ps + interest + pi.end_contribution)
    cumulative_interest = _hkd(cumulative_interest_before + interest)

    return PeriodResult(
        period_id=period_id,
        start_date=start_date,
        end_date=pi.end_date,
        days=days,
        interest_type=pi.interest_type,
        interest_basis=pi.interest_basis,
        nominal_rate=pi.nominal_rate,
        rate_basis=pi.rate_basis,
        compounding_freq=pi.compounding_freq,
        include_start_day=pi.include_start_day,
        include_end_day=pi.include_end_day,
        annualised_rate=ann_rate,
        year_fraction=yf,
        effective_period_rate=epr,
        effective_annual_rate=ear,
        principal_start=ps,
        interest=interest,
        principal_end=principal_end,
        cumulative_interest=cumulative_interest,
        whole_years=whole_years,
        stub_days=stub_days,
    )


# ---------------------------------------------------------------------------
# Step 6 — All periods
# ---------------------------------------------------------------------------

def compute_all_periods(
    global_settings: GlobalSettings,
    period_inputs: list,
) -> list:
    """Chain all periods, passing principal_end and cumulative_interest forward."""
    results = []
    principal_start       = global_settings.principal
    cumulative_interest   = Decimal("0")
    current_start         = global_settings.start_date

    for i, pi in enumerate(period_inputs):
        result = compute_period(
            period_id=i + 1,
            start_date=current_start,
            period_input=pi,
            principal_start=principal_start,
            initial_principal=global_settings.principal,
            cumulative_interest_before=cumulative_interest,
            convention=global_settings.day_count_convention,
        )
        results.append(result)
        principal_start     = result.principal_end
        cumulative_interest = result.cumulative_interest
        current_start       = pi.end_date

    return results


# ---------------------------------------------------------------------------
# Daily series (chart data)
# ---------------------------------------------------------------------------

def daily_series(
    global_settings: GlobalSettings,
    period_results: list,
) -> list:
    """
    One DayPoint per calendar day.  Within each period the accrual is
    interpolated linearly — a visualisation approximation; per-period
    totals remain exact.
    """
    if not period_results:
        return []

    points = []
    principal = global_settings.principal

    for pr in period_results:
        period_days = (pr.end_date - pr.start_date).days
        if period_days <= 0:
            continue

        prior_cum    = pr.cumulative_interest - pr.interest
        daily_amount = pr.interest / Decimal(period_days)

        for offset in range(period_days):
            current_date = pr.start_date + timedelta(days=offset)
            accrual = _hkd(daily_amount * Decimal(offset + 1))
            points.append(DayPoint(
                date=current_date,
                principal=principal,
                prior_cumulative_interest=prior_cum,
                current_period_accrual=accrual,
            ))

    # Final day at full cumulative
    last = period_results[-1]
    points.append(DayPoint(
        date=last.end_date,
        principal=principal,
        prior_cumulative_interest=last.cumulative_interest,
        current_period_accrual=Decimal("0"),
    ))

    return points


# ---------------------------------------------------------------------------
# Explanation generator
# ---------------------------------------------------------------------------

_ORDINALS = {1:"1st",2:"2nd",3:"3rd",4:"4th",5:"5th",
             6:"6th",7:"7th",8:"8th",9:"9th",10:"10th"}


def _fmt_date(d: date) -> str:
    # e.g. "21 Aug 2015"  — use lstrip to avoid leading zero on all platforms
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _fmt_hkd(v: Decimal) -> str:
    return f"HK${v:,.2f}"


def _fmt_pct(r: Decimal) -> str:
    pct = float(r) * 100
    # Show up to 4 significant figures, strip trailing zeros
    return f"{pct:.4g}%"


def generate_explanation(
    global_settings: GlobalSettings,
    period_results: list,
) -> list:
    """
    Return a list of plain-English strings: one per period, plus a summary.
    """
    paragraphs = []

    # Preamble
    paragraphs.append(
        f"Day Count Convention: {global_settings.day_count_convention.value}. "
        f"Initial Principal: {_fmt_hkd(global_settings.principal)}."
    )

    for pr in period_results:
        ordinal = _ORDINALS.get(pr.period_id, f"{pr.period_id}th")
        incl = (
            f"{'including' if pr.include_start_day else 'excluding'} the start day, "
            f"{'including' if pr.include_end_day else 'excluding'} the end day"
        )

        if pr.interest_basis == InterestBasis.INITIAL_PRINCIPAL:
            basis_str = f"the initial principal of {_fmt_hkd(global_settings.principal)}"
            interest_base = global_settings.principal
        else:
            basis_str = f"the running sum of {_fmt_hkd(pr.principal_start)}"
            interest_base = pr.principal_start

        rate_str = f"{_fmt_pct(pr.nominal_rate)} {pr.rate_basis.value.lower()}"

        # Year fraction detail
        conv = global_settings.day_count_convention
        if conv == DayCountConvention.ANNIVERSARY_365 and pr.whole_years:
            yf_detail = (
                f"{pr.whole_years} whole year{'s' if pr.whole_years != 1 else ''} "
                f"+ {pr.stub_days} stub day{'s' if pr.stub_days != 1 else ''} / 365 "
                f"= {float(pr.year_fraction):.6g} years"
            )
        else:
            yf_detail = f"{pr.days} days / 365 = {float(pr.year_fraction):.6g} years"

        # Interest formula display
        if pr.interest_type == InterestType.SIMPLE:
            type_str = "simple interest"
            formula = (
                f"{_fmt_hkd(interest_base)} × {_fmt_pct(pr.annualised_rate)} "
                f"× {float(pr.year_fraction):.6g} years = {_fmt_hkd(pr.interest)}"
            )
        else:
            m = _compounding_freq_to_int(pr.compounding_freq)
            type_str = f"compound interest (compounded {pr.compounding_freq.value.lower()})"
            formula = (
                f"(1 + {_fmt_pct(pr.annualised_rate)} / {m})^"
                f"({m} × {float(pr.year_fraction):.6g}) − 1 "
                f"= {_fmt_pct(pr.effective_period_rate)} effective rate "
                f"on {_fmt_hkd(interest_base)} = {_fmt_hkd(pr.interest)}"
            )

        para = (
            f"Period {pr.period_id} ({ordinal} period): {type_str} at {rate_str} "
            f"on {basis_str}, from {_fmt_date(pr.start_date)} to "
            f"{_fmt_date(pr.end_date)}. "
            f"This period has {pr.days} interest day{'s' if pr.days != 1 else ''} "
            f"({incl}). "
            f"Using the {conv.value} convention, the year fraction is {yf_detail}. "
            f"Interest: {formula}. "
            f"Cumulative interest to end of this period: "
            f"{_fmt_hkd(pr.cumulative_interest)}."
        )
        paragraphs.append(para)

    # Summary
    if period_results:
        first, last = period_results[0], period_results[-1]
        paragraphs.append(
            f"Total interest from {_fmt_date(first.start_date)} to "
            f"{_fmt_date(last.end_date)}: {_fmt_hkd(last.cumulative_interest)}, "
            f"giving a total amount of {_fmt_hkd(last.principal_end)}."
        )

    return paragraphs


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def run_case(
    case_name: str,
    global_settings: GlobalSettings,
    period_inputs: list,
) -> CaseResult:
    """Single function the API layer calls to compute a full case."""
    from datetime import datetime

    period_results = compute_all_periods(global_settings, period_inputs)
    total_interest = period_results[-1].cumulative_interest if period_results else Decimal("0")
    final_amount   = period_results[-1].principal_end       if period_results else global_settings.principal
    series         = daily_series(global_settings, period_results)
    explanation    = generate_explanation(global_settings, period_results)

    return CaseResult(
        case_name=case_name,
        global_settings=global_settings,
        periods=period_results,
        total_interest=total_interest,
        final_amount=final_amount,
        daily_series=series,
        explanation=explanation,
        generated_at=datetime.utcnow().isoformat() + "Z",
    )
