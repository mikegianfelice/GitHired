"""Regression: between/and ranges, multi-geo bands, Ashby description fallback."""

from __future__ import annotations

import unittest

from jobseek.adapters.ashby import _salary as ashby_salary
from jobseek.filters.salary import enrich_job_salary, extract_salary_from_text


class BetweenAndRangeTests(unittest.TestCase):
    def test_between_cad_and_cad(self):
        info = extract_salary_from_text(
            "Canada-based roles only: The annual base salary for this role "
            "is between $171,000 CAD and $248,000 CAD.",
            location_hint="Remote (United States | Canada)",
        )
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.salary_min, 171_000.0)
        self.assertEqual(info.salary_max, 248_000.0)
        self.assertEqual(info.currency, "CAD")

    def test_k_suffix_to(self):
        info = extract_salary_from_text("The salary range is $150k to $200k CAD.")
        self.assertEqual((info.salary_min, info.salary_max, info.currency), (150_000.0, 200_000.0, "CAD"))

    def test_hyphen_en_dash(self):
        a = extract_salary_from_text("Compensation: $150,000-$200,000 CAD")
        b = extract_salary_from_text("Pay: $150,000 – $200,000 CAD")
        self.assertEqual(a.salary_min, 150_000.0)
        self.assertEqual(b.salary_max, 200_000.0)

    def test_cad_prefix_to(self):
        info = extract_salary_from_text("CAD 150,000 to CAD 200,000 annually")
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.salary_min, 150_000.0)
        self.assertEqual(info.salary_max, 200_000.0)

    def test_between_cad_dollar_and(self):
        info = extract_salary_from_text(
            "Base salary between CAD $95,000 and CAD $135,000",
            location_hint="Toronto, ON",
        )
        self.assertEqual(info.salary_min, 95_000.0)
        self.assertEqual(info.salary_max, 135_000.0)
        self.assertEqual(info.currency, "CAD")

    def test_does_not_collapse_to_max_only(self):
        info = extract_salary_from_text(
            "The annual base salary for this role is between $171,000 CAD and $248,000 CAD."
        )
        self.assertNotEqual(info.salary_min, info.salary_max)
        self.assertEqual(info.salary_min, 171_000.0)

    def test_multi_geo_prefers_canada_band(self):
        text = (
            "USA-based roles only: The annual base salary for this role is "
            "between $171,000 USD and $248,000 USD. "
            "Canada-based roles only: The annual base salary for this role is "
            "between $171,000 CAD and $248,000 CAD."
        )
        ca = extract_salary_from_text(text, location_hint="Remote (United States | Canada)")
        us = extract_salary_from_text(text, location_hint="Austin, TX (Remote)")
        self.assertEqual(ca.currency, "CAD")
        self.assertEqual(ca.salary_min, 171_000.0)
        self.assertEqual(us.currency, "USD")
        self.assertEqual(us.salary_max, 248_000.0)

    def test_never_invents_salary(self):
        info = extract_salary_from_text("Competitive compensation. Great benefits.")
        self.assertEqual(info.confidence, "undisclosed")
        self.assertIsNone(info.salary_min)


class AshbyDescriptionFallbackTests(unittest.TestCase):
    def test_structured_preferred_over_description(self):
        job = {
            "compensation": {
                "summaryComponents": [
                    {
                        "compensationType": "Salary",
                        "interval": "1 YEAR",
                        "currencyCode": "CAD",
                        "minValue": 100000,
                        "maxValue": 120000,
                    }
                ]
            },
            "descriptionPlain": (
                "Canada-based roles only: between $171,000 CAD and $248,000 CAD."
            ),
            "location": "Toronto, ON",
        }
        raw, amin, amax, cur = ashby_salary(
            job, description=job["descriptionPlain"], location_raw="Toronto, ON"
        )
        self.assertEqual(amin, 100_000.0)
        self.assertEqual(amax, 120_000.0)
        self.assertEqual(cur, "CAD")

    def test_description_fallback_when_no_structure(self):
        job = {
            "descriptionPlain": (
                "Canada-based roles only: The annual base salary for this role "
                "is between $171,000 CAD and $248,000 CAD."
            ),
            "location": "Remote (United States | Canada)",
        }
        raw, amin, amax, cur = ashby_salary(
            job,
            description=job["descriptionPlain"],
            location_raw="Remote (United States | Canada)",
        )
        self.assertEqual(amin, 171_000.0)
        self.assertEqual(amax, 248_000.0)
        self.assertEqual(cur, "CAD")
        self.assertIn("171,000", raw or "")

    def test_enrich_job_salary_backfills_1password_style(self):
        job = {
            "title": "Engineering Manager, Infrastructure",
            "company": "1Password",
            "location_raw": "Remote (United States | Canada)",
            "description": (
                "USA-based roles only: The annual base salary for this role is "
                "between $185,000 USD and $268,000 USD. "
                "Canada-based roles only: The annual base salary for this role is "
                "between $171,000 CAD and $248,000 CAD."
            ),
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
        }
        out = enrich_job_salary(job)
        self.assertEqual(out["salary_confidence"], "verified")
        self.assertEqual(out["salary_min"], 171_000.0)
        self.assertEqual(out["salary_max"], 248_000.0)
        self.assertEqual(out["salary_currency"], "CAD")


if __name__ == "__main__":
    unittest.main()
