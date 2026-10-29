"""Hard filter tests for Canada-remote policy."""

from __future__ import annotations

import unittest

from jobseek.filters.hard import apply_hard_filters

SEARCH = {
    "tracks": ["ai_engineering", "data_engineering", "forward_deployed", "ml_engineering"],
    "target_titles": [
        "AI Engineer",
        "Senior AI Engineer",
        "Applied AI Engineer",
        "Forward Deployed Engineer",
        "Data Engineer",
        "Senior Data Engineer",
        "Staff Data Engineer",
        "AI Solutions Architect",
    ],
    "title_aliases": ["Machine Learning Engineer"],
    "location": {
        "modes": ["remote_canada", "remote_province", "hybrid", "onsite"],
        "preferred": ["Canada remote", "Remote Canada"],
        "allow_us_employer_remote_with_canada_evidence": True,
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
        "cities": ["Toronto", "Vancouver"],
        "provinces": ["Ontario", "ON"],
    },
    "salary": {"reject_missing": False, "floors": {"CAD": 120000, "USD": 90000}},
}


class HardFilterTests(unittest.TestCase):
    def test_canada_remote_pass(self):
        job = {
            "title": "Senior AI Engineer",
            "location_raw": "Remote - Canada",
            "description": "Build models. Remote in Canada.",
            "salary_min": 150000,
            "salary_currency": "CAD",
        }
        result = apply_hard_filters(job, SEARCH)
        self.assertEqual(result.verdict, "PASS")
        self.assertTrue(result.title_match)
        self.assertEqual(result.location_verdict, "PASS")

    def test_us_only_reject(self):
        job = {
            "title": "Applied AI Engineer",
            "location_raw": "Remote, United States",
            "description": "Must be located in the United States only.",
        }
        result = apply_hard_filters(job, SEARCH)
        self.assertEqual(result.verdict, "FAIL")
        self.assertEqual(result.location_verdict, "FAIL")

    def test_worldwide_pass(self):
        job = {
            "title": "Forward Deployed Engineer",
            "location_raw": "Remote",
            "description": "Work from anywhere. Worldwide remote OK.",
        }
        result = apply_hard_filters(job, SEARCH)
        self.assertEqual(result.location_verdict, "PASS")
        self.assertEqual(result.verdict, "PASS")

    def test_silent_remote_flag(self):
        job = {
            "title": "Staff Data Engineer",
            "location_raw": "Remote",
            "description": "Fully remote role building pipelines.",
        }
        result = apply_hard_filters(job, SEARCH)
        self.assertEqual(result.location_verdict, "FLAG")
        self.assertEqual(result.verdict, "FLAG")

    def test_title_mismatch(self):
        job = {
            "title": "Kitchen Manager",
            "location_raw": "Remote - Canada",
            "description": "Remote in Canada.",
        }
        result = apply_hard_filters(job, SEARCH)
        self.assertEqual(result.verdict, "FAIL")
        self.assertFalse(result.title_match)

    def test_salary_below_floor(self):
        job = {
            "title": "AI Engineer",
            "location_raw": "Canada remote",
            "description": "Remote Canada.",
            "salary_max": 80000,
            "salary_currency": "CAD",
        }
        result = apply_hard_filters(job, SEARCH)
        self.assertEqual(result.salary_verdict, "FAIL")
        self.assertEqual(result.verdict, "FAIL")

    def test_never_invent_canada_on_us_remote(self):
        job = {
            "title": "AI Solutions Architect",
            "location_raw": "Remote USA",
            "description": "Remote within the United States. Offices in NYC.",
        }
        result = apply_hard_filters(job, SEARCH)
        # US-primary without explicit Canada → UNCERTAIN (not invented ELIGIBLE)
        self.assertEqual(result.eligibility, "UNCERTAIN")
        self.assertEqual(result.location_verdict, "FLAG")
        self.assertFalse(any("invent" in r.lower() for r in result.reasons))

    def test_us_only_ineligible(self):
        job = {
            "title": "AI Engineer",
            "location_raw": "Remote",
            "description": "Must be located in the United States only.",
        }
        result = apply_hard_filters(job, SEARCH)
        self.assertEqual(result.eligibility, "INELIGIBLE")
        self.assertEqual(result.verdict, "FAIL")

    def test_intern_excluded_by_default(self):
        job = {
            "title": "Data Engineer Intern",
            "location_raw": "Remote - Canada",
            "description": "Remote in Canada.",
        }
        result = apply_hard_filters(job, SEARCH)
        self.assertEqual(result.verdict, "FAIL")
        self.assertTrue(any("intern" in r.casefold() for r in result.reasons))

    def test_toronto_hybrid_pass(self):
        cfg = {
            **SEARCH,
            "location": {
                **SEARCH["location"],
                "modes": ["hybrid", "onsite"],
                "cities": ["Toronto", "Vancouver"],
                "provinces": ["Ontario"],
            },
        }
        job = {
            "title": "Senior AI Engineer",
            "location_raw": "Hybrid - Toronto, ON",
            "description": "Hybrid role based in Toronto.",
        }
        result = apply_hard_filters(job, cfg)
        self.assertEqual(result.location_verdict, "PASS")


if __name__ == "__main__":
    unittest.main()
