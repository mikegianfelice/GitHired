"""Ashby compensation extraction — includeCompensation + structured components."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from jobseek.adapters.ashby import AshbyAdapter, _salary
from jobseek.http_client import HttpResponse


def _client(payload, status=200, url="https://api.ashbyhq.com/posting-api/job-board/x"):
    client = MagicMock()
    text = payload if isinstance(payload, str) else json.dumps(payload)
    client.get.return_value = HttpResponse(status, text, url)
    return client


def seven_shifts_mid_market() -> dict:
    """Live-shaped payload for Software Developer, Mid-Market (7shifts)."""
    return {
        "id": "7shifts-mid",
        "title": "Software Developer, Mid-Market",
        "jobUrl": "https://jobs.ashbyhq.com/7shifts/7shifts-mid",
        "applyUrl": "https://jobs.ashbyhq.com/7shifts/7shifts-mid/application",
        "isListed": True,
        "isRemote": True,
        "location": "Canada",
        "descriptionPlain": "Build products for restaurants.",
        "compensation": {
            "compensationTierSummary": "CA$95K – CA$135K • Offers Equity",
            "scrapeableCompensationSalarySummary": "CA$95K - CA$135K",
            "compensationTiers": [
                {
                    "id": "tier-1",
                    "components": [
                        {
                            "compensationType": "Salary",
                            "interval": "1 YEAR",
                            "currencyCode": "CAD",
                            "minValue": 95000,
                            "maxValue": 135000,
                        },
                        {
                            "compensationType": "EquityPercentage",
                            "interval": "NONE",
                            "currencyCode": None,
                            "minValue": None,
                            "maxValue": None,
                        },
                    ],
                }
            ],
            "summaryComponents": [
                {
                    "compensationType": "Salary",
                    "interval": "1 YEAR",
                    "currencyCode": "CAD",
                    "minValue": 95000,
                    "maxValue": 135000,
                },
                {
                    "compensationType": "EquityPercentage",
                    "interval": "NONE",
                    "currencyCode": None,
                    "minValue": None,
                    "maxValue": None,
                },
            ],
        },
    }


class AshbySalaryParseTests(unittest.TestCase):
    def test_7shifts_mid_market_base_salary(self):
        raw, amin, amax, cur = _salary(seven_shifts_mid_market())
        self.assertEqual(cur, "CAD")
        self.assertEqual(amin, 95000.0)
        self.assertEqual(amax, 135000.0)
        self.assertIn("95000", raw or "")

    def test_ignores_equity_bonus_commission(self):
        job = {
            "compensation": {
                "summaryComponents": [
                    {
                        "compensationType": "EquityPercentage",
                        "interval": "NONE",
                        "minValue": 0.5,
                        "maxValue": 1.5,
                    },
                    {
                        "compensationType": "Bonus",
                        "interval": "1 YEAR",
                        "currencyCode": "USD",
                        "minValue": 10000,
                        "maxValue": 20000,
                    },
                    {
                        "compensationType": "Commission",
                        "interval": "1 YEAR",
                        "currencyCode": "USD",
                        "minValue": 5000,
                        "maxValue": 15000,
                    },
                    {
                        "compensationType": "Salary",
                        "interval": "1 YEAR",
                        "currencyCode": "USD",
                        "minValue": 120000,
                        "maxValue": 140000,
                    },
                ]
            }
        }
        raw, amin, amax, cur = _salary(job)
        self.assertEqual(cur, "USD")
        self.assertEqual(amin, 120000.0)
        self.assertEqual(amax, 140000.0)

    def test_rejects_hourly_salary_component(self):
        job = {
            "compensation": {
                "summaryComponents": [
                    {
                        "compensationType": "Salary",
                        "interval": "1 HOUR",
                        "currencyCode": "CAD",
                        "minValue": 45,
                        "maxValue": 60,
                    }
                ]
            }
        }
        self.assertEqual(_salary(job), (None, None, None, None))

    def test_tiers_fallback_when_summary_missing(self):
        job = {
            "compensation": {
                "compensationTiers": [
                    {
                        "components": [
                            {
                                "compensationType": "Salary",
                                "interval": "1 YEAR",
                                "currencyCode": "CAD",
                                "minValue": 100000,
                                "maxValue": 130000,
                            }
                        ]
                    }
                ]
            }
        }
        _, amin, amax, cur = _salary(job)
        self.assertEqual((amin, amax, cur), (100000.0, 130000.0, "CAD"))

    def test_multi_tier_same_currency_uses_envelope(self):
        """Ashby summaryComponents envelope — not inventing a third band."""
        job = {
            "compensation": {
                "summaryComponents": [
                    {
                        "compensationType": "Salary",
                        "interval": "1 YEAR",
                        "currencyCode": "CAD",
                        "minValue": 250000,
                        "maxValue": 535000,
                    }
                ],
                "compensationTiers": [
                    {
                        "title": "Toronto",
                        "components": [
                            {
                                "compensationType": "Salary",
                                "interval": "1 YEAR",
                                "currencyCode": "CAD",
                                "minValue": 295000,
                                "maxValue": 535000,
                            }
                        ],
                    },
                    {
                        "title": "Canada",
                        "components": [
                            {
                                "compensationType": "Salary",
                                "interval": "1 YEAR",
                                "currencyCode": "CAD",
                                "minValue": 250000,
                                "maxValue": 460000,
                            }
                        ],
                    },
                ],
            }
        }
        _, amin, amax, cur = _salary(job)
        self.assertEqual((amin, amax, cur), (250000.0, 535000.0, "CAD"))

    def test_mixed_currency_tiers_without_summary_refused(self):
        job = {
            "compensation": {
                "compensationTiers": [
                    {
                        "components": [
                            {
                                "compensationType": "Salary",
                                "interval": "1 YEAR",
                                "currencyCode": "CAD",
                                "minValue": 250000,
                                "maxValue": 460000,
                            }
                        ]
                    },
                    {
                        "components": [
                            {
                                "compensationType": "Salary",
                                "interval": "1 YEAR",
                                "currencyCode": "USD",
                                "minValue": 175000,
                                "maxValue": 325000,
                            }
                        ]
                    },
                ]
            }
        }
        self.assertEqual(_salary(job), (None, None, None, None))

    def test_missing_compensation_returns_none(self):
        self.assertEqual(_salary({"title": "Engineer"}), (None, None, None, None))


class AshbyAdapterCompensationTests(unittest.TestCase):
    def test_requests_include_compensation_flag(self):
        client = _client({"jobs": []})
        AshbyAdapter(client=client).fetch_company(
            {"name": "7shifts", "board_token": "7shifts"}
        )
        url = client.get.call_args[0][0]
        self.assertIn("includeCompensation=true", url)

    def test_parses_7shifts_job_into_rawjob(self):
        payload = {"jobs": [seven_shifts_mid_market()]}
        result = AshbyAdapter(client=_client(payload)).fetch_company(
            {"name": "7shifts", "board_token": "7shifts"}
        )
        self.assertEqual(len(result.jobs), 1)
        job = result.jobs[0]
        self.assertEqual(job.salary_currency, "CAD")
        self.assertEqual(job.salary_min, 95000.0)
        self.assertEqual(job.salary_max, 135000.0)
        self.assertEqual(job.title, "Software Developer, Mid-Market")

    def test_skips_unlisted_jobs(self):
        job = seven_shifts_mid_market()
        job["isListed"] = False
        result = AshbyAdapter(client=_client({"jobs": [job]})).fetch_company(
            {"name": "7shifts", "board_token": "7shifts"}
        )
        self.assertEqual(result.jobs, [])


if __name__ == "__main__":
    unittest.main()
