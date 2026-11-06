"""US ATS location + Canada hire body must not publish exclusive US labels."""

from __future__ import annotations

import unittest

from jobseek.filters.hard import apply_hard_filters
from jobseek.filters.location import classify_canada_eligibility
from jobseek.public_shortlist.export import (
    PUBLIC_SEARCH,
    public_location_label,
    select_public_jobs,
)


CLICKHOUSE_DESC = (
    "NOTE: This position can be remote in Canada or the United States. "
    "We are hiring talented Full Stack Software Engineers for our Control Plane team."
)


class UsLocationCanadaHireTests(unittest.TestCase):
    def test_clickhouse_style_eligible_but_not_us_only_label(self):
        job = {
            "title": "Full Stack Software Engineer - Control Plane",
            "company": "ClickHouse",
            "location_raw": "United States (Remote)",
            "description": CLICKHOUSE_DESC,
            "description_complete": 1,
            "url": "https://jobs.ashbyhq.com/clickhouse/bd6d5e55-790a-4f3d-a905-193fe39ed5cf",
            "apply_url": (
                "https://jobs.ashbyhq.com/clickhouse/"
                "bd6d5e55-790a-4f3d-a905-193fe39ed5cf/application"
            ),
            "source": "ashby",
            "ats_provider": "ashby",
            "ats_job_id": "bd6d5e55-790a-4f3d-a905-193fe39ed5cf",
            "salary_min": 140_000,
            "salary_max": 200_000,
            "salary_currency": "USD",
            "first_seen": "2026-11-01T00:00:00Z",
            "last_seen": "2026-11-06T00:00:00Z",
            "removed_at": None,
        }
        elig, verdict, reasons, _ = classify_canada_eligibility(job, PUBLIC_SEARCH)
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")
        self.assertTrue(any("canada" in r.casefold() for r in reasons))

        label = public_location_label(job["location_raw"], job["description"])
        self.assertNotEqual(label.casefold(), "united states (remote)")
        self.assertIn("canada", label.casefold())

        selected = select_public_jobs([job], limit=10)
        self.assertEqual(len(selected), 1)
        self.assertNotEqual(selected[0].location.casefold(), "united states (remote)")
        self.assertIn("canada", selected[0].location.casefold())
        self.assertEqual(selected[0].remote_scope, "canada")

    def test_us_only_without_canada_body_ineligible(self):
        job = {
            "title": "Software Engineer",
            "company": "Acme US",
            "location_raw": "United States (Remote)",
            "description": "Remote within the United States only. Python.",
            "url": "https://boards.greenhouse.io/acme/jobs/99",
            "apply_url": "https://boards.greenhouse.io/acme/jobs/99",
            "source": "greenhouse",
        }
        elig, verdict, _, _ = classify_canada_eligibility(job, PUBLIC_SEARCH)
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")
        hard = apply_hard_filters(job, PUBLIC_SEARCH)
        self.assertNotEqual(hard.eligibility, "ELIGIBLE")


if __name__ == "__main__":
    unittest.main()
