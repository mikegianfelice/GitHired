"""Deterministic Stage-1 ranking tests."""

from __future__ import annotations

import unittest

from jobseek.rank.scorer import score_deterministic, score_job
from jobseek.config_loader import Settings


SEARCH = {
    "tracks": ["ai_engineering"],
    "track_aliases": {"ai_engineering": ["AI Engineer", "Applied AI Engineer"]},
    "seniority": ["senior", "staff", "mid"],
    "location": {
        "modes": ["remote_canada"],
        "preferred": ["Canada remote", "Remote Canada"],
        "allow_us_employer_remote_with_canada_evidence": True,
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
    },
    "salary": {"reject_missing": False, "floors": {"CAD": 120000}},
    "recency_days": 30,
}

PROFILE = {
    "skills": {"primary": ["Python", "LLM"], "secondary": ["PyTorch"], "domain": ["AI"]},
    "experience": {"strong_domains": ["machine learning"]},
}


class DeterministicRankTests(unittest.TestCase):
    def test_canada_ai_role_scores_positive(self):
        job = {
            "title": "Senior AI Engineer",
            "location_raw": "Remote - Canada",
            "description": "Build LLM systems with Python and PyTorch. Remote in Canada.",
            "salary_min": 150000,
            "salary_currency": "CAD",
            "first_seen": "2026-10-01T00:00:00Z",
        }
        result = score_deterministic(job, search_cfg=SEARCH, profile=PROFILE)
        self.assertEqual(result.score_kind, "deterministic")
        self.assertEqual(result.model, "deterministic")
        self.assertGreater(result.overall, 50)
        self.assertTrue(result.hard_filter and result.hard_filter.verdict in ("PASS", "FLAG"))

    def test_us_only_fails_hard(self):
        job = {
            "title": "Applied AI Engineer",
            "location_raw": "Remote, United States",
            "description": "Must be located in the United States only.",
        }
        result = score_job(
            job,
            search_cfg=SEARCH,
            profile=PROFILE,
            settings=Settings(),
            use_llm=False,
        )
        self.assertEqual(result.overall, 0)
        self.assertEqual(result.score_kind, "hard_filter")

    def test_not_labeled_as_ai(self):
        job = {
            "title": "AI Engineer",
            "location_raw": "Canada remote",
            "description": "Python LLM work from Canada.",
        }
        result = score_deterministic(job, search_cfg=SEARCH, profile=PROFILE)
        self.assertNotIn("gpt", result.model.lower())
        self.assertNotIn("claude", result.model.lower())
        self.assertEqual(result.score_kind, "deterministic")


if __name__ == "__main__":
    unittest.main()
