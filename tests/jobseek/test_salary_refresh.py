"""Salary backfill and coverage report."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jobseek.db.store import Database
from jobseek.models import RawJob
from jobseek.salary_refresh import refresh_salaries, salary_coverage_report


class SalaryRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "t.db")

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_reparse_description_recovers_salary(self):
        job = RawJob(
            company="Acme",
            title="Data Engineer",
            url="https://boards.greenhouse.io/acme/jobs/1",
            source="greenhouse",
            ats_provider="greenhouse",
            ats_job_id="1",
            description="Hybrid Toronto. Base salary CAD $140,000 - $160,000 annually.",
            description_complete=True,
        )
        self.db.upsert_job(job)
        before = salary_coverage_report(self.db)
        self.assertEqual(before["totals"]["verified"], 0)
        result = refresh_salaries(self.db, limit=10, refetch_structured=False)
        self.assertGreaterEqual(result["recovered"], 1)
        after = salary_coverage_report(self.db)
        self.assertGreaterEqual(after["totals"]["verified"], 1)
        row = self.db._conn.execute(
            "SELECT salary_min, salary_max, salary_currency, salary_confidence, first_seen FROM jobs"
        ).fetchone()
        self.assertEqual(row["salary_currency"], "CAD")
        self.assertEqual(row["salary_min"], 140000.0)
        self.assertEqual(row["salary_confidence"], "verified")
        self.assertIsNotNone(row["first_seen"])

    def test_does_not_overwrite_verified_with_null(self):
        job = RawJob(
            company="Acme",
            title="Engineer",
            url="https://boards.greenhouse.io/acme/jobs/2",
            source="greenhouse",
            ats_provider="greenhouse",
            ats_job_id="2",
            description="No pay listed.",
            salary_min=150000,
            salary_max=180000,
            salary_currency="CAD",
            description_complete=True,
        )
        jid, _ = self.db.upsert_job(job)
        self.db._conn.execute(
            "UPDATE jobs SET salary_confidence='verified' WHERE id=?",
            (jid,),
        )
        self.db._conn.commit()
        refresh_salaries(self.db, limit=10)
        row = self.db._conn.execute(
            "SELECT salary_min, salary_confidence FROM jobs WHERE id=?",
            (jid,),
        ).fetchone()
        self.assertEqual(row["salary_min"], 150000.0)
        self.assertEqual(row["salary_confidence"], "verified")


if __name__ == "__main__":
    unittest.main()
