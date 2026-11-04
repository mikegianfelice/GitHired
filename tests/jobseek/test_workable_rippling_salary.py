"""Workable / Rippling structured salary extraction (detail payloads)."""

from __future__ import annotations

import unittest

from jobseek.adapters.rippling import salary_from_rippling_detail
from jobseek.adapters.workable import salary_from_workable_detail


class WorkableDetailSalaryTests(unittest.TestCase):
    def test_annual_cad_from_detail(self):
        raw, amin, amax, cur = salary_from_workable_detail(
            {
                "salary_from": 80000,
                "salary_to": 130000,
                "salary_currency_iso_code": "CAD",
                "salary_frequency": "year",
            }
        )
        self.assertEqual(cur, "CAD")
        self.assertEqual(amin, 80000.0)
        self.assertEqual(amax, 130000.0)

    def test_hourly_frequency_not_annual(self):
        raw, amin, amax, cur = salary_from_workable_detail(
            {
                "salary_from": 40,
                "salary_to": 55,
                "salary_currency_iso_code": "CAD",
                "salary_frequency": "hour",
            }
        )
        self.assertIsNone(amin)
        self.assertIsNone(amax)

    def test_description_fallback(self):
        raw, amin, amax, cur = salary_from_workable_detail(
            {
                "description": "<p>Base salary CAD $110,000 - $140,000 annually</p>",
            }
        )
        self.assertEqual(cur, "CAD")
        self.assertEqual(amin, 110000.0)


class RipplingDetailSalaryTests(unittest.TestCase):
    def test_pay_range_details(self):
        raw, amin, amax, cur = salary_from_rippling_detail(
            {
                "payRangeDetails": [
                    {
                        "min": 120000,
                        "max": 150000,
                        "currency": "CAD",
                        "period": "year",
                    }
                ]
            }
        )
        self.assertEqual((amin, amax, cur), (120000.0, 150000.0, "CAD"))

    def test_json_ld_base_salary(self):
        raw, amin, amax, cur = salary_from_rippling_detail(
            {
                "payRangeDetails": [],
                "jsonLd": {
                    "baseSalary": {
                        "currency": "USD",
                        "value": {"minValue": 160000, "maxValue": 190000, "unitText": "YEAR"},
                    }
                },
            }
        )
        self.assertEqual(cur, "USD")
        self.assertEqual(amin, 160000.0)
        self.assertEqual(amax, 190000.0)

    def test_empty_pay_returns_none(self):
        self.assertEqual(
            salary_from_rippling_detail({"payRangeDetails": [], "description": {}}),
            (None, None, None, None),
        )


if __name__ == "__main__":
    unittest.main()
