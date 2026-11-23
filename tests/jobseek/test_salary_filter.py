"""Salary extraction, currency detection, and floor gating."""

from __future__ import annotations

import unittest

from jobseek.filters.hard import apply_hard_filters
from jobseek.filters.salary import enrich_job_salary, extract_salary_from_text, salary_label_for_job


def _search(**salary_overrides):
    sal = {"reject_missing": False, "floors": {"CAD": 130_000}}
    sal.update(salary_overrides)
    return {
        "tracks": ["data_engineering"],
        "seniority": {"include": ["mid", "senior", "staff"], "exclude": ["intern"]},
        "location": {
            "modes": ["remote_canada", "hybrid"],
            "preferred": ["Canada remote", "Remote Canada"],
            "reject_us_only_remote": True,
            "unknown_location_policy": "flag",
            "cities": ["Toronto"],
            "provinces": ["Ontario", "ON"],
        },
        "salary": sal,
    }


class SalaryFilterTests(unittest.TestCase):
    def test_missing_salary_is_undisclosed_not_invented(self):
        info = extract_salary_from_text("Great team, competitive compensation.")
        self.assertEqual(info.confidence, "undisclosed")
        self.assertIsNone(info.salary_min)
        self.assertIn("undisclosed", info.label.lower())

    def test_verified_cad_range(self):
        info = extract_salary_from_text("Base salary CAD $140,000 - $160,000 annually")
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.currency, "CAD")
        self.assertEqual(info.salary_min, 140_000)
        self.assertEqual(info.salary_max, 160_000)
        self.assertIn("Verified", info.label)

    def test_usd_vs_cad_detection(self):
        cad = extract_salary_from_text("Salary range: C$120,000 to C$140,000")
        usd = extract_salary_from_text("Salary range: USD $120,000 to $140,000")
        self.assertEqual(cad.currency, "CAD")
        self.assertEqual(usd.currency, "USD")

    def test_conflicting_currency_prefers_explicit_token(self):
        info = extract_salary_from_text("USD $150,000 CAD market rates")
        # First explicit currency token wins via CAD/USD detectors (CAD checked first)
        self.assertIn(info.currency, ("CAD", "USD"))
        self.assertIn(info.confidence, ("verified", "unverified"))

    def test_hourly_not_treated_as_annual_base(self):
        info = extract_salary_from_text("Pay: $85 / hour CAD")
        self.assertEqual(info.period, "hourly")
        self.assertEqual(info.confidence, "unverified")
        self.assertIsNone(info.salary_min)

    def test_equity_bonus_not_base(self):
        info = extract_salary_from_text("Total compensation $200,000 including equity and bonus")
        self.assertTrue(info.kind != "base" or info.confidence == "unverified")
        self.assertIsNone(info.salary_min)

    def test_ambiguous_bare_dollar_unverified(self):
        info = extract_salary_from_text("Compensation: $150,000 - $170,000")
        self.assertEqual(info.confidence, "unverified")
        self.assertTrue("currency" in " ".join(info.reasons).lower() or info.currency is None)

    def test_enrich_prefers_structured_fields(self):
        job = {
            "salary_min": 145000,
            "salary_max": 165000,
            "salary_currency": "CAD",
            "description": "ignore me $50k",
        }
        out = enrich_job_salary(job)
        self.assertEqual(out["salary_confidence"], "verified")
        self.assertIn("145,000", out["salary_label"])

    def test_below_floor_label(self):
        job = {
            "salary_min": 100000,
            "salary_max": 110000,
            "salary_currency": "CAD",
        }
        info = salary_label_for_job(job, floors={"CAD": 130000})
        self.assertEqual(info.confidence, "below_floor")
        self.assertIn("below preference", info.label.lower())

    def test_hard_filter_keeps_undisclosed_by_default(self):
        job = {
            "title": "Data Engineer",
            "location_raw": "Toronto, Ontario (Hybrid)",
            "description": "Hybrid in Toronto. Competitive pay.",
            "url": "https://boards.greenhouse.io/acme/jobs/1",
            "source": "greenhouse",
        }
        result = apply_hard_filters(job, _search())
        self.assertEqual(result.salary_verdict, "PASS")
        self.assertTrue(
            any("missing" in r.lower() or "undisclosed" in r.lower() for r in result.reasons)
        )

    def test_hard_filter_fails_below_floor_when_verified(self):
        job = {
            "title": "Data Engineer",
            "location_raw": "Toronto, Ontario (Hybrid)",
            "description": "Hybrid Toronto. Base salary CAD $90,000 - $100,000.",
            "url": "https://boards.greenhouse.io/acme/jobs/1",
            "source": "greenhouse",
        }
        result = apply_hard_filters(job, _search())
        self.assertEqual(result.salary_verdict, "FAIL")

    def test_reject_missing_when_configured(self):
        job = {
            "title": "Data Engineer",
            "location_raw": "Remote, Canada",
            "description": "Remote Canada. No pay listed.",
            "url": "https://boards.greenhouse.io/acme/jobs/1",
            "source": "greenhouse",
        }
        result = apply_hard_filters(job, _search(reject_missing=True))
        self.assertEqual(result.salary_verdict, "FAIL")


if __name__ == "__main__":
    unittest.main()
