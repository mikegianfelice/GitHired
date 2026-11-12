"""Automated quality gates for public inventory and eligibility correctness."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jobseek.filters.location import classify_canada_eligibility, default_city_office_arrangement
from jobseek.public_shortlist.export import DEFAULT_LIMIT, PUBLIC_SEARCH, select_public_jobs
from jobseek.showcase.top_paying import SHOWCASE_SEARCH

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "api" / "data" / "jobs.snapshot.json"
SITE_JOBS = ROOT / "site" / "jobs.json"


class CityOfficeEligibilityGates(unittest.TestCase):
    def test_default_city_office_arrangement(self):
        self.assertEqual(default_city_office_arrangement("Toronto, Canada"), "onsite")
        self.assertIsNone(default_city_office_arrangement("Toronto (Remote)"))
        self.assertIsNone(default_city_office_arrangement("Remote, Canada"))

    def test_city_only_canada_eligible_with_onsite_mode(self):
        cfg = {
            **SHOWCASE_SEARCH,
            "location": {
                **(SHOWCASE_SEARCH.get("location") or {}),
                "modes": ["remote_canada", "hybrid", "onsite"],
                "cities": ["Toronto"],
                "provinces": ["Ontario", "ON"],
            },
        }
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Toronto, Canada",
                "description": "Join our Toronto engineering team.",
            },
            cfg,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")


class SnapshotSyncGates(unittest.TestCase):
    def test_snapshot_present_and_within_cap(self):
        if not SNAPSHOT.exists():
            self.skipTest("api snapshot missing")
        snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        jobs = snap.get("jobs") or []
        self.assertGreaterEqual(len(jobs), 200)
        self.assertLessEqual(len(jobs), DEFAULT_LIMIT)
        self.assertTrue(snap.get("dataset_id"))
        self.assertTrue(snap.get("generated_at"))

    def test_site_and_api_counts_close(self):
        if not SNAPSHOT.exists() or not SITE_JOBS.exists():
            self.skipTest("snapshots missing")
        api_n = len(json.loads(SNAPSHOT.read_text(encoding="utf-8")).get("jobs") or [])
        site_n = len(json.loads(SITE_JOBS.read_text(encoding="utf-8")).get("jobs") or [])
        # Allow temporary drift during partial deploys; flag large gaps.
        self.assertLessEqual(abs(api_n - site_n), 80)

    def test_public_jobs_are_canada_eligible_shape(self):
        if not SNAPSHOT.exists():
            self.skipTest("api snapshot missing")
        snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        for job in (snap.get("jobs") or [])[:50]:
            self.assertTrue(job.get("apply_url"))
            self.assertIn(job.get("work_arrangement"), ("remote", "hybrid", "onsite", "unspecified"))
            self.assertTrue(job.get("title"))
            self.assertTrue(job.get("company"))


class PublicExportCapGate(unittest.TestCase):
    def test_default_limit_is_soft_ceiling_not_inventory_cap(self):
        # Soft count ceiling; payload-size safeguard is authoritative for API.
        self.assertGreaterEqual(DEFAULT_LIMIT, 1000)
        self.assertEqual(PUBLIC_SEARCH["salary"]["policy"], "none")


if __name__ == "__main__":
    unittest.main()
