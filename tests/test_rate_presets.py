"""
test_rate_presets.py — Tests for CJ rate lookups and scraper parsing.
Run: python3 tests/test_rate_presets.py -v
"""

import sys
import os
import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from rate_presets import (
    get_cj_rate, get_cj_rate_pct, get_rate_table,
    rate_summary, RateEntry,
)
from rate_scraper import (
    parse_judiciary_html, compute_diff, apply_diff,
    scrape_from_html, ScrapedEntry, _parse_date, _parse_rate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_tmp_rates(entries: list[dict]) -> str:
    """Write a list of rate dicts to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(entries, f, indent=2)
    f.close()
    return f.name


# Minimal fixture: a few well-known rates for lookup tests
# Fixture matches the HTML fixture exactly (15 entries, same as _JUDICIARY_HTML_FIXTURE).
# Any test that needs a partial table creates its own temp file.
_FIXTURE_RATES = [
    {"effective_date": "2026-01-01", "rate": 8.107},
    {"effective_date": "2025-10-01", "rate": 8.250},
    {"effective_date": "2025-07-01", "rate": 8.250},
    {"effective_date": "2025-04-01", "rate": 8.276},
    {"effective_date": "2025-01-01", "rate": 8.622},
    {"effective_date": "2024-10-01", "rate": 8.875},
    {"effective_date": "2024-07-01", "rate": 8.875},
    {"effective_date": "2024-04-01", "rate": 8.875},
    {"effective_date": "2024-01-01", "rate": 8.875},
    {"effective_date": "2023-10-01", "rate": 8.798},
    {"effective_date": "2023-07-01", "rate": 8.662},
    {"effective_date": "2023-04-01", "rate": 8.583},
    {"effective_date": "2023-01-01", "rate": 8.169},
    {"effective_date": "2015-01-01", "rate": 8.000},
    {"effective_date": "2000-07-01", "rate": 11.980},  # earliest in this fixture
]

# The full HTML fixture — a minimal reproduction of the Judiciary page structure
_JUDICIARY_HTML_FIXTURE = """
<!DOCTYPE html>
<html>
<body>
<h1>Interest on Judgments and Interest Rates</h1>
<table>
  <tr>
    <th>Interest Rates on Judgment debts (% per annum)</th>
    <th>Effective Date</th>
  </tr>
  <tr><td>8.107</td><td>01-01-2026</td></tr>
  <tr><td>8.250</td><td>01-10-2025</td></tr>
  <tr><td>8.250</td><td>01-07-2025</td></tr>
  <tr><td>8.276</td><td>01-04-2025</td></tr>
  <tr><td>8.622</td><td>01-01-2025</td></tr>
  <tr><td>8.875</td><td>01-10-2024</td></tr>
  <tr><td>8.875</td><td>01-07-2024</td></tr>
  <tr><td>8.875</td><td>01-04-2024</td></tr>
  <tr><td>8.875</td><td>01-01-2024</td></tr>
  <tr><td>8.798</td><td>01-10-2023</td></tr>
  <tr><td>8.662</td><td>01-07-2023</td></tr>
  <tr><td>8.583</td><td>01-04-2023</td></tr>
  <tr><td>8.169</td><td>01-01-2023</td></tr>
  <tr><td>8.000</td><td>01-01-2015</td></tr>
  <tr><td>11.980</td><td>01-07-2000</td></tr>
</table>
</body>
</html>
"""


# ===========================================================================
# 1. rate_presets — lookup functions
# ===========================================================================

class TestGetCjRate(unittest.TestCase):

    def setUp(self):
        self.path = _write_tmp_rates(_FIXTURE_RATES)

    def tearDown(self):
        os.unlink(self.path)

    def test_exact_effective_date(self):
        """A query on the exact effective date of a rate change returns that rate."""
        rate = get_cj_rate(date(2026, 1, 1), path=self.path)
        self.assertEqual(rate, Decimal("0.08107"))

    def test_mid_quarter(self):
        """A mid-quarter date returns the most recently effective rate."""
        # 15 Nov 2025 falls in the 2025-10-01 rate period (8.250%)
        rate = get_cj_rate(date(2025, 11, 15), path=self.path)
        self.assertEqual(rate, Decimal("0.08250"))

    def test_first_day_of_new_period(self):
        """The first day of a new quarter returns the new rate, not the old one."""
        # 2025-04-01 → 8.276%; the previous rate (2025-01-01) was 8.622%
        rate = get_cj_rate(date(2025, 4, 1), path=self.path)
        self.assertEqual(rate, Decimal("0.08276"))

    def test_day_before_change(self):
        """The day before a rate change still returns the old rate."""
        # 2025-03-31 → still in 2025-01-01 period (8.622%)
        rate = get_cj_rate(date(2025, 3, 31), path=self.path)
        self.assertEqual(rate, Decimal("0.08622"))

    def test_date_within_flat_period(self):
        """A date between two known entries returns the earlier one."""
        # 2022-06-15 falls between 2023-01-01 (8.169%) and 2015-01-01 (8.000%)
        # → should return 8.000% (the most recent rate on or before 2022-06-15)
        rate = get_cj_rate(date(2022, 6, 15), path=self.path)
        self.assertEqual(rate, Decimal("0.08000"))

    def test_earliest_date_in_table(self):
        """Querying the earliest effective_date in the table returns its rate."""
        rate = get_cj_rate(date(2000, 7, 1), path=self.path)
        self.assertEqual(rate, Decimal("0.11980"))

    def test_before_earliest_raises(self):
        """A date before the earliest entry raises a descriptive ValueError."""
        with self.assertRaises(ValueError) as ctx:
            get_cj_rate(date(1999, 12, 31), path=self.path)
        self.assertIn("2000-07-01", str(ctx.exception))
        self.assertIn("Judiciary", str(ctx.exception))

    def test_returns_decimal(self):
        """Return type must be Decimal (not float)."""
        rate = get_cj_rate(date(2026, 3, 10), path=self.path)
        self.assertIsInstance(rate, Decimal)

    def test_get_cj_rate_pct_is_100x(self):
        """get_cj_rate_pct() returns percentage (fraction × 100)."""
        pct = get_cj_rate_pct(date(2026, 1, 1), path=self.path)
        self.assertEqual(pct, Decimal("8.107"))

    def test_today(self):
        """Querying today's date should work (returns most recent rate)."""
        # Use the full production file — just check it doesn't raise
        from datetime import date as today_cls
        today = today_cls.today()
        # Only run against production file if it exists
        prod_path = os.path.join(
            os.path.dirname(__file__), '..', 'data', 'cj_rates.json'
        )
        if os.path.exists(prod_path):
            rate = get_cj_rate(today, path=prod_path)
            self.assertIsInstance(rate, Decimal)
            self.assertGreater(rate, Decimal("0"))


class TestGetRateTable(unittest.TestCase):

    def test_sorted_descending(self):
        path = _write_tmp_rates(_FIXTURE_RATES)
        try:
            table = get_rate_table(path=path)
            dates = [e.effective_date for e in table]
            self.assertEqual(dates, sorted(dates, reverse=True))
        finally:
            os.unlink(path)

    def test_entry_fields(self):
        path = _write_tmp_rates(_FIXTURE_RATES)
        try:
            table = get_rate_table(path=path)
            first = table[0]
            self.assertEqual(first.effective_date, date(2026, 1, 1))
            self.assertEqual(first.rate_pct, Decimal("8.107"))
            self.assertEqual(first.rate, Decimal("0.08107"))
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            get_rate_table(path="/nonexistent/path/cj_rates.json")

    def test_malformed_entry_raises(self):
        path = _write_tmp_rates([{"effective_date": "not-a-date", "rate": 8.0}])
        try:
            with self.assertRaises(ValueError):
                get_rate_table(path=path)
        finally:
            os.unlink(path)


class TestRateSummary(unittest.TestCase):

    def test_summary_structure(self):
        path = _write_tmp_rates(_FIXTURE_RATES)
        try:
            s = rate_summary(path=path)
            self.assertIn("count", s)
            self.assertIn("earliest_date", s)
            self.assertIn("latest_date", s)
            self.assertIn("latest_rate_pct", s)
            self.assertIn("entries", s)
            self.assertEqual(s["count"], len(_FIXTURE_RATES))
            self.assertEqual(s["latest_date"], "2026-01-01")
            self.assertEqual(s["earliest_date"], "2000-07-01")
            self.assertAlmostEqual(s["latest_rate_pct"], 8.107, places=3)
        finally:
            os.unlink(path)

    def test_entries_are_descending(self):
        path = _write_tmp_rates(_FIXTURE_RATES)
        try:
            s = rate_summary(path=path)
            dates = [e["effective_date"] for e in s["entries"]]
            self.assertEqual(dates, sorted(dates, reverse=True))
        finally:
            os.unlink(path)


# ===========================================================================
# 2. rate_scraper — HTML parsing
# ===========================================================================

class TestParseJudiciaryHtml(unittest.TestCase):

    def test_parses_all_rows(self):
        entries = parse_judiciary_html(_JUDICIARY_HTML_FIXTURE)
        self.assertEqual(len(entries), 15)

    def test_sorted_descending(self):
        entries = parse_judiciary_html(_JUDICIARY_HTML_FIXTURE)
        dates = [e.effective_date for e in entries]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_most_recent_entry(self):
        entries = parse_judiciary_html(_JUDICIARY_HTML_FIXTURE)
        self.assertEqual(entries[0].effective_date, date(2026, 1, 1))
        self.assertEqual(entries[0].rate_pct, Decimal("8.107"))

    def test_earliest_entry(self):
        entries = parse_judiciary_html(_JUDICIARY_HTML_FIXTURE)
        self.assertEqual(entries[-1].effective_date, date(2000, 7, 1))
        self.assertEqual(entries[-1].rate_pct, Decimal("11.980"))

    def test_returns_scraped_entry_objects(self):
        entries = parse_judiciary_html(_JUDICIARY_HTML_FIXTURE)
        for e in entries:
            self.assertIsInstance(e, ScrapedEntry)
            self.assertIsInstance(e.effective_date, date)
            self.assertIsInstance(e.rate_pct, Decimal)

    def test_no_table_raises(self):
        with self.assertRaises(ValueError) as ctx:
            parse_judiciary_html("<html><body><p>No table here</p></body></html>")
        self.assertIn("table", str(ctx.exception).lower())

    def test_empty_table_raises(self):
        html = """
        <html><body>
        <table>
          <tr><th>Interest Rates on Judgment debts</th><th>Effective Date</th></tr>
        </table>
        </body></html>
        """
        with self.assertRaises(ValueError):
            parse_judiciary_html(html)

    def test_extra_whitespace_in_cells_tolerated(self):
        html = """
        <table>
          <tr><th>Interest Rates on Judgment debts</th><th>Effective Date</th></tr>
          <tr><td>  8.107  </td><td>  01-01-2026  </td></tr>
        </table>
        """
        entries = parse_judiciary_html(html)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].rate_pct, Decimal("8.107"))


class TestParseHelpers(unittest.TestCase):

    def test_parse_date_dd_mm_yyyy(self):
        self.assertEqual(_parse_date("01-01-2026"), date(2026, 1, 1))
        self.assertEqual(_parse_date("01-10-2025"), date(2025, 10, 1))

    def test_parse_date_iso(self):
        self.assertEqual(_parse_date("2026-01-01"), date(2026, 1, 1))

    def test_parse_date_invalid(self):
        with self.assertRaises(ValueError):
            _parse_date("not-a-date")

    def test_parse_rate_normal(self):
        self.assertEqual(_parse_rate("8.107"), Decimal("8.107"))
        self.assertEqual(_parse_rate("11.980"), Decimal("11.980"))

    def test_parse_rate_integer(self):
        self.assertEqual(_parse_rate("8"), Decimal("8"))

    def test_parse_rate_invalid(self):
        with self.assertRaises(ValueError):
            _parse_rate("not-a-number")


# ===========================================================================
# 3. Diff and apply
# ===========================================================================

class TestComputeDiff(unittest.TestCase):

    def test_no_new_entries_when_all_present(self):
        path = _write_tmp_rates(_FIXTURE_RATES)
        try:
            scraped = parse_judiciary_html(_JUDICIARY_HTML_FIXTURE)
            # The fixture HTML matches the fixture JSON, so diff should be empty
            diff = compute_diff(scraped, existing_path=path)
            self.assertEqual(diff, [])
        finally:
            os.unlink(path)

    def test_detects_new_entries(self):
        # Existing file is missing the 2026-01-01 entry
        existing = [e for e in _FIXTURE_RATES if e["effective_date"] != "2026-01-01"]
        path = _write_tmp_rates(existing)
        try:
            scraped = parse_judiciary_html(_JUDICIARY_HTML_FIXTURE)
            diff = compute_diff(scraped, existing_path=path)
            self.assertEqual(len(diff), 1)
            self.assertEqual(diff[0].effective_date, date(2026, 1, 1))
            self.assertEqual(diff[0].rate_pct, Decimal("8.107"))
        finally:
            os.unlink(path)

    def test_empty_existing_file_returns_all(self):
        path = _write_tmp_rates([])
        try:
            scraped = parse_judiciary_html(_JUDICIARY_HTML_FIXTURE)
            diff = compute_diff(scraped, existing_path=path)
            self.assertEqual(len(diff), len(scraped))
        finally:
            os.unlink(path)

    def test_missing_file_treated_as_empty(self):
        scraped = parse_judiciary_html(_JUDICIARY_HTML_FIXTURE)
        diff = compute_diff(scraped, existing_path="/nonexistent/file.json")
        self.assertEqual(len(diff), len(scraped))

    def test_diff_sorted_descending(self):
        existing = [e for e in _FIXTURE_RATES
                    if e["effective_date"] not in ("2026-01-01", "2025-10-01")]
        path = _write_tmp_rates(existing)
        try:
            scraped = parse_judiciary_html(_JUDICIARY_HTML_FIXTURE)
            diff = compute_diff(scraped, existing_path=path)
            self.assertEqual(len(diff), 2)
            self.assertGreater(diff[0].effective_date, diff[1].effective_date)
        finally:
            os.unlink(path)


class TestApplyDiff(unittest.TestCase):

    def test_apply_writes_new_entries(self):
        existing = [e for e in _FIXTURE_RATES if e["effective_date"] != "2026-01-01"]
        path = _write_tmp_rates(existing)
        try:
            new_entries = [ScrapedEntry(date(2026, 1, 1), Decimal("8.107"))]
            result = apply_diff(new_entries, existing_path=path)
            self.assertEqual(result["applied"], 1)
            self.assertEqual(result["total"], len(_FIXTURE_RATES))
            self.assertIn("2026-01-01", result["new_dates"])

            # Verify the file was actually updated
            with open(path) as f:
                saved = json.load(f)
            saved_dates = [e["effective_date"] for e in saved]
            self.assertIn("2026-01-01", saved_dates)
        finally:
            os.unlink(path)

    def test_apply_empty_diff_is_noop(self):
        path = _write_tmp_rates(_FIXTURE_RATES)
        try:
            mtime_before = os.path.getmtime(path)
            result = apply_diff([], existing_path=path)
            self.assertEqual(result["applied"], 0)
        finally:
            os.unlink(path)

    def test_apply_preserves_sort_order(self):
        path = _write_tmp_rates([{"effective_date": "2025-01-01", "rate": 8.622}])
        try:
            new_entries = [
                ScrapedEntry(date(2026, 1, 1), Decimal("8.107")),
                ScrapedEntry(date(2024, 10, 1), Decimal("8.875")),
            ]
            apply_diff(new_entries, existing_path=path)
            with open(path) as f:
                saved = json.load(f)
            dates = [e["effective_date"] for e in saved]
            self.assertEqual(dates, sorted(dates, reverse=True))
        finally:
            os.unlink(path)

    def test_apply_does_not_duplicate(self):
        """Calling apply_diff twice with the same entries should not duplicate."""
        path = _write_tmp_rates([{"effective_date": "2025-01-01", "rate": 8.622}])
        try:
            new_entries = [ScrapedEntry(date(2026, 1, 1), Decimal("8.107"))]
            apply_diff(new_entries, existing_path=path)
            apply_diff(new_entries, existing_path=path)  # second call
            with open(path) as f:
                saved = json.load(f)
            dates = [e["effective_date"] for e in saved]
            self.assertEqual(len(dates), len(set(dates)))  # no duplicates
        finally:
            os.unlink(path)


# ===========================================================================
# 4. scrape_from_html end-to-end
# ===========================================================================

class TestScrapeFromHtml(unittest.TestCase):

    def test_returns_all_and_diff(self):
        # Use an existing file that is missing the 2026-01-01 entry
        existing = [e for e in _FIXTURE_RATES if e["effective_date"] != "2026-01-01"]
        path = _write_tmp_rates(existing)
        try:
            # Temporarily monkey-patch the default path in rate_scraper
            import rate_scraper
            original = rate_scraper._RATES_FILE
            rate_scraper._RATES_FILE = path

            all_entries, diff = scrape_from_html(_JUDICIARY_HTML_FIXTURE)
            self.assertGreater(len(all_entries), 0)
            self.assertEqual(len(diff), 1)
            self.assertEqual(diff[0].effective_date, date(2026, 1, 1))

            rate_scraper._RATES_FILE = original
        finally:
            os.unlink(path)

    def test_lookup_after_apply(self):
        """Full round-trip: scrape → diff → apply → lookup returns new rate."""
        existing = [e for e in _FIXTURE_RATES if e["effective_date"] != "2026-01-01"]
        path = _write_tmp_rates(existing)
        try:
            import rate_scraper
            original = rate_scraper._RATES_FILE
            rate_scraper._RATES_FILE = path

            all_entries, diff = scrape_from_html(_JUDICIARY_HTML_FIXTURE)
            apply_diff(diff, existing_path=path)

            # Now lookup should find the new rate
            rate = get_cj_rate(date(2026, 3, 10), path=path)
            self.assertEqual(rate, Decimal("0.08107"))

            rate_scraper._RATES_FILE = original
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
