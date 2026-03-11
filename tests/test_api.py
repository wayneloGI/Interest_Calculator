"""
test_api.py — Integration tests for the FastAPI application.
Run: python3 tests/test_api.py -v

These tests exercise the full HTTP layer (routing, auth, serialisation)
using FastAPI's built-in TestClient (which wraps httpx).

The calculator and rate lookup are NOT mocked — tests run against the real
engine and the production cj_rates.json, which means they also serve as
end-to-end regression tests.
"""

import sys
import os
import json
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

# Set a test API key before importing the app
os.environ["APP_API_KEY"] = "test-secret-key-12345"

from fastapi.testclient import TestClient
from main import app

client = TestClient(app, raise_server_exceptions=True)
HEADERS = {"X-API-Key": "test-secret-key-12345"}
BAD_HEADERS = {"X-API-Key": "wrong-key"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Easy Policy Finance Ltd v 陳海濱 [2025] HKCFI 4295
# Spreadsheet settings: Period 1 @ 5%, Period 2 @ 24%
EASY_POLICY_PAYLOAD = {
    "case_name": "Easy Policy Finance Ltd v 陳海濱",
    "principal": "10765000.00",
    "start_date": "2015-08-21",
    "day_count_convention": "Actual/365 Fixed",
    "periods": [
        {
            "end_date": "2021-08-20",
            "interest_type": "Simple",
            "interest_basis": "Initial Principal",
            "nominal_rate": "0.05",
            "rate_basis": "Per annum",
            "include_start_day": True,
            "include_end_day": True,
        },
        {
            "end_date": "2025-09-22",
            "interest_type": "Simple",
            "interest_basis": "Initial Principal",
            "nominal_rate": "0.24",
            "rate_basis": "Per annum",
            "include_start_day": False,
            "include_end_day": True,
        },
    ],
    "include_daily_series": False,  # keep response small in tests
}

MINIMAL_PAYLOAD = {
    "principal": "1000000.00",
    "start_date": "2020-01-01",
    "day_count_convention": "Actual/365 Fixed",
    "periods": [
        {
            "end_date": "2021-01-01",
            "interest_type": "Simple",
            "interest_basis": "Initial Principal",
            "nominal_rate": "0.08",
            "rate_basis": "Per annum",
        }
    ],
    "include_daily_series": False,
}


# ===========================================================================
# 1. Authentication
# ===========================================================================

class TestAuthentication(unittest.TestCase):

    def test_missing_key_returns_401(self):
        r = client.post("/api/calculate", json=MINIMAL_PAYLOAD)
        self.assertEqual(r.status_code, 401)

    def test_wrong_key_returns_401(self):
        r = client.post("/api/calculate", json=MINIMAL_PAYLOAD, headers=BAD_HEADERS)
        self.assertEqual(r.status_code, 401)

    def test_correct_key_accepted(self):
        r = client.post("/api/calculate", json=MINIMAL_PAYLOAD, headers=HEADERS)
        self.assertEqual(r.status_code, 200)

    def test_settings_requires_auth(self):
        r = client.get("/api/settings/rates")
        self.assertEqual(r.status_code, 401)

    def test_cj_rate_requires_auth(self):
        r = client.get("/api/rate-presets/cj?query_date=2025-06-15")
        self.assertEqual(r.status_code, 401)


# ===========================================================================
# 2. POST /api/calculate
# ===========================================================================

class TestCalculateEndpoint(unittest.TestCase):

    def _post(self, payload):
        return client.post("/api/calculate", json=payload, headers=HEADERS)

    def test_easy_policy_period1_interest(self):
        """Period 1 interest must equal HK$3,232,449.32"""
        r = self._post(EASY_POLICY_PAYLOAD)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        p1 = data["periods"][0]
        self.assertAlmostEqual(p1["interest"], 3232449.32, places=2)

    def test_easy_policy_period2_interest(self):
        """Period 2 interest must equal HK$10,575,064.11"""
        r = self._post(EASY_POLICY_PAYLOAD)
        data = r.json()
        p2 = data["periods"][1]
        self.assertAlmostEqual(p2["interest"], 10575064.11, places=2)

    def test_easy_policy_total_interest(self):
        r = self._post(EASY_POLICY_PAYLOAD)
        data = r.json()
        self.assertAlmostEqual(data["total_interest"], 13807513.43, places=2)

    def test_easy_policy_final_amount(self):
        r = self._post(EASY_POLICY_PAYLOAD)
        data = r.json()
        self.assertAlmostEqual(data["final_amount"], 24572513.43, places=2)

    def test_response_includes_explanation(self):
        r = self._post(EASY_POLICY_PAYLOAD)
        data = r.json()
        self.assertIsInstance(data["explanation"], list)
        self.assertGreater(len(data["explanation"]), 0)
        # Preamble should mention the convention
        self.assertIn("Actual/365 Fixed", data["explanation"][0])

    def test_response_fields_present(self):
        r = self._post(MINIMAL_PAYLOAD)
        data = r.json()
        for field in ["case_name", "principal", "start_date", "total_interest",
                      "final_amount", "periods", "explanation", "generated_at"]:
            self.assertIn(field, data, f"Missing field: {field}")

    def test_period_response_fields(self):
        r = self._post(MINIMAL_PAYLOAD)
        p = r.json()["periods"][0]
        for field in ["period_id", "start_date", "end_date", "days",
                      "interest", "principal_start", "principal_end",
                      "cumulative_interest", "year_fraction"]:
            self.assertIn(field, p, f"Missing period field: {field}")

    def test_daily_series_included_when_requested(self):
        payload = dict(MINIMAL_PAYLOAD)
        payload["include_daily_series"] = True
        r = self._post(payload)
        data = r.json()
        self.assertGreater(len(data["daily_series"]), 0)
        point = data["daily_series"][0]
        for field in ["date", "principal", "total_interest", "total_amount"]:
            self.assertIn(field, point)

    def test_daily_series_omitted_when_false(self):
        r = self._post(MINIMAL_PAYLOAD)  # include_daily_series=False
        data = r.json()
        self.assertEqual(data["daily_series"], [])

    def test_compound_interest_type(self):
        payload = {
            "principal": "1000000.00",
            "start_date": "2021-01-01",
            "day_count_convention": "Actual/365 Fixed",
            "periods": [
                {
                    "end_date": "2024-01-01",
                    "interest_type": "Compound",
                    "interest_basis": "Initial Principal",
                    "nominal_rate": "0.24",
                    "rate_basis": "Per annum",
                    "compounding_freq": "Monthly",
                    "include_start_day": True,
                    "include_end_day": False,
                }
            ],
            "include_daily_series": False,
        }
        r = self._post(payload)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        # (1.02)^36 − 1 ≈ 96.97% → interest ≈ HK$969,741
        self.assertGreater(data["total_interest"], 900000)
        self.assertLess(data["total_interest"], 1100000)

    def test_single_period_zero_rate(self):
        payload = {
            "principal": "500000.00",
            "start_date": "2020-01-01",
            "day_count_convention": "Actual/365 Fixed",
            "periods": [
                {
                    "end_date": "2021-01-01",
                    "interest_type": "Simple",
                    "interest_basis": "Initial Principal",
                    "nominal_rate": "0.00",
                    "rate_basis": "Per annum",
                }
            ],
            "include_daily_series": False,
        }
        r = self._post(payload)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertAlmostEqual(data["total_interest"], 0.0, places=2)
        self.assertAlmostEqual(data["final_amount"], 500000.0, places=2)

    def test_anniversary_convention(self):
        payload = {
            "principal": "1000000.00",
            "start_date": "2015-08-21",
            "day_count_convention": "Anniversary/365",
            "periods": [
                {
                    "end_date": "2021-08-21",
                    "interest_type": "Simple",
                    "interest_basis": "Initial Principal",
                    "nominal_rate": "0.05",
                    "rate_basis": "Per annum",
                    "include_start_day": True,
                    "include_end_day": False,
                }
            ],
            "include_daily_series": False,
        }
        r = self._post(payload)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        # Exactly 6 years → interest = 1,000,000 × 5% × 6 = 300,000
        self.assertAlmostEqual(data["total_interest"], 300000.0, places=2)

    # --- Validation errors ---

    def test_missing_principal_returns_422(self):
        payload = dict(MINIMAL_PAYLOAD)
        del payload["principal"]
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)

    def test_zero_principal_returns_422(self):
        payload = dict(MINIMAL_PAYLOAD)
        payload["principal"] = "0"
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)

    def test_empty_periods_returns_422(self):
        payload = dict(MINIMAL_PAYLOAD)
        payload["periods"] = []
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)

    def test_end_date_before_start_returns_422(self):
        payload = {
            "principal": "1000000.00",
            "start_date": "2021-01-01",
            "day_count_convention": "Actual/365 Fixed",
            "periods": [
                {
                    "end_date": "2020-01-01",  # before start_date
                    "interest_type": "Simple",
                    "interest_basis": "Initial Principal",
                    "nominal_rate": "0.08",
                    "rate_basis": "Per annum",
                }
            ],
            "include_daily_series": False,
        }
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)

    def test_negative_rate_returns_422(self):
        payload = dict(MINIMAL_PAYLOAD)
        payload["periods"][0]["nominal_rate"] = "-0.05"
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)

    def test_invalid_convention_returns_422(self):
        payload = dict(MINIMAL_PAYLOAD)
        payload["day_count_convention"] = "Made Up Convention"
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)

    def test_case_name_preserved_in_response(self):
        r = self._post(EASY_POLICY_PAYLOAD)
        data = r.json()
        self.assertEqual(data["case_name"], "Easy Policy Finance Ltd v 陳海濱")


# ===========================================================================
# 3. GET /api/rate-presets/cj
# ===========================================================================

class TestCjRateEndpoint(unittest.TestCase):

    def _get(self, query_date: str):
        return client.get(
            f"/api/rate-presets/cj?query_date={query_date}",
            headers=HEADERS,
        )

    def test_current_rate_returns_200(self):
        r = self._get("2026-01-15")
        self.assertEqual(r.status_code, 200)

    def test_response_fields(self):
        r = self._get("2026-01-15")
        data = r.json()
        for field in ["query_date", "effective_date", "rate_pct", "rate_fraction"]:
            self.assertIn(field, data)

    def test_rate_is_positive(self):
        r = self._get("2026-01-15")
        data = r.json()
        self.assertGreater(data["rate_pct"], 0)
        self.assertGreater(data["rate_fraction"], 0)

    def test_rate_fraction_is_rate_pct_over_100(self):
        r = self._get("2025-06-15")
        data = r.json()
        self.assertAlmostEqual(
            data["rate_fraction"],
            data["rate_pct"] / 100,
            places=6,
        )

    def test_effective_date_on_or_before_query(self):
        r = self._get("2025-11-15")
        data = r.json()
        from datetime import date
        query = date.fromisoformat(data["query_date"])
        effective = date.fromisoformat(data["effective_date"])
        self.assertLessEqual(effective, query)

    def test_exact_quarter_boundary(self):
        # 1 Jan 2026 → rate of 8.107%
        r = self._get("2026-01-01")
        data = r.json()
        self.assertAlmostEqual(data["rate_pct"], 8.107, places=2)

    def test_date_before_table_returns_404(self):
        r = self._get("1990-01-01")
        self.assertEqual(r.status_code, 404)

    def test_invalid_date_format_returns_422(self):
        r = client.get("/api/rate-presets/cj?query_date=not-a-date", headers=HEADERS)
        self.assertEqual(r.status_code, 422)

    def test_missing_query_date_returns_422(self):
        r = client.get("/api/rate-presets/cj", headers=HEADERS)
        self.assertEqual(r.status_code, 422)


# ===========================================================================
# 4. GET /api/settings/rates
# ===========================================================================

class TestSettingsRatesEndpoint(unittest.TestCase):

    def test_returns_200(self):
        r = client.get("/api/settings/rates", headers=HEADERS)
        self.assertEqual(r.status_code, 200)

    def test_response_shape(self):
        r = client.get("/api/settings/rates", headers=HEADERS)
        data = r.json()
        for field in ["count", "earliest_date", "latest_date",
                      "latest_rate_pct", "entries"]:
            self.assertIn(field, data)

    def test_count_matches_entries_length(self):
        r = client.get("/api/settings/rates", headers=HEADERS)
        data = r.json()
        self.assertEqual(data["count"], len(data["entries"]))

    def test_entries_are_descending(self):
        r = client.get("/api/settings/rates", headers=HEADERS)
        data = r.json()
        dates = [e["effective_date"] for e in data["entries"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_latest_date_is_most_recent(self):
        r = client.get("/api/settings/rates", headers=HEADERS)
        data = r.json()
        if data["entries"]:
            self.assertEqual(data["latest_date"], data["entries"][0]["effective_date"])

    def test_earliest_date_is_oldest(self):
        r = client.get("/api/settings/rates", headers=HEADERS)
        data = r.json()
        if data["entries"]:
            self.assertEqual(data["earliest_date"], data["entries"][-1]["effective_date"])


# ===========================================================================
# 5. Static / SPA routes (no auth)
# ===========================================================================

class TestStaticRoutes(unittest.TestCase):

    def test_root_returns_200_or_json(self):
        r = client.get("/")
        # Either serves index.html (200) or a JSON hint that frontend isn't built
        self.assertIn(r.status_code, [200, 404])

    def test_api_docs_accessible(self):
        r = client.get("/api/docs")
        self.assertEqual(r.status_code, 200)

    def test_openapi_json_accessible(self):
        r = client.get("/openapi.json")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("openapi", data)
        self.assertIn("paths", data)

    def test_all_api_routes_in_schema(self):
        r = client.get("/openapi.json")
        paths = r.json()["paths"]
        for expected in ["/api/calculate", "/api/rate-presets/cj",
                         "/api/settings/rates", "/api/settings/rates/refresh",
                         "/api/settings/rates/apply"]:
            self.assertIn(expected, paths, f"Route missing from schema: {expected}")


# ===========================================================================
# 6. Multi-period chain validation
# ===========================================================================

class TestMultiPeriodChain(unittest.TestCase):

    def test_three_period_chain(self):
        payload = {
            "principal": "1000000.00",
            "start_date": "2019-01-01",
            "day_count_convention": "Actual/365 Fixed",
            "periods": [
                {
                    "end_date": "2020-01-01",
                    "interest_type": "Simple",
                    "interest_basis": "Running Sum",
                    "nominal_rate": "0.08",
                    "rate_basis": "Per annum",
                    "include_start_day": True,
                    "include_end_day": False,
                },
                {
                    "end_date": "2021-01-01",
                    "interest_type": "Simple",
                    "interest_basis": "Running Sum",
                    "nominal_rate": "0.08",
                    "rate_basis": "Per annum",
                    "include_start_day": True,
                    "include_end_day": False,
                },
                {
                    "end_date": "2022-01-01",
                    "interest_type": "Simple",
                    "interest_basis": "Running Sum",
                    "nominal_rate": "0.08",
                    "rate_basis": "Per annum",
                    "include_start_day": True,
                    "include_end_day": False,
                },
            ],
            "include_daily_series": False,
        }
        r = client.post("/api/calculate", json=payload, headers=HEADERS)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        periods = data["periods"]

        # Chain: principal_start[N] == principal_end[N-1]
        for i in range(1, len(periods)):
            self.assertAlmostEqual(
                periods[i]["principal_start"],
                periods[i-1]["principal_end"],
                places=2,
                msg=f"Chain broken at period {i+1}",
            )

        # Cumulative interest increases monotonically
        for i in range(1, len(periods)):
            self.assertGreater(
                periods[i]["cumulative_interest"],
                periods[i-1]["cumulative_interest"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
