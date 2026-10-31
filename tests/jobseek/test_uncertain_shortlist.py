"""Phase 4: ranked UNCERTAIN secondary shortlist (never auto-confirmed)."""

from __future__ import annotations

import json
import unittest

from jobseek.digest.build import render_digest_markdown, _uncertain_why
from jobseek.filters.hard import apply_hard_filters
from jobseek.rank.scorer import score_deterministic


SEARCH = {
    "tracks": ["software_engineering", "data_engineering"],
    "seniority": {"include": ["mid", "senior"], "exclude": ["intern"]},
    "location": {
        "modes": ["remote_canada", "hybrid"],
        "preferred": ["Canada remote", "Remote Canada"],
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
        "cities": ["Toronto"],
        "provinces": ["Ontario", "ON"],
    },
    "salary": {"reject_missing": False, "floors": {}},
}


class UncertainWhyTests(unittest.TestCase):
    def test_missing_location_evidence(self):
        job = {
            "location_raw": "",
            "hard_filter_json": json.dumps(
                {"eligibility": "UNCERTAIN", "reasons": ["location not evidenced for Canada"]}
            ),
        }
        why = _uncertain_why(job)
        self.assertTrue(why)
        self.assertNotIn("ELIGIBLE", why)

    def test_explicit_restriction_signal_labeled(self):
        job = {
            "location_raw": "Remote",
            "hard_filter_json": json.dumps(
                {
                    "eligibility": "UNCERTAIN",
                    "reasons": ["US-only remote restriction signal without Canada evidence"],
                }
            ),
        }
        why = _uncertain_why(job).casefold()
        self.assertTrue("restrict" in why or "us-only" in why or "united states" in why)


class UncertainNotPromotedTests(unittest.TestCase):
    def test_silent_remote_stays_uncertain(self):
        job = {
            "title": "Senior Software Engineer",
            "location_raw": "Remote",
            "description": "Fully remote role. Competitive compensation.",
            "url": "https://boards.greenhouse.io/acme/jobs/1",
            "source": "greenhouse",
        }
        hf = apply_hard_filters(job, SEARCH)
        self.assertEqual(hf.eligibility, "UNCERTAIN")
        score = score_deterministic(job, search_cfg=SEARCH, profile={})
        self.assertEqual(score.hard_filter.eligibility, "UNCERTAIN")
        self.assertLessEqual(score.overall, 62)


class DigestUncertainSectionTests(unittest.TestCase):
    def test_markdown_includes_uncertain_shortlist(self):
        digest = {
            "confirmed_matches": 1,
            "count": 1,
            "uncertain_opportunities": 3,
            "next": "githired jobs --eligibility uncertain",
            "jobs": [
                {
                    "title": "Data Engineer",
                    "company": "Acme",
                    "overall": 88,
                    "location_raw": "Remote - Canada",
                    "url": "https://example.com/1",
                    "strengths_json": "[]",
                    "gaps_json": "[]",
                    "hard_filter_json": json.dumps({"eligibility": "ELIGIBLE"}),
                }
            ],
            "uncertain_shortlist": [
                {
                    "title": "Backend Engineer",
                    "company": "MysteryCo",
                    "overall": 55,
                    "location_raw": "Remote",
                    "url": "https://example.com/u1",
                    "hard_filter_json": json.dumps(
                        {
                            "eligibility": "UNCERTAIN",
                            "reasons": ["Canada eligibility not clearly evidenced"],
                        }
                    ),
                }
            ],
        }
        md = render_digest_markdown(digest)
        self.assertIn("Top uncertain opportunities", md)
        self.assertIn("not promoted to confirmed", md)
        self.assertIn("Why uncertain", md)
        self.assertIn("MysteryCo", md)
        # Confirmed section still first
        self.assertLess(md.index("Acme"), md.index("MysteryCo"))


if __name__ == "__main__":
    unittest.main()
