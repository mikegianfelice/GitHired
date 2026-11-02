"""Salary policy: flexible / strict / none + explicit USD↔CAD FX."""

from __future__ import annotations

import unittest

from jobseek.filters.hard import apply_hard_filters, _salary_policy


BASE = {
    "tracks": ["data_engineering"],
    "track_aliases": {"data_engineering": ["Data Engineer", "Senior Data Engineer"]},
    "location": {
        "modes": ["remote_canada"],
        "preferred": ["Remote - Canada"],
        "cities": ["Toronto"],
        "provinces": ["Ontario", "ON"],
        "allow_us_employer_remote_with_canada_evidence": True,
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
    },
}


def _cfg(policy: str, **salary_extra):
    return {
        **BASE,
        "salary": {
            "policy": policy,
            "usd_to_cad": 1.35,
            "floors": {"CAD": 130000},
            **salary_extra,
        },
    }


class SalaryPolicyTests(unittest.TestCase):
    def test_policy_alias_reject_missing(self):
        self.assertEqual(
            _salary_policy({"salary": {"reject_missing": True}}), "strict"
        )
        self.assertEqual(_salary_policy({"salary": {}}), "flexible")

    def test_flexible_allows_missing(self):
        job = {
            "title": "Senior Data Engineer",
            "location_raw": "Remote - Canada",
            "description": "Remote Canada. Python SQL.",
        }
        r = apply_hard_filters(job, _cfg("flexible"))
        self.assertEqual(r.salary_verdict, "PASS")
        self.assertTrue(any("flexible" in x.casefold() for x in r.reasons))

    def test_strict_rejects_missing(self):
        job = {
            "title": "Senior Data Engineer",
            "location_raw": "Remote - Canada",
            "description": "Remote Canada. Python SQL.",
        }
        r = apply_hard_filters(job, _cfg("strict"))
        self.assertEqual(r.salary_verdict, "FAIL")
        self.assertEqual(r.verdict, "FAIL")

    def test_none_ignores_floor(self):
        job = {
            "title": "Senior Data Engineer",
            "location_raw": "Remote - Canada",
            "description": "Remote Canada.",
            "salary_min": 80000,
            "salary_max": 90000,
            "salary_currency": "CAD",
        }
        r = apply_hard_filters(job, _cfg("none"))
        self.assertEqual(r.salary_verdict, "PASS")
        self.assertNotEqual(r.verdict, "FAIL")

    def test_range_below_floor_fails_flexible(self):
        job = {
            "title": "Data Engineer",
            "location_raw": "Remote - Canada",
            "description": "Remote Canada. Base salary CAD 100000-110000.",
            "salary_min": 100000,
            "salary_max": 110000,
            "salary_currency": "CAD",
        }
        r = apply_hard_filters(job, _cfg("flexible"))
        self.assertEqual(r.salary_verdict, "FAIL")

    def test_range_meeting_floor_passes(self):
        job = {
            "title": "Data Engineer",
            "location_raw": "Remote - Canada",
            "description": "Remote Canada.",
            "salary_min": 120000,
            "salary_max": 150000,
            "salary_currency": "CAD",
        }
        r = apply_hard_filters(job, _cfg("flexible"))
        self.assertEqual(r.salary_verdict, "PASS")

    def test_usd_not_equated_one_to_one(self):
        # USD 100k ≈ CAD 135k at 1.35 — above CAD 130k floor → PASS with FX note
        job = {
            "title": "Data Engineer",
            "location_raw": "Remote - Canada",
            "description": "Remote Canada.",
            "salary_min": 100000,
            "salary_max": 100000,
            "salary_currency": "USD",
        }
        r = apply_hard_filters(job, _cfg("flexible"))
        self.assertEqual(r.salary_verdict, "PASS")
        self.assertTrue(any("usd_to_cad" in x.casefold() for x in r.reasons))

        # USD 80k ≈ CAD 108k — below CAD 130k → FAIL
        job2 = dict(job)
        job2["salary_min"] = job2["salary_max"] = 80000
        r2 = apply_hard_filters(job2, _cfg("flexible"))
        self.assertEqual(r2.salary_verdict, "FAIL")
        self.assertTrue(any("never treated as cad 1:1" in x.casefold() for x in r2.reasons))


class UncertaintyClassifyTests(unittest.TestCase):
    def test_us_primary_not_enrichable_when_complete(self):
        from jobseek.uncertainty import classify_uncertainty

        row = {
            "description_complete": 1,
            "description": "x" * 200,
            "location_raw": "United States",
            "hard_filter_json": {
                "eligibility": "UNCERTAIN",
                "title_match": True,
                "relevance": "MATCH",
                "reasons": ["US-primary remote without explicit Canadian eligibility"],
            },
        }
        out = classify_uncertainty(row)
        self.assertEqual(out["category"], "us_primary_without_canada_evidence")
        self.assertFalse(out["enrichable"])

    def test_incomplete_is_enrichable(self):
        from jobseek.uncertainty import classify_uncertainty

        row = {
            "description_complete": 0,
            "description": "stub",
            "location_raw": "5 Locations",
            "hard_filter_json": {
                "eligibility": "UNCERTAIN",
                "title_match": True,
                "relevance": "MATCH",
                "reasons": ["location/Canada eligibility not evidenced (unknown)"],
            },
        }
        out = classify_uncertainty(row)
        self.assertEqual(out["category"], "missing_incomplete_description")
        self.assertTrue(out["enrichable"])


if __name__ == "__main__":
    unittest.main()
