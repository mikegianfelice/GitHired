"""Track taxonomy regressions — contiguous titles, not token bags."""

from __future__ import annotations

import unittest

from jobseek.filters.tracks import match_track
from jobseek.rank.scorer import score_deterministic


SEARCH_DE = {
    "tracks": ["data_engineering", "analytics_engineering"],
    "seniority": {
        "include": ["mid", "senior", "staff", "principal", "lead"],
        "exclude": ["intern", "coop", "student", "new_grad", "junior"],
    },
    "location": {
        "modes": ["remote_canada", "hybrid"],
        "cities": ["Toronto"],
        "provinces": ["Ontario", "ON"],
        "reject_us_only_remote": True,
    },
    "salary": {"reject_missing": False, "floors": {"CAD": 130000}},
}

SEARCH_PLATFORM = {
    **SEARCH_DE,
    "tracks": ["platform_engineering"],
}

SEARCH_MIXED = {
    **SEARCH_DE,
    "tracks": ["data_engineering", "platform_engineering", "devops_sre"],
}

PROFILE = {
    "skills": {
        "primary": ["Python", "SQL", "Databricks", "Spark", "Azure", "Airflow"],
        "secondary": ["dbt", "Kafka"],
        "domain": ["data platforms"],
    }
}


class FalsePositiveTitleTests(unittest.TestCase):
    def test_data_center_electrical_not_data_engineering(self):
        result = match_track("Data Center Electrical R&D Engineer", SEARCH_DE)
        self.assertFalse(result.matched)

    def test_database_excellence_ruby_not_data_engineering(self):
        result = match_track(
            "Senior Backend Engineer, Database Excellence (Ruby)", SEARCH_DE
        )
        self.assertFalse(result.matched)

    def test_ux_platform_not_platform_engineering(self):
        result = match_track(
            "Manager, Software Engineering - UX Platform", SEARCH_PLATFORM
        )
        self.assertFalse(result.matched)

    def test_mobile_platform_ios_not_platform(self):
        result = match_track(
            "Software Engineer, Mobile Platform (iOS)", SEARCH_PLATFORM
        )
        self.assertFalse(result.matched)

    def test_sre_not_matching_data_only_tracks(self):
        result = match_track(
            "Senior Site Reliability Engineer (Observability & Analytics) – Platform Infra",
            SEARCH_DE,
        )
        self.assertFalse(result.matched)


class TruePositiveTitleTests(unittest.TestCase):
    def test_data_engineer(self):
        self.assertTrue(match_track("Senior Data Engineer", SEARCH_DE).matched)
        self.assertTrue(match_track("Staff Data Engineer", SEARCH_DE).matched)
        self.assertTrue(
            match_track("Staff Software Engineer, Risk Data Engineering", SEARCH_DE).matched
        )

    def test_analytics_engineer(self):
        self.assertTrue(match_track("Analytics Engineer", SEARCH_DE).matched)

    def test_platform_engineer_exact(self):
        self.assertTrue(match_track("Platform Engineer", SEARCH_PLATFORM).matched)
        self.assertTrue(
            match_track("Senior Infrastructure Engineer", SEARCH_PLATFORM).matched
        )


class RankingRelevanceTests(unittest.TestCase):
    def test_toronto_de_outranks_london_infra(self):
        toronto = score_deterministic(
            {
                "title": "Staff Software Engineer, Risk Data Engineering",
                "location_raw": "Toronto",
                "description": "Airflow Spark Kafka SQL data pipelines. Toronto office.",
                "first_seen": "2026-10-01T00:00:00Z",
            },
            search_cfg=SEARCH_MIXED,
            profile=PROFILE,
        )
        london = score_deterministic(
            {
                "title": "Senior Infrastructure Software Engineer, Apps Platform",
                "location_raw": "London, UK",
                "description": "Kubernetes Terraform on the platform. On-call in London.",
                "first_seen": "2026-10-01T00:00:00Z",
            },
            search_cfg=SEARCH_MIXED,
            profile=PROFILE,
        )
        self.assertEqual(toronto.hard_filter.eligibility, "ELIGIBLE")
        self.assertEqual(london.overall, 0)
        self.assertEqual(london.score_kind, "hard_filter")
        self.assertGreater(toronto.overall, 70)

    def test_missing_salary_not_boosted(self):
        scored = score_deterministic(
            {
                "title": "Senior Data Engineer",
                "location_raw": "Remote - Canada",
                "description": "Python SQL Spark. Remote in Canada.",
                "first_seen": "2026-10-01T00:00:00Z",
            },
            search_cfg=SEARCH_DE,
            profile=PROFILE,
        )
        self.assertEqual(scored.scores.get("salary"), 50.0)

    def test_eligible_outranks_uncertain(self):
        eligible = score_deterministic(
            {
                "title": "Senior Data Engineer",
                "location_raw": "Toronto, ON",
                "description": "Python SQL Airflow.",
                "first_seen": "2026-10-01T00:00:00Z",
            },
            search_cfg=SEARCH_DE,
            profile=PROFILE,
        )
        uncertain = score_deterministic(
            {
                "title": "Senior Data Engineer",
                "location_raw": "Remote",
                "description": "Python SQL Airflow. Fully remote.",
                "first_seen": "2026-10-01T00:00:00Z",
            },
            search_cfg=SEARCH_DE,
            profile=PROFILE,
        )
        self.assertEqual(eligible.hard_filter.eligibility, "ELIGIBLE")
        self.assertEqual(uncertain.hard_filter.eligibility, "UNCERTAIN")
        self.assertGreater(eligible.overall, uncertain.overall)


if __name__ == "__main__":
    unittest.main()
