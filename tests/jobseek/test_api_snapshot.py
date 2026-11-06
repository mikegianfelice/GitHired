"""API snapshot export — Canada-eligible only, advertised salaries, stable ids."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jobseek.api_snapshot import (
    build_api_snapshot,
    description_excerpt,
    write_api_snapshot,
)


def _job(**kwargs):
    base = {
        "title": "Senior Data Engineer",
        "company": "Acme",
        "location_raw": "Remote - Canada",
        "description": "Build pipelines with Python Spark Airflow. Salary CAD $160,000–$190,000.",
        "description_complete": 1,
        "url": "https://boards.greenhouse.io/acme/jobs/1001",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/1001",
        "source": "greenhouse",
        "ats_provider": "greenhouse",
        "ats_job_id": "1001",
        "salary_min": 160_000,
        "salary_max": 190_000,
        "salary_currency": "CAD",
        "first_seen": "2026-11-01T00:00:00Z",
        "last_seen": "2026-11-04T00:00:00Z",
        "removed_at": None,
    }
    base.update(kwargs)
    return base


class ApiSnapshotTests(unittest.TestCase):
    def test_includes_eligible_excludes_us_only(self):
        jobs = [
            _job(),
            _job(
                title="Staff Engineer",
                company="US Co",
                location_raw="Remote, USA",
                url="https://jobs.lever.co/usco/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                apply_url="https://jobs.lever.co/usco/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                ats_job_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            ),
        ]
        snap = build_api_snapshot(jobs, limit=50)
        self.assertGreaterEqual(snap["count"], 1)
        companies = {j["company"] for j in snap["jobs"]}
        self.assertIn("Acme", companies)
        self.assertNotIn("US Co", companies)
        for j in snap["jobs"]:
            self.assertTrue(j["id"])
            self.assertTrue(j["apply_url"].startswith("http"))

    def test_description_excerpt_truncated(self):
        text = "<p>" + ("word " * 2000) + "</p>"
        excerpt = description_excerpt(text, limit=100)
        self.assertIsNotNone(excerpt)
        assert excerpt is not None
        self.assertLessEqual(len(excerpt), 100)
        self.assertNotIn("<p>", excerpt)

    def test_salary_kind_advertised_only(self):
        snap = build_api_snapshot([_job()], limit=10)
        job = snap["jobs"][0]
        self.assertEqual(job["salary_kind"], "advertised_base")
        self.assertTrue(job["salary_available"])
        self.assertEqual(snap["salary_policy"]["estimates"], False)

    def test_write_snapshot(self):
        snap = build_api_snapshot([_job()], limit=10)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.snapshot.json"
            meta = write_api_snapshot(snap, path)
            self.assertTrue(meta["ok"])
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["count"], snap["count"])
            self.assertEqual(loaded["dataset_id"], snap["dataset_id"])


if __name__ == "__main__":
    unittest.main()
