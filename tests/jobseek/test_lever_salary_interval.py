"""Lever salaryRange.interval handling."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from jobseek.adapters.lever import LeverAdapter, _salary
from jobseek.http_client import HttpResponse


def _client(payload, status=200):
    client = MagicMock()
    client.get.return_value = HttpResponse(status, json.dumps(payload), "https://api.lever.co")
    return client


class LeverSalaryIntervalTests(unittest.TestCase):
    def test_annual_cad(self):
        job = {
            "salaryRange": {
                "min": 170000,
                "max": 220000,
                "currency": "CAD",
                "interval": "per-year-salary",
            },
            "salaryDescriptionPlain": "The salary range is $170,000 - $220,000 CAD per year.",
        }
        raw, amin, amax, cur = _salary(job)
        self.assertEqual(cur, "CAD")
        self.assertEqual(amin, 170000.0)
        self.assertEqual(amax, 220000.0)
        self.assertIn("170,000", raw or "")

    def test_annual_usd(self):
        raw, amin, amax, cur = _salary(
            {
                "salaryRange": {
                    "min": 150000,
                    "max": 180000,
                    "currency": "USD",
                    "interval": "per-year-salary",
                }
            }
        )
        self.assertEqual((amin, amax, cur), (150000.0, 180000.0, "USD"))

    def test_hourly_not_annual_columns(self):
        raw, amin, amax, cur = _salary(
            {
                "salaryRange": {
                    "min": 45,
                    "max": 65,
                    "currency": "CAD",
                    "interval": "per-hour-salary",
                },
                "salaryDescriptionPlain": "CAD $45-$65 per hour",
            }
        )
        self.assertIsNone(amin)
        self.assertIsNone(amax)
        self.assertIsNotNone(raw)

    def test_missing_interval_annual_looking(self):
        raw, amin, amax, cur = _salary(
            {"salaryRange": {"min": 100000, "max": 120000, "currency": "CAD"}}
        )
        # Structured ATS without interval but annual-looking → verified annual
        self.assertEqual(amin, 100000.0)
        self.assertEqual(cur, "CAD")

    def test_missing_salary(self):
        self.assertEqual(_salary({}), (None, None, None, None))

    def test_partial_min_only(self):
        raw, amin, amax, cur = _salary(
            {"salaryRange": {"min": 140000, "currency": "USD", "interval": "per-year-salary"}}
        )
        self.assertEqual(amin, 140000.0)
        self.assertEqual(amax, 140000.0)
        self.assertEqual(cur, "USD")

    def test_adapter_end_to_end(self):
        payload = [
            {
                "id": "abc",
                "text": "Principal Engineer",
                "hostedUrl": "https://jobs.lever.co/acme/abc",
                "applyUrl": "https://jobs.lever.co/acme/abc/apply",
                "descriptionPlain": "Build things.",
                "categories": {"location": "Toronto"},
                "salaryRange": {
                    "min": 170000,
                    "max": 220000,
                    "currency": "CAD",
                    "interval": "per-year-salary",
                },
            }
        ]
        result = LeverAdapter(client=_client(payload)).fetch_company(
            {"name": "Acme", "board_token": "acme"}
        )
        self.assertEqual(result.jobs[0].salary_min, 170000.0)
        self.assertEqual(result.jobs[0].salary_currency, "CAD")


if __name__ == "__main__":
    unittest.main()
