"""Worldwide-remote include path: explicit global signals only, null province, ranking."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from jobseek.public_shortlist.export import (
    PUBLIC_SEARCH,
    _has_explicit_global_remote_signal,
    _remote_scope,
    select_public_jobs,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def _job(**overrides):
    base = {
        "title": "Senior Software Engineer",
        "company": "GlobalCo",
        "location_raw": "Remote",
        "description": (
            "We are a remote-first team. Work from anywhere. Python TypeScript."
            + (" x" * 40)
        ),
        "description_complete": 1,
        "url": "https://boards.greenhouse.io/globalco/jobs/99901",
        "apply_url": "https://boards.greenhouse.io/globalco/jobs/99901",
        "source": "greenhouse",
        "ats_provider": "greenhouse",
        "first_seen": "2026-11-04T08:00:00Z",
        "last_seen": "2026-11-04T10:00:00Z",
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "removed_at": None,
    }
    base.update(overrides)
    return base


class ExplicitGlobalSignalTests(unittest.TestCase):
    def test_work_from_anywhere_counts(self):
        self.assertTrue(
            _has_explicit_global_remote_signal("Remote", "Work from anywhere with a home-office budget.")
        )

    def test_remote_global_location_counts(self):
        self.assertTrue(_has_explicit_global_remote_signal("Remote, Global", ""))
        self.assertTrue(_has_explicit_global_remote_signal("Remote - Worldwide", ""))

    def test_bare_remote_does_not_count(self):
        self.assertFalse(_has_explicit_global_remote_signal("Remote", "Build platforms with Python."))

    def test_incidental_global_team_does_not_count(self):
        self.assertFalse(
            _has_explicit_global_remote_signal(
                "Remote",
                "We are a global technology company headquartered in Toronto serving customers worldwide.",
            )
        )

    def test_ideas_from_anywhere_does_not_count(self):
        self.assertFalse(
            _has_explicit_global_remote_signal(
                "Remote",
                "Good ideas can come from anywhere, and people are trusted to ship.",
            )
        )

    def test_elevenlabs_style_global_team_location_signal(self):
        self.assertTrue(
            _has_explicit_global_remote_signal(
                "Remote",
                "Global team: We prioritize your talent, not your location. Python.",
            )
        )

    def test_us_only_location_never_global(self):
        self.assertFalse(
            _has_explicit_global_remote_signal(
                "Remote - US",
                "Work from anywhere in the United States.",
            )
        )

    def test_ukraine_anywhere_location_not_global_token(self):
        self.assertFalse(_has_explicit_global_remote_signal("Ukraine Anywhere", ""))


class RemoteScopePrecedenceTests(unittest.TestCase):
    def test_canada_beats_global_marketing(self):
        scope = _remote_scope(
            "Remote, Canada",
            "remote",
            [],
            "Work from anywhere. Python.",
        )
        self.assertEqual(scope, "canada")

    def test_province_city_remote_beats_anywhere_perk(self):
        scope = _remote_scope(
            "Toronto (Remote)",
            "remote",
            ["Ontario"],
            "Employees can work from anywhere. Python.",
        )
        self.assertEqual(scope, "province")

    def test_explicit_global_remote(self):
        scope = _remote_scope("Remote", "remote", [], "Work from anywhere. Python.")
        self.assertEqual(scope, "global")


class IncludeGlobalRemoteSelectTests(unittest.TestCase):
    def test_default_config_includes_global(self):
        self.assertTrue(PUBLIC_SEARCH.get("include_global_remote"))

    def test_includes_global_with_null_province(self):
        selected = select_public_jobs([_job()], limit=5, now=NOW)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].remote_scope, "global")
        self.assertIsNone(selected[0].province)

    def test_off_toggle_excludes_global(self):
        cfg = {**PUBLIC_SEARCH, "include_global_remote": False}
        selected = select_public_jobs([_job()], limit=5, now=NOW, search_cfg=cfg)
        self.assertEqual(selected, [])

    def test_us_only_remote_stays_out(self):
        selected = select_public_jobs(
            [
                _job(
                    location_raw="Remote - US",
                    description="US remote only. Work from anywhere in the US." + (" y" * 40),
                    url="https://boards.greenhouse.io/globalco/jobs/us-1",
                    apply_url="https://boards.greenhouse.io/globalco/jobs/us-1",
                )
            ],
            limit=5,
            now=NOW,
        )
        self.assertEqual(selected, [])

    def test_global_ranks_below_canada(self):
        canada = _job(
            company="CanadaCo",
            location_raw="Remote - Canada",
            description="Remote in Canada. Python TypeScript." + (" z" * 40),
            url="https://boards.greenhouse.io/canadaco/jobs/1",
            apply_url="https://boards.greenhouse.io/canadaco/jobs/1",
            salary_min=160000,
            salary_max=190000,
            salary_currency="CAD",
        )
        worldwide = _job(
            company="WorldCo",
            location_raw="Remote",
            description="Work from anywhere. Python TypeScript." + (" w" * 40),
            url="https://boards.greenhouse.io/worldco/jobs/2",
            apply_url="https://boards.greenhouse.io/worldco/jobs/2",
            salary_min=200000,
            salary_max=250000,
            salary_currency="USD",
        )
        selected = select_public_jobs([worldwide, canada], limit=10, now=NOW)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0].remote_scope, "canada")
        self.assertEqual(selected[1].remote_scope, "global")


if __name__ == "__main__":
    unittest.main()
