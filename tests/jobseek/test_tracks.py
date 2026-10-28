"""Engineering track matching tests."""

from __future__ import annotations

import unittest

from jobseek.filters.tracks import detect_seniority, match_track


SEARCH = {
    "tracks": ["ai_engineering", "data_engineering", "forward_deployed"],
    "track_aliases": {
        "ai_engineering": ["AI Engineer", "Applied AI Engineer"],
        "data_engineering": ["Data Engineer", "Senior Data Engineer"],
        "forward_deployed": ["Forward Deployed Engineer"],
    },
    "seniority": ["senior", "staff"],
    "custom_title_overrides": [],
}


class TrackTests(unittest.TestCase):
    def test_ai_engineer_matches(self):
        result = match_track("Senior AI Engineer", SEARCH)
        self.assertTrue(result.matched)
        self.assertIn("ai_engineering", result.tracks)
        self.assertEqual(result.seniority, "senior")

    def test_unrelated_title_fails(self):
        result = match_track("Retail Store Manager", SEARCH)
        self.assertFalse(result.matched)

    def test_custom_override(self):
        cfg = {**SEARCH, "custom_title_overrides": ["Solutions Architect"]}
        result = match_track("Cloud Solutions Architect", cfg)
        self.assertTrue(result.matched)

    def test_seniority_detection(self):
        self.assertEqual(detect_seniority("Staff Data Engineer"), "staff")
        self.assertEqual(detect_seniority("Junior Developer"), "junior")


if __name__ == "__main__":
    unittest.main()
