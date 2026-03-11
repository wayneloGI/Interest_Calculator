"""
test_calculator.py — Unit tests for the judgment interest calculation engine.
Runs with Python's built-in unittest (no external test runner required).

Run:  python3 tests/test_calculator.py -v

Regression cases
----------------
A  Easy Policy Finance Ltd v 陳海濱 [2025] HKCFI 4295
     Principal: HK$10,765,000
     Spreadsheet settings:
       Period 1: 21 Aug 2015→20 Aug 2021, 5% pa, simple, initial principal,
                 Actual/365 Fixed, include start+end
                 Expected interest: HK$3,232,449.32
       Period 2: 20 Aug 2021→22 Sep 2025, 24% pa, simple, initial principal,
                 Actual/365 Fixed, exclude start, include end
                 Expected interest: HK$10,575,064.11
     Actual judgment rates (both periods at 24% pa):
       Period 2 interest still: HK$10,575,064.11

B  Waddington — 2.5% pa, single period, Actual/365 Fixed

C  Compound interest — 24% pa monthly over 3 years
     EPR = (1.02)^36 − 1 ≈ 96.9742%
"""

import sys
import os
import unittest
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from calculator import (
    DayCountConvention, InterestType, InterestBasis,
    RateBasis, CompoundingFreq,
    GlobalSettings, PeriodInput,
    compute_days, annualise_rate, year_fraction, effective_period_rate,
    compute_period, compute_all_periods, generate_explanation, run_case,
    _eff_start, _eff_end,
)

D = Decimal  # shorthand


# ===========================================================================
# 1. compute_days
# ===========================================================================

class TestComputeDays(unittest.TestCase):

    def test_both_included(self):
        # 21 Aug 2015 to 20 Aug 2021: 2191 calendar days + 1 = 2192
        self.assertEqual(compute_days(date(2015,8,21), date(2021,8,20), True, True), 2192)

    def test_easy_policy_period2(self):
        # 20 Aug 2021 to 22 Sep 2025: exclude start, include end → 1494
        self.assertEqual(compute_days(date(2021,8,20), date(2025,9,22), False, True), 1494)

    def test_start_only(self):
        d1, d2 = date(2020,1,1), date(2020,12,31)
        raw = (d2 - d1).days  # 365
        self.assertEqual(compute_days(d1, d2, True, False), raw)

    def test_end_only(self):
        d1, d2 = date(2020,1,1), date(2020,12,31)
        raw = (d2 - d1).days
        self.assertEqual(compute_days(d1, d2, False, True), raw)

    def test_neither(self):
        d1, d2 = date(2020,1,1), date(2020,12,31)
        raw = (d2 - d1).days
        self.assertEqual(compute_days(d1, d2, False, False), raw - 1)

    def test_single_day_both_included(self):
        d = date(2024,6,1)
        self.assertEqual(compute_days(d, d, True, True), 1)

    def test_single_day_neither(self):
        d = date(2024,6,1)
        self.assertEqual(compute_days(d, d, False, False), 0)

    def test_adjacent_both_excluded(self):
        self.assertEqual(compute_days(date(2024,1,1), date(2024,1,2), False, False), 0)

    def test_never_negative(self):
        # Even a pathological case (same date, neither included) returns 0
        d = date(2024,1,1)
        self.assertGreaterEqual(compute_days(d, d, False, False), 0)


# ===========================================================================
# 2. annualise_rate
# ===========================================================================

class TestAnnualiseRate(unittest.TestCase):

    def test_per_annum_unchanged(self):
        self.assertEqual(annualise_rate(D("0.24"), RateBasis.PER_ANNUM), D("0.24"))

    def test_per_month_times_12(self):
        self.assertEqual(annualise_rate(D("0.02"), RateBasis.PER_MONTH), D("0.24"))

    def test_per_quarter_times_4(self):
        self.assertEqual(annualise_rate(D("0.06"), RateBasis.PER_QUARTER), D("0.24"))

    def test_per_day_times_365(self):
        daily = D("0.05") / D("365")
        result = annualise_rate(daily, RateBasis.PER_DAY)
        self.assertAlmostEqual(float(result), 0.05, places=6)

    def test_zero_rate(self):
        self.assertEqual(annualise_rate(D("0"), RateBasis.PER_ANNUM), D("0"))


# ===========================================================================
# 3. year_fraction
# ===========================================================================

class TestYearFraction(unittest.TestCase):

    # --- Actual/365 Fixed ---

    def test_actual365_easy_policy_p1(self):
        # Period 1: eff_start=21 Aug 2015, eff_end=21 Aug 2021 (incl end → +1 day)
        # 2192 days / 365
        eff_s = date(2015, 8, 21)
        eff_e = date(2021, 8, 21)
        yf, wy, sd = year_fraction(eff_s, eff_e, DayCountConvention.ACTUAL_365_FIXED)
        expected = D("2192") / D("365")
        self.assertAlmostEqual(float(yf), float(expected), places=6)
        self.assertEqual(wy, 0)
        self.assertEqual(sd, 0)

    def test_actual365_easy_policy_p2(self):
        # Period 2: eff_start=21 Aug 2021 (excl start +1), eff_end=23 Sep 2025 (incl end +1)
        # 1494 days / 365
        eff_s = date(2021, 8, 21)
        eff_e = date(2025, 9, 23)
        yf, wy, sd = year_fraction(eff_s, eff_e, DayCountConvention.ACTUAL_365_FIXED)
        expected = D("1494") / D("365")
        self.assertAlmostEqual(float(yf), float(expected), places=6)

    def test_actual365_zero(self):
        d = date(2024, 1, 1)
        yf, wy, sd = year_fraction(d, d, DayCountConvention.ACTUAL_365_FIXED)
        self.assertEqual(yf, D("0"))

    # --- Anniversary/365 ---

    def test_anniversary_exact_6_years(self):
        yf, wy, sd = year_fraction(
            date(2015,8,21), date(2021,8,21), DayCountConvention.ANNIVERSARY_365
        )
        self.assertEqual(wy, 6)
        self.assertEqual(sd, 0)
        self.assertEqual(yf, D("6"))

    def test_anniversary_with_stub(self):
        # 21 Aug 2015 → 5 Sep 2021 = 6 years + 15 stub days
        yf, wy, sd = year_fraction(
            date(2015,8,21), date(2021,9,5), DayCountConvention.ANNIVERSARY_365
        )
        self.assertEqual(wy, 6)
        self.assertEqual(sd, 15)
        expected = D("6") + D("15") / D("365")
        self.assertEqual(yf, expected)

    def test_anniversary_under_1_year(self):
        yf, wy, sd = year_fraction(
            date(2024,1,1), date(2024,7,1), DayCountConvention.ANNIVERSARY_365
        )
        self.assertEqual(wy, 0)
        self.assertEqual(sd, 182)
        self.assertEqual(yf, D("182") / D("365"))

    # --- Actual/Actual ---

    def test_actual_actual_full_non_leap_year(self):
        yf, _, _ = year_fraction(
            date(2019,1,1), date(2020,1,1), DayCountConvention.ACTUAL_ACTUAL
        )
        self.assertEqual(yf, D("1"))

    def test_actual_actual_full_leap_year(self):
        yf, _, _ = year_fraction(
            date(2020,1,1), date(2021,1,1), DayCountConvention.ACTUAL_ACTUAL
        )
        self.assertEqual(yf, D("1"))

    def test_actual_actual_straddles_leap(self):
        # 1 Jul 2019 → 1 Jul 2020: 184 days in 2019 (365-day), 182 in 2020 (366-day)
        yf, _, _ = year_fraction(
            date(2019,7,1), date(2020,7,1), DayCountConvention.ACTUAL_ACTUAL
        )
        expected = D("184") / D("365") + D("182") / D("366")
        self.assertAlmostEqual(float(yf), float(expected), places=8)


# ===========================================================================
# 4. effective_period_rate
# ===========================================================================

class TestEffectivePeriodRate(unittest.TestCase):

    def test_simple_1_year(self):
        epr = effective_period_rate(D("0.24"), D("1"), InterestType.SIMPLE, CompoundingFreq.ANNUAL)
        self.assertAlmostEqual(float(epr), 0.24, places=7)

    def test_simple_easy_policy_p1(self):
        # 5% × (2192/365) = 0.3002739726...
        yf = D("2192") / D("365")
        epr = effective_period_rate(D("0.05"), yf, InterestType.SIMPLE, CompoundingFreq.ANNUAL)
        self.assertAlmostEqual(float(epr), 0.3002739726, places=6)

    def test_compound_monthly_3_years(self):
        # (1.02)^36 − 1
        expected = 1.02 ** 36 - 1
        epr = effective_period_rate(D("0.24"), D("3"), InterestType.COMPOUND, CompoundingFreq.MONTHLY)
        self.assertAlmostEqual(float(epr), expected, places=6)

    def test_compound_quarterly_1_year(self):
        # (1.03)^4 − 1
        expected = 1.03 ** 4 - 1
        epr = effective_period_rate(D("0.12"), D("1"), InterestType.COMPOUND, CompoundingFreq.QUARTERLY)
        self.assertAlmostEqual(float(epr), expected, places=6)

    def test_compound_semi_annual(self):
        # (1.05)^2 − 1 = 0.1025
        epr = effective_period_rate(D("0.10"), D("1"), InterestType.COMPOUND, CompoundingFreq.SEMI_ANNUAL)
        self.assertAlmostEqual(float(epr), 0.1025, places=7)

    def test_compound_annual_equals_rate(self):
        epr = effective_period_rate(D("0.10"), D("1"), InterestType.COMPOUND, CompoundingFreq.ANNUAL)
        self.assertAlmostEqual(float(epr), 0.10, places=7)

    def test_zero_rate(self):
        epr = effective_period_rate(D("0"), D("5"), InterestType.SIMPLE, CompoundingFreq.ANNUAL)
        self.assertEqual(epr, D("0"))

    def test_zero_year_fraction(self):
        epr = effective_period_rate(D("0.24"), D("0"), InterestType.COMPOUND, CompoundingFreq.MONTHLY)
        self.assertAlmostEqual(float(epr), 0.0, places=7)


# ===========================================================================
# 5. Single period
# ===========================================================================

class TestComputePeriod(unittest.TestCase):

    def _run_p1_5pct(self):
        pi = PeriodInput(
            end_date=date(2021,8,20),
            interest_type=InterestType.SIMPLE,
            interest_basis=InterestBasis.INITIAL_PRINCIPAL,
            nominal_rate=D("0.05"),
            rate_basis=RateBasis.PER_ANNUM,
            include_start_day=True,
            include_end_day=True,
        )
        return compute_period(
            period_id=1,
            start_date=date(2015,8,21),
            period_input=pi,
            principal_start=D("10765000"),
            initial_principal=D("10765000"),
            cumulative_interest_before=D("0"),
            convention=DayCountConvention.ACTUAL_365_FIXED,
        )

    def test_p1_days(self):
        self.assertEqual(self._run_p1_5pct().days, 2192)

    def test_p1_interest(self):
        # 10,765,000 × 5% × (2192/365) = 3,232,449.32
        self.assertEqual(self._run_p1_5pct().interest, D("3232449.32"))

    def test_p1_principal_end(self):
        self.assertEqual(self._run_p1_5pct().principal_end, D("13997449.32"))

    def test_zero_rate_period(self):
        pi = PeriodInput(
            end_date=date(2022,1,1),
            interest_type=InterestType.SIMPLE,
            interest_basis=InterestBasis.INITIAL_PRINCIPAL,
            nominal_rate=D("0"),
            rate_basis=RateBasis.PER_ANNUM,
        )
        result = compute_period(1, date(2021,1,1), pi, D("1000000"), D("1000000"),
                                D("0"), DayCountConvention.ACTUAL_365_FIXED)
        self.assertEqual(result.interest, D("0.00"))
        self.assertEqual(result.principal_end, D("1000000.00"))

    def test_running_sum_uses_principal_start(self):
        """Running Sum basis should multiply principal_start, not initial_principal.
        Use include_end=False so the period is exactly 365 days → yf = 1.0."""
        pi = PeriodInput(
            end_date=date(2022,1,1),
            interest_type=InterestType.SIMPLE,
            interest_basis=InterestBasis.RUNNING_SUM,
            nominal_rate=D("0.10"),
            rate_basis=RateBasis.PER_ANNUM,
            include_start_day=True,
            include_end_day=False,   # 365 days exactly → yf = 1.0
        )
        # principal_start = 1,200,000 but initial_principal = 1,000,000
        result = compute_period(2, date(2021,1,1), pi,
                                D("1200000"), D("1000000"),
                                D("0"), DayCountConvention.ACTUAL_365_FIXED)
        # Interest base must be 1,200,000 (running sum); yf = 365/365 = 1.0
        expected_interest = (D("1200000") * D("0.10")).quantize(D("0.01"))
        self.assertEqual(result.interest, expected_interest)

    def test_initial_principal_basis_ignores_principal_start(self):
        """Initial Principal basis always uses P₀, even when principal_start differs.
        Use include_end=False so yf = 1.0 exactly."""
        pi = PeriodInput(
            end_date=date(2022,1,1),
            interest_type=InterestType.SIMPLE,
            interest_basis=InterestBasis.INITIAL_PRINCIPAL,
            nominal_rate=D("0.10"),
            rate_basis=RateBasis.PER_ANNUM,
            include_start_day=True,
            include_end_day=False,   # 365 days → yf = 1.0
        )
        result = compute_period(2, date(2021,1,1), pi,
                                D("1200000"), D("1000000"),
                                D("0"), DayCountConvention.ACTUAL_365_FIXED)
        # Interest base must be 1,000,000 (initial principal)
        expected_interest = (D("1000000") * D("0.10")).quantize(D("0.01"))
        self.assertEqual(result.interest, expected_interest)


# ===========================================================================
# 6. Full case regressions
# ===========================================================================

class TestFullCaseRegressions(unittest.TestCase):

    def _easy_policy_gs(self):
        return GlobalSettings(
            principal=D("10765000"),
            start_date=date(2015,8,21),
            day_count_convention=DayCountConvention.ACTUAL_365_FIXED,
        )

    def test_easy_policy_spreadsheet_settings(self):
        """
        Exact spreadsheet configuration (5% then 24% pa).
        Verified against spreadsheet outputs.
        """
        gs = self._easy_policy_gs()
        periods = [
            PeriodInput(end_date=date(2021,8,20), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.05"), rate_basis=RateBasis.PER_ANNUM,
                        include_start_day=True, include_end_day=True),
            PeriodInput(end_date=date(2025,9,22), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.24"), rate_basis=RateBasis.PER_ANNUM,
                        include_start_day=False, include_end_day=True),
        ]
        results = compute_all_periods(gs, periods)

        self.assertEqual(results[0].interest, D("3232449.32"))
        self.assertEqual(results[1].interest, D("10575064.11"))
        # Total: 3,232,449.32 + 10,575,064.11 = 13,807,513.43
        self.assertEqual(results[1].cumulative_interest, D("13807513.43"))
        self.assertEqual(results[1].principal_end, D("24572513.43"))

    def test_easy_policy_period2_at_24pct(self):
        """
        Period 2 interest is the primary judgment-verified figure.
        10,765,000 × 24% × (1494/365) = 10,575,064.11
        """
        gs = self._easy_policy_gs()
        periods = [
            PeriodInput(end_date=date(2021,8,20), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.24"), rate_basis=RateBasis.PER_ANNUM,
                        include_start_day=True, include_end_day=True),
            PeriodInput(end_date=date(2025,9,22), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.24"), rate_basis=RateBasis.PER_ANNUM,
                        include_start_day=False, include_end_day=True),
        ]
        results = compute_all_periods(gs, periods)
        self.assertEqual(results[1].interest, D("10575064.11"))

    def test_waddington(self):
        """
        2.5% pa simple, Actual/365 Fixed, on HK$33,511,220.85
        Period: 18 Dec 2013 → 18 Dec 2015, include start + include end → 731 days
        Interest = 33,511,220.85 × 2.5% × (731/365)
        """
        gs = GlobalSettings(
            principal=D("33511220.85"),
            start_date=date(2013,12,18),
            day_count_convention=DayCountConvention.ACTUAL_365_FIXED,
        )
        periods = [
            PeriodInput(end_date=date(2015,12,18), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.025"), rate_basis=RateBasis.PER_ANNUM,
                        include_start_day=True, include_end_day=True),
        ]
        results = compute_all_periods(gs, periods)
        self.assertEqual(results[0].days, 731)
        from decimal import ROUND_HALF_UP
        expected = (D("33511220.85") * D("0.025") * D("731") / D("365")).quantize(
            D("0.01"), rounding=ROUND_HALF_UP
        )
        self.assertEqual(results[0].interest, expected)

    def test_compound_monthly_3_years(self):
        """
        24% pa compounded monthly, exactly 3 years.
        EPR = (1.02)^36 − 1 ≈ 96.9742%
        Use 2021-01-01 → 2024-01-01: three non-leap years = 1095 days, yf = 3.0 exactly.
        """
        gs = GlobalSettings(
            principal=D("1000000"),
            start_date=date(2021,1,1),
            day_count_convention=DayCountConvention.ACTUAL_365_FIXED,
        )
        periods = [
            PeriodInput(end_date=date(2024,1,1), interest_type=InterestType.COMPOUND,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.24"), rate_basis=RateBasis.PER_ANNUM,
                        compounding_freq=CompoundingFreq.MONTHLY,
                        include_start_day=True, include_end_day=False),
        ]
        results = compute_all_periods(gs, periods)
        self.assertEqual(results[0].days, 1095)  # 365 × 3
        epr_exact = D(str(1.02 ** 36 - 1))
        theoretical = (D("1000000") * epr_exact).quantize(D("0.01"))
        self.assertAlmostEqual(float(results[0].interest), float(theoretical), delta=0.02)

    def test_zero_rate_between_periods_chain_intact(self):
        """A zero-rate period must not break the principal chain."""
        gs = GlobalSettings(
            principal=D("1000000"),
            start_date=date(2020,1,1),
            day_count_convention=DayCountConvention.ACTUAL_365_FIXED,
        )
        periods = [
            PeriodInput(end_date=date(2021,1,1), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.08"), rate_basis=RateBasis.PER_ANNUM),
            PeriodInput(end_date=date(2022,1,1), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0"),    rate_basis=RateBasis.PER_ANNUM),
            PeriodInput(end_date=date(2023,1,1), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.08"), rate_basis=RateBasis.PER_ANNUM),
        ]
        results = compute_all_periods(gs, periods)

        self.assertEqual(results[1].interest, D("0.00"))
        self.assertEqual(results[2].principal_start, results[1].principal_end)
        self.assertGreater(results[2].cumulative_interest, results[1].cumulative_interest)

    def test_large_principal_no_overflow(self):
        """HK$1 billion — no precision errors visible at 2 d.p."""
        gs = GlobalSettings(
            principal=D("1000000000"),
            start_date=date(2020,1,1),
            day_count_convention=DayCountConvention.ACTUAL_365_FIXED,
        )
        periods = [
            PeriodInput(end_date=date(2025,1,1), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.08"), rate_basis=RateBasis.PER_ANNUM),
        ]
        results = compute_all_periods(gs, periods)
        # Must be rounded to 2 d.p.
        self.assertEqual(results[0].interest,
                         results[0].interest.quantize(D("0.01")))
        # Roughly 5 years × 8% × 1B = ~400M
        self.assertGreater(results[0].interest, D("390000000"))
        self.assertLess(results[0].interest,    D("410000000"))

    def test_principal_chain_across_periods(self):
        """Principal_start of period N must equal principal_end of period N-1."""
        gs = GlobalSettings(
            principal=D("500000"),
            start_date=date(2020,1,1),
            day_count_convention=DayCountConvention.ACTUAL_365_FIXED,
        )
        periods = [
            PeriodInput(end_date=date(2021,1,1), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.RUNNING_SUM,
                        nominal_rate=D("0.10"), rate_basis=RateBasis.PER_ANNUM),
            PeriodInput(end_date=date(2022,1,1), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.RUNNING_SUM,
                        nominal_rate=D("0.10"), rate_basis=RateBasis.PER_ANNUM),
            PeriodInput(end_date=date(2023,1,1), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.RUNNING_SUM,
                        nominal_rate=D("0.10"), rate_basis=RateBasis.PER_ANNUM),
        ]
        results = compute_all_periods(gs, periods)
        for i in range(1, len(results)):
            self.assertEqual(results[i].principal_start, results[i-1].principal_end,
                             f"Chain broken at period {i+1}")


# ===========================================================================
# 7. Explanation generator
# ===========================================================================

class TestGenerateExplanation(unittest.TestCase):

    def _two_period_case(self):
        gs = GlobalSettings(
            principal=D("10765000"),
            start_date=date(2015,8,21),
            day_count_convention=DayCountConvention.ACTUAL_365_FIXED,
        )
        periods = [
            PeriodInput(end_date=date(2021,8,20), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.05"), rate_basis=RateBasis.PER_ANNUM),
            PeriodInput(end_date=date(2025,9,22), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.24"), rate_basis=RateBasis.PER_ANNUM,
                        include_start_day=False, include_end_day=True),
        ]
        results = compute_all_periods(gs, periods)
        return gs, results

    def test_paragraph_count(self):
        gs, results = self._two_period_case()
        paras = generate_explanation(gs, results)
        # 1 preamble + 2 periods + 1 summary = 4
        self.assertEqual(len(paras), 4)

    def test_summary_mentions_total_interest(self):
        gs, results = self._two_period_case()
        paras = generate_explanation(gs, results)
        summary = paras[-1]
        self.assertIn("HK$", summary)
        self.assertIn("total", summary.lower())

    def test_period_paragraph_mentions_days(self):
        gs, results = self._two_period_case()
        paras = generate_explanation(gs, results)
        # Period 1: 2192 days
        self.assertIn("2192 interest days", paras[1])

    def test_compound_paragraph_mentions_compounding(self):
        gs = GlobalSettings(principal=D("1000000"), start_date=date(2020,1,1),
                            day_count_convention=DayCountConvention.ACTUAL_365_FIXED)
        periods = [PeriodInput(end_date=date(2023,1,1), interest_type=InterestType.COMPOUND,
                               interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                               nominal_rate=D("0.24"), rate_basis=RateBasis.PER_ANNUM,
                               compounding_freq=CompoundingFreq.MONTHLY)]
        results = compute_all_periods(gs, periods)
        paras = generate_explanation(gs, results)
        self.assertIn("monthly", paras[1].lower())
        self.assertIn("compound", paras[1].lower())

    def test_preamble_contains_convention(self):
        gs, results = self._two_period_case()
        paras = generate_explanation(gs, results)
        self.assertIn("Actual/365 Fixed", paras[0])


# ===========================================================================
# 8. run_case integration
# ===========================================================================

class TestRunCase(unittest.TestCase):

    def test_structure(self):
        gs = GlobalSettings(
            principal=D("10765000"),
            start_date=date(2015,8,21),
            day_count_convention=DayCountConvention.ACTUAL_365_FIXED,
        )
        periods = [
            PeriodInput(end_date=date(2021,8,20), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.05"), rate_basis=RateBasis.PER_ANNUM),
        ]
        result = run_case("Test Case", gs, periods)

        self.assertEqual(result.case_name, "Test Case")
        self.assertEqual(len(result.periods), 1)
        self.assertEqual(result.total_interest, result.periods[-1].cumulative_interest)
        self.assertEqual(result.final_amount,   result.periods[-1].principal_end)
        self.assertGreater(len(result.daily_series), 0)
        self.assertEqual(len(result.explanation), 3)  # preamble + 1 period + summary
        self.assertTrue(result.generated_at.endswith("Z"))

    def test_daily_series_length(self):
        """Daily series should have one entry per calendar day in the case."""
        gs = GlobalSettings(
            principal=D("1000000"),
            start_date=date(2020,1,1),
            day_count_convention=DayCountConvention.ACTUAL_365_FIXED,
        )
        periods = [
            PeriodInput(end_date=date(2022,1,1), interest_type=InterestType.SIMPLE,
                        interest_basis=InterestBasis.INITIAL_PRINCIPAL,
                        nominal_rate=D("0.08"), rate_basis=RateBasis.PER_ANNUM),
        ]
        result = run_case("Daily Test", gs, periods)
        # 2020: 366 days, 2021: 365 days = 731 days, plus the final endpoint = 732
        self.assertEqual(len(result.daily_series), 732)


if __name__ == "__main__":
    unittest.main(verbosity=2)
