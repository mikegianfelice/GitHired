"""Progressive pipeline: list-only discover, enrich leases, provisional ranking."""

from __future__ import annotations

import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from jobseek.adapters.workday import WorkdayAdapter
from jobseek.db.store import Database, enrichment_status_for_job
from jobseek.http_client import HttpResponse
from jobseek.models import RawJob
from jobseek.rank.fingerprint import scoring_fingerprint
from jobseek.rank.scorer import STAGE1_MODELS


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EnrichmentStatusTests(unittest.TestCase):
    def test_status_derivation(self):
        self.assertEqual(
            enrichment_status_for_job(ats_provider="workday", description_complete=False),
            "pending",
        )
        self.assertEqual(
            enrichment_status_for_job(ats_provider="workday", description_complete=True),
            "complete",
        )
        self.assertEqual(
            enrichment_status_for_job(ats_provider="greenhouse", description_complete=True),
            "complete",
        )
        self.assertEqual(
            enrichment_status_for_job(
                ats_provider="workday",
                description_complete=False,
                previous_status="failed",
            ),
            "failed",
        )


class ListOnlyDiscoverPersistTests(unittest.TestCase):
    def test_workday_list_stub_is_pending_and_queryable(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            stub = RawJob(
                company="RBC",
                title="Senior Data Engineer",
                url="https://rbc.wd3.myworkdayjobs.com/RBCGLOBAL1/job/Toronto/Role_R1",
                source="workday",
                ats_provider="workday",
                ats_job_id="R1",
                location_raw="5 Locations",
                description="Senior Data Engineer",
                description_complete=False,
            )
            jid, is_new = db.upsert_job(stub)
            self.assertTrue(is_new)
            row = db.get_job(jid)
            assert row is not None
            self.assertEqual(row["enrichment_status"], "pending")
            self.assertEqual(row["description_complete"], 0)
            # Queryable before enrichment
            self.assertEqual(db.get_job(jid)["title"], "Senior Data Engineer")
            db.close()

    def test_complete_description_preserved_on_list_refresh(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            full = RawJob(
                company="TD",
                title="Data Engineer",
                url="https://example.com/td/1",
                source="workday",
                ats_provider="workday",
                ats_job_id="R9",
                description="FULL BODY " + ("x" * 400),
                description_complete=True,
                description_fetched_at=_now(),
                location_raw="Toronto, ON",
            )
            jid, _ = db.upsert_job(full)
            stub = RawJob(
                company="TD",
                title="Data Engineer",
                url="https://example.com/td/1",
                source="workday",
                ats_provider="workday",
                ats_job_id="R9",
                description=None,
                description_complete=False,
                location_raw="3 Locations",
            )
            db.upsert_job(stub)
            row = db.get_job(jid)
            assert row is not None
            self.assertIn("FULL BODY", row["description"])
            self.assertEqual(row["description_complete"], 1)
            self.assertEqual(row["enrichment_status"], "complete")
            db.close()


class EnrichLeaseTests(unittest.TestCase):
    def test_claim_is_exclusive_and_resumable(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            for i in range(5):
                db.upsert_job(
                    RawJob(
                        company="BMO",
                        title=f"Engineer {i}",
                        url=f"https://bmo.example/job/{i}",
                        source="workday",
                        ats_provider="workday",
                        ats_job_id=f"R{i}",
                        description=f"Engineer {i}",
                        description_complete=False,
                    )
                )
            a = db.claim_enrichment_jobs(limit=3, worker_id="w-a", lease_s=60)
            self.assertEqual(len(a), 3)
            b = db.claim_enrichment_jobs(limit=5, worker_id="w-b", lease_s=60)
            # Remaining 2 only
            self.assertEqual(len(b), 2)
            ids_a = {r["id"] for r in a}
            ids_b = {r["id"] for r in b}
            self.assertFalse(ids_a & ids_b)
            # Complete one; fail one (retry immediately); leave one processing with expired lease
            db.complete_enrichment(a[0]["id"], ok=True)
            db.complete_enrichment(
                a[1]["id"], ok=False, error="boom", retry_backoff_s=0
            )
            db._conn.execute(
                "UPDATE jobs SET enrich_lease_until = ? WHERE id = ?",
                ("2000-01-01T00:00:00Z", a[2]["id"]),
            )
            db._conn.commit()
            resumed = db.claim_enrichment_jobs(limit=10, worker_id="w-c", lease_s=60)
            resumed_ids = {r["id"] for r in resumed}
            self.assertIn(a[1]["id"], resumed_ids)  # failed (backoff elapsed)
            self.assertIn(a[2]["id"], resumed_ids)  # expired lease
            self.assertNotIn(a[0]["id"], resumed_ids)  # complete
            db.close()

    def test_concurrent_claims_no_duplicates(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            for i in range(40):
                db.upsert_job(
                    RawJob(
                        company="Intact",
                        title=f"Role {i}",
                        url=f"https://intact.example/job/{i}",
                        source="workday",
                        ats_provider="workday",
                        ats_job_id=f"R{i}",
                        description=f"Role {i}",
                        description_complete=False,
                    )
                )

            def _claim(wid: str) -> list[int]:
                rows = db.claim_enrichment_jobs(limit=15, worker_id=wid, lease_s=30)
                return [int(r["id"]) for r in rows]

            with ThreadPoolExecutor(max_workers=4) as pool:
                futs = [pool.submit(_claim, f"w{i}") for i in range(4)]
                all_ids: list[int] = []
                for f in futs:
                    all_ids.extend(f.result())
            self.assertEqual(len(all_ids), len(set(all_ids)))
            db.close()


class ProvisionalRankSafetyTests(unittest.TestCase):
    def test_provisional_never_in_confirmed_shortlist(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            job = RawJob(
                company="Shopify",
                title="Senior Data Engineer",
                url="https://example.com/s1",
                source="greenhouse",
                description="Python SQL remote Canada",
                location_raw="Remote - Canada",
                description_complete=False,
            )
            # Force incomplete greenhouse-like stub
            jid, _ = db.upsert_job(job)
            db._conn.execute(
                "UPDATE jobs SET description_complete = 0, enrichment_status = 'pending' WHERE id = ?",
                (jid,),
            )
            db._conn.commit()
            row = db.get_job(jid)
            assert row is not None
            db.save_score(
                jid,
                overall=90.0,
                scores={"skills": 90},
                hard_filter={
                    "verdict": "FLAG",
                    "eligibility": "UNCERTAIN",
                    "evidence": ["provisional"],
                },
                strengths=[],
                gaps=[],
                salary_alignment="ok",
                rejection_reasons=[],
                evidence=[],
                model="provisional/test",
                description_hash=row["description_hash"],
                score_kind="provisional",
                config_fingerprint="abc",
            )
            confirmed = db.list_jobs(
                limit=10, score_kind="deterministic", eligibility="ELIGIBLE"
            )
            self.assertEqual(confirmed, [])
            # Even provisional score_kind list requires care — confirmed path uses deterministic
            top = db.top_new_scored(limit=5, min_score=50, eligibility="ELIGIBLE")
            self.assertEqual(top, [])
            db.close()

    def test_fingerprint_skip_after_confirmed_rank(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            search = {"tracks": ["data_engineering"], "salary": {"min_cad": 130000}}
            profile = {"skills": {"primary": ["Python"]}, "experience": {"years": 7}}
            fp = scoring_fingerprint(search, profile)
            job = RawJob(
                company="Databricks",
                title="Analytics Engineer",
                url="https://example.com/d1",
                source="greenhouse",
                description="Python SQL Spark Databricks remote Canada Ontario",
                location_raw="Remote - Canada",
                description_complete=True,
                description_fetched_at=_now(),
            )
            jid, _ = db.upsert_job(job)
            row = db.get_job(jid)
            assert row is not None
            db.save_score(
                jid,
                overall=80,
                scores={},
                hard_filter={"verdict": "PASS", "eligibility": "ELIGIBLE"},
                strengths=[],
                gaps=[],
                salary_alignment="ok",
                rejection_reasons=[],
                evidence=[],
                model=STAGE1_MODELS[0],
                description_hash=row["description_hash"],
                score_kind="deterministic",
                config_fingerprint=fp,
            )
            pending = db.count_jobs_needing_score(
                score_kind="deterministic",
                current_model=STAGE1_MODELS,
                config_fingerprint=fp,
                require_complete=True,
            )
            self.assertEqual(pending, 0)
            db.close()


class WorkdayFetchDetailsOffTests(unittest.TestCase):
    def test_adapter_list_only_skips_detail_http(self):
        class _C:
            def __init__(self):
                self.gets = []
                self.posts = 0

            def post(self, url, *, json_body=None, headers=None):
                self.posts += 1
                body = {
                    "total": 1,
                    "jobPostings": [
                        {
                            "title": "Eng",
                            "externalPath": "/job/Toronto/Role_R1",
                            "locationsText": "Toronto, ON",
                            "bulletFields": ["R1"],
                        }
                    ],
                }
                return HttpResponse(200, json.dumps(body), url)

            def get(self, url, *, params=None, headers=None):
                self.gets.append(url)
                return HttpResponse(404, "{}", url)

        client = _C()
        company = {
            "name": "Sun Life",
            "ats": "workday",
            "board_token": "sunlife.wd3.myworkdayjobs.com/sunlife/sunlife",
        }
        adapter = WorkdayAdapter(client, fetch_details=False, list_budget_s=30)  # type: ignore[arg-type]
        result = adapter.fetch_company(company)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(client.gets, [])
        self.assertFalse(result.jobs[0].description_complete)


if __name__ == "__main__":
    unittest.main()
