"""Application URL classification and affiliate rejection."""

from __future__ import annotations

import unittest

from jobseek.filters.apply_url import (
    classify_application_url,
    is_affiliate_url,
    select_actionable_apply_url,
)
from jobseek.filters.hard import apply_hard_filters


SEARCH = {
    "tracks": ["software_engineering"],
    "track_aliases": {"software_engineering": ["Software Engineer", "Backend"]},
    "seniority": {
        "include": ["mid", "senior", "staff", "unknown"],
        "exclude": ["intern", "coop", "student"],
    },
    "location": {
        "modes": ["remote_canada", "hybrid"],
        "preferred": ["Canada remote", "Remote Canada"],
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
        "cities": ["Montreal"],
        "provinces": ["QC", "Quebec"],
    },
    "salary": {"reject_missing": False, "floors": {}},
}


class ClassifyTests(unittest.TestCase):
    def test_whatjobs_is_affiliate(self):
        v = classify_application_url("https://ca.whatjobs.com/job/123")
        self.assertEqual(v.kind, "affiliate")
        self.assertFalse(v.actionable)
        self.assertTrue(is_affiliate_url("https://www.whatjobs.ca/x"))

    def test_greenhouse_is_direct(self):
        v = classify_application_url("https://boards.greenhouse.io/acme/jobs/1")
        self.assertEqual(v.kind, "direct")
        self.assertTrue(v.actionable)

    def test_workday_is_direct(self):
        v = classify_application_url(
            "https://intactfc.wd3.myworkdayjobs.com/intactfc/job/X_R1"
        )
        self.assertEqual(v.kind, "direct")

    def test_select_prefers_direct_over_affiliate(self):
        url, v = select_actionable_apply_url(
            primary="https://ca.whatjobs.com/job/1",
            fallbacks=["https://boards.greenhouse.io/acme/jobs/9"],
        )
        self.assertEqual(url, "https://boards.greenhouse.io/acme/jobs/9")
        self.assertEqual(v.kind, "direct")

    def test_affiliate_only_not_actionable(self):
        url, v = select_actionable_apply_url(
            primary="https://ca.whatjobs.com/job/1",
        )
        self.assertFalse(v.actionable)
        self.assertEqual(v.kind, "affiliate")
        self.assertIn("whatjobs", url or "")


class HardFilterAffiliateTests(unittest.TestCase):
    def test_affiliate_demotes_eligible_geo(self):
        job = {
            "title": "Senior Software Engineer",
            "company": "Acme",
            "location_raw": "Remote, Canada",
            "description": "Fully remote in Canada.",
            "url": "https://ca.whatjobs.com/job/abc",
            "apply_url": "https://ca.whatjobs.com/job/abc",
            "source": "freehire_review",
        }
        result = apply_hard_filters(job, SEARCH)
        self.assertNotEqual(result.eligibility, "ELIGIBLE")
        self.assertTrue(any("not confirmed-actionable" in r for r in result.reasons))

    def test_direct_freehire_stays_eligible(self):
        job = {
            "title": "Senior Software Engineer",
            "company": "Acme",
            "location_raw": "Remote, Canada",
            "description": "Fully remote in Canada.",
            "url": "https://boards.greenhouse.io/acme/jobs/1",
            "apply_url": "https://boards.greenhouse.io/acme/jobs/1",
            "source": "freehire",
        }
        result = apply_hard_filters(job, SEARCH)
        self.assertEqual(result.eligibility, "ELIGIBLE")


if __name__ == "__main__":
    unittest.main()
