"""Uncertainty CLI explanations must match hard-filter classifier evidence."""

from __future__ import annotations

import unittest

from jobseek.filters.hard import apply_hard_filters
from jobseek.filters.location import classify_canada_eligibility
from jobseek.uncertainty import classify_uncertainty


SEARCH = {
    "tracks": ["data_engineering"],
    "track_aliases": {
        "data_engineering": ["Data Engineer", "Senior Data Engineer"],
    },
    "seniority": {
        "include": ["mid", "senior", "staff"],
        "exclude": ["intern", "junior"],
    },
    "location": {
        "modes": ["remote_canada", "hybrid"],
        "cities": ["Toronto"],
        "provinces": ["Ontario", "ON"],
        "preferred": ["Remote - Canada"],
        "allow_us_employer_remote_with_canada_evidence": True,
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
    },
    "salary": {"policy": "flexible", "floors": {"CAD": 100_000}},
}


class UncertaintyExplanationTests(unittest.TestCase):
    def test_toronto_unspecified_arrangement_not_province_mismatch(self):
        job = {
            "title": "Data Engineer",
            "location_raw": "Toronto, ON, CAN",
            "description": "Join our Toronto data team. Python, SQL, Spark." + (" x" * 40),
            "url": "https://boards.greenhouse.io/bmo/jobs/1",
            "source": "greenhouse",
        }
        hard = apply_hard_filters(job, SEARCH)
        self.assertEqual(hard.eligibility, "UNCERTAIN")
        self.assertTrue(
            any("work arrangement not evidenced" in r.casefold() for r in hard.reasons)
        )
        # Must not claim city/province mismatch when city matched.
        self.assertFalse(
            any(
                "incompatible with candidate" in r.casefold()
                or "outside candidate" in r.casefold()
                for r in hard.reasons
            )
        )

        row = {
            "description_complete": 1,
            "description": job["description"],
            "location_raw": job["location_raw"],
            "hard_filter_json": {
                "eligibility": hard.eligibility,
                "title_match": hard.title_match,
                "relevance": hard.relevance,
                "reasons": list(hard.reasons),
            },
        }
        out = classify_uncertainty(row)
        self.assertEqual(out["category"], "work_arrangement_unspecified")
        self.assertIn("work arrangement is unspecified", out["summary"].casefold())
        self.assertNotIn("city/province evidence does not match", out["summary"].casefold())

    def test_explanations_agree_with_classifier_reasons(self):
        elig, _, reasons, _ = classify_canada_eligibility(
            {
                "title": "Data Engineer",
                "location_raw": "Toronto, ON",
                "description": "Toronto office data platform role.",
            },
            SEARCH,
        )
        self.assertEqual(elig, "UNCERTAIN")
        out = classify_uncertainty(
            {
                "description_complete": 1,
                "description": "Toronto office data platform role." + (" y" * 50),
                "location_raw": "Toronto, ON",
                "hard_filter_json": {
                    "eligibility": elig,
                    "title_match": True,
                    "relevance": "MATCH",
                    "reasons": reasons,
                },
            }
        )
        self.assertEqual(out["category"], "work_arrangement_unspecified")
        self.assertTrue(
            any("work arrangement" in r.casefold() for r in out["reasons"])
        )

    def test_genuine_province_mismatch_still_labeled(self):
        out = classify_uncertainty(
            {
                "description_complete": 1,
                "description": "x" * 200,
                "location_raw": "Canada Hybrid (Ontario)",
                "hard_filter_json": {
                    "eligibility": "UNCERTAIN",
                    "title_match": True,
                    "relevance": "MATCH",
                    "reasons": [
                        "hub-remote city Vancouver outside candidate city "
                        "without nationwide Canada evidence"
                    ],
                },
            }
        )
        self.assertEqual(out["category"], "province_or_city_restriction")
        self.assertIn("city/province", out["summary"].casefold())

    def test_positive_candidate_city_phrase_not_province_mismatch(self):
        # Regression: "candidate city" substring used to fire province_or_city_restriction.
        out = classify_uncertainty(
            {
                "description_complete": 1,
                "description": "x" * 200,
                "location_raw": "Toronto, ON",
                "hard_filter_json": {
                    "eligibility": "UNCERTAIN",
                    "title_match": True,
                    "relevance": "MATCH",
                    "reasons": [
                        "matched Canadian city: Toronto",
                        "candidate-compatible: job cities include candidate city (Toronto)",
                        "uncertainty_code=work_arrangement_unspecified",
                        "work arrangement not evidenced (unknown); cannot confirm "
                        "against modes ['hybrid', 'remote_canada']",
                    ],
                },
            }
        )
        self.assertEqual(out["category"], "work_arrangement_unspecified")


if __name__ == "__main__":
    unittest.main()
