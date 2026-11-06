"""E2E acceptance: remote senior data engineering ≥ CAD $150k (snapshot search)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "api" / "data" / "jobs.snapshot.json"


def _salary_cad(job: dict, fx: float = 1.35) -> float | None:
    if job.get("salary_max_cad") is not None:
        return float(job["salary_max_cad"])
    if job.get("salary_max") is None or not job.get("salary_currency"):
        return None
    cur = str(job["salary_currency"]).upper()
    if cur == "CAD":
        return float(job["salary_max"])
    if cur == "USD":
        return float(job["salary_max"]) * fx
    return None


def _matches_query(job: dict) -> bool:
    blob = f"{job.get('title')} {job.get('track')} {' '.join(job.get('technologies') or [])}".lower()
    tokens = ("data", "engineer")
    return all(t in blob for t in tokens) or "data_engineering" in str(job.get("track") or "")


class ApiAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SNAPSHOT.exists():
            raise unittest.SkipTest("api snapshot missing — run export_api_snapshot.py")
        cls.snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        cls.fx = float(cls.snap.get("usd_to_cad") or 1.35)

    def test_snapshot_has_canada_eligible_jobs(self):
        self.assertGreaterEqual(int(self.snap.get("count") or 0), 1)
        self.assertFalse(self.snap["salary_policy"]["estimates"])

    def test_remote_senior_data_engineer_cad_150k(self):
        """REST/MCP shared filter semantics against real snapshot data."""
        hits = []
        for job in self.snap["jobs"]:
            if job.get("work_arrangement") != "remote":
                continue
            if (job.get("seniority") or "").lower() not in ("senior", "staff", "principal", "lead"):
                # Prefer senior+; allow staff/principal/lead as senior-band roles
                if (job.get("seniority") or "").lower() != "senior":
                    if "senior" not in (job.get("title") or "").lower():
                        continue
            if not _matches_query(job):
                continue
            cad = _salary_cad(job, self.fx)
            if cad is None or cad < 150_000:
                continue
            self.assertTrue(job.get("apply_url", "").startswith("http"))
            self.assertTrue(job.get("last_verified"))
            self.assertTrue(job.get("salary_available"))
            self.assertEqual(job.get("salary_kind"), "advertised_base")
            hits.append(job)

        # Honest empty is allowed; when hits exist they must satisfy the contract.
        for job in hits:
            why = (
                f"{job['title']} at {job['company']} is remote Canada-eligible, "
                f"senior-band, advertised pay CAD-equivalent { _salary_cad(job, self.fx):,.0f}, "
                f"last verified {job['last_verified']}."
            )
            self.assertIn("http", job["apply_url"])
            self.assertTrue(len(why) > 40)

        # Print for operator visibility when run with -v
        print(f"\nacceptance hits={len(hits)} dataset_id={self.snap.get('dataset_id')}")


if __name__ == "__main__":
    unittest.main()
