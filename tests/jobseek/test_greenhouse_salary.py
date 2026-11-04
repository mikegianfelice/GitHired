"""Greenhouse salary parsing regressions (comma / K / currency)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from jobseek.adapters.greenhouse import GreenhouseAdapter, _salary_from_job
from jobseek.filters.salary import extract_salary_from_text
from jobseek.http_client import HttpResponse


def _client(payload, status=200):
    client = MagicMock()
    client.get.return_value = HttpResponse(status, json.dumps(payload), "https://example.test")
    return client


class GreenhouseSalaryRegexRegressionTests(unittest.TestCase):
    def test_cad_range_not_truncated_to_950(self):
        info = extract_salary_from_text("CAD $95,000 - $135,000")
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.salary_min, 95000.0)
        self.assertEqual(info.salary_max, 135000.0)
        self.assertEqual(info.currency, "CAD")

    def test_usd_range_not_truncated_to_150(self):
        info = extract_salary_from_text("USD $150,000 - $200,000")
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.salary_min, 150000.0)
        self.assertEqual(info.salary_max, 200000.0)

    def test_ca_dollar_k_suffix(self):
        info = extract_salary_from_text("CA$95K–CA$135K")
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.salary_min, 95000.0)
        self.assertEqual(info.salary_max, 135000.0)
        self.assertEqual(info.currency, "CAD")

    def test_bare_digits_with_cad_trail(self):
        info = extract_salary_from_text("CAD 95000–135000")
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.salary_min, 95000.0)
        self.assertEqual(info.salary_max, 135000.0)

    def test_k_range_with_trailing_cad(self):
        info = extract_salary_from_text("$120k–$160k CAD")
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.salary_min, 120000.0)
        self.assertEqual(info.salary_max, 160000.0)
        self.assertEqual(info.currency, "CAD")

    def test_single_annual(self):
        info = extract_salary_from_text("Base salary CAD $150,000 annually")
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.salary_min, 150000.0)

    def test_hourly_not_annual(self):
        info = extract_salary_from_text("$60–$80/hour CAD")
        self.assertEqual(info.period, "hourly")
        self.assertIsNone(info.salary_min)

    def test_html_embedded_salary(self):
        html = "<p>Compensation:</p><p>CAD $95,000 &ndash; $135,000</p>"
        raw, amin, amax, cur = _salary_from_job({}, html)
        self.assertEqual(cur, "CAD")
        self.assertEqual(amin, 95000.0)
        self.assertEqual(amax, 135000.0)

    def test_metadata_preferred(self):
        item = {
            "metadata": [{"name": "Salary Range", "value": "USD $180,000 - $220,000"}],
            "content": "ignore CAD $50,000",
        }
        raw, amin, amax, cur = _salary_from_job(item, item["content"])
        self.assertEqual(cur, "USD")
        self.assertEqual(amin, 180000.0)
        self.assertEqual(amax, 220000.0)

    def test_ambiguous_dollar_unverified(self):
        info = extract_salary_from_text("Compensation: $150,000 - $170,000")
        self.assertEqual(info.confidence, "unverified")

    def test_adapter_parses_content(self):
        payload = {
            "jobs": [
                {
                    "id": 1,
                    "title": "Software Engineer",
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                    "location": {"name": "Toronto, ON"},
                    "content": "Base salary CAD $95,000 - $135,000. Equity may be offered.",
                    "updated_at": "2026-11-01T00:00:00Z",
                }
            ]
        }
        result = GreenhouseAdapter(client=_client(payload)).fetch_company(
            {"name": "Acme", "board_token": "acme"}
        )
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0].salary_currency, "CAD")
        self.assertEqual(result.jobs[0].salary_min, 95000.0)
        self.assertEqual(result.jobs[0].salary_max, 135000.0)

    def test_affirm_style_base_pay_with_equity_elsewhere(self):
        text = (
            "The base pay range for this position is $181,000 - $241,000 CAD. "
            "#Li-Remote Affirm is proud to offer equity and benefits."
        )
        info = extract_salary_from_text(text)
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.salary_min, 181000.0)
        self.assertEqual(info.salary_max, 241000.0)
        self.assertEqual(info.currency, "CAD")


if __name__ == "__main__":
    unittest.main()
