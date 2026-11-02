"""Enrichment priority, employer fairness, lease ownership, relevance separation."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from jobseek.db.store import Database
from jobseek.enrich import prioritize_enrichment
from jobseek.enrich_priority import compute_enrich_priority, fair_select_for_enrichment
from jobseek.filters.hard import apply_hard_filters
from jobseek.models import RawJob


SEARCH = {
    "tracks": ["data_engineering", "analytics_engineering"],
    "track_aliases": {
        "data_engineering": ["data engineer", "senior data engineer"],
        "analytics_engineering": ["analytics engineer"],
    },
    "seniority": {"include": ["senior", "staff", "mid"], "exclude": ["intern", "junior"]},
    "location": {
        "modes": ["remote_canada", "hybrid"],
        "cities": ["Toronto"],
        "provinces": ["Ontario", "ON"],
    },
    "salary": {"floors": {"CAD": 130000}},
}

PROFILE = {
    "skills": {"primary": ["Python", "SQL", "Databricks", "Spark"]},
    "experience": {"years": 7},
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stub(
    company: str,
    title: str,
    *,
    jid: str,
    location: str = "Toronto, ON",
) -> RawJob:
    return RawJob(
        company=company,
        title=title,
        url=f"https://{company.casefold().replace(' ', '')}.example/job/{jid}",
        source="workday",
        ats_provider="workday",
        ats_job_id=jid,
        location_raw=location,
        description=title,
        description_complete=False,
    )


class PriorityScoringTests(unittest.TestCase):
    def test_track_match_outranks_banking_noise(self):
        eng = compute_enrich_priority(
            {"title": "Senior Data Engineer", "location_raw": "Toronto, ON", "company": "RBC"},
            SEARCH,
            PROFILE,
        )
        noise = compute_enrich_priority(
            {
                "title": "Personal Banker - Branch Advisor",
                "location_raw": "Toronto, ON",
                "company": "RBC",
            },
            SEARCH,
            PROFILE,
        )
        self.assertGreaterEqual(eng, 500)
        self.assertLessEqual(noise, 20)
        self.assertGreater(eng, noise)

    def test_missing_salary_not_penalized(self):
        a = compute_enrich_priority(
            {"title": "Data Engineer", "location_raw": "Remote - Canada"},
            SEARCH,
            PROFILE,
        )
        b = compute_enrich_priority(
            {
                "title": "Data Engineer",
                "location_raw": "Remote - Canada",
                "salary_raw": "CAD 140000",
                "salary_min": 140000,
                "salary_max": 160000,
            },
            SEARCH,
            PROFILE,
        )
        # Salary boost is positive but missing salary must not tank priority.
        self.assertGreaterEqual(a, 500)
        self.assertGreaterEqual(b, a)

    def test_missing_location_keeps_relevant_title_candidacy(self):
        pri = compute_enrich_priority(
            {"title": "Analytics Engineer", "location_raw": ""},
            SEARCH,
            PROFILE,
        )
        self.assertGreaterEqual(pri, 500)


class FairSelectAcceptanceTests(unittest.TestCase):
    def test_acceptance_limit_50_not_dominated_by_rbc_noise(self):
        """500 RBC noise + multi-employer engineering → limit=50 favors relevant + diverse."""
        ranked: list[dict] = []
        for i in range(500):
            job = {
                "id": i,
                "company": "RBC",
                "title": f"Customer Service Representative {i}",
                "location_raw": "Toronto, ON",
            }
            job["enrich_priority"] = compute_enrich_priority(job, SEARCH, PROFILE)
            ranked.append(job)
        for i in range(20):
            job = {
                "id": 1000 + i,
                "company": "RBC",
                "title": "Senior Data Engineer",
                "location_raw": "Toronto, ON",
            }
            job["enrich_priority"] = compute_enrich_priority(job, SEARCH, PROFILE)
            ranked.append(job)
        for i in range(15):
            job = {
                "id": 2000 + i,
                "company": "TD",
                "title": "Data Engineer",
                "location_raw": "Remote - Canada",
            }
            job["enrich_priority"] = compute_enrich_priority(job, SEARCH, PROFILE)
            ranked.append(job)
        for i in range(10):
            job = {
                "id": 3000 + i,
                "company": "Intact",
                "title": "Analytics Engineer",
                "location_raw": "Ontario Hybrid",
            }
            job["enrich_priority"] = compute_enrich_priority(job, SEARCH, PROFILE)
            ranked.append(job)
        for i in range(10):
            job = {
                "id": 4000 + i,
                "company": f"OtherCo{i}",
                "title": "Senior Data Engineer",
                "location_raw": "Canada",
            }
            job["enrich_priority"] = compute_enrich_priority(job, SEARCH, PROFILE)
            ranked.append(job)

        ranked.sort(key=lambda r: (-(r["enrich_priority"] or 0), r["id"]))
        selected = fair_select_for_enrichment(
            ranked, limit=50, max_per_company=12, min_priority=500
        )
        # 20+15+10+10 = 55 relevant; limit 50 → exactly 50, zero noise.
        self.assertEqual(len(selected), 50)
        companies = {r["company"] for r in selected}
        self.assertIn("TD", companies)
        self.assertIn("Intact", companies)
        self.assertTrue(any(c.startswith("OtherCo") for c in companies))
        titles = [r["title"] for r in selected]
        noise = sum(1 for t in titles if "Customer Service" in t)
        eng = sum(
            1
            for t in titles
            if "Data Engineer" in t or "Analytics Engineer" in t
        )
        self.assertGreaterEqual(eng, 40)
        self.assertLessEqual(noise, 5)
        rbc_eng = sum(
            1
            for r in selected
            if r["company"] == "RBC" and "Data Engineer" in r["title"]
        )
        rbc_noise = sum(
            1
            for r in selected
            if r["company"] == "RBC" and "Customer Service" in r["title"]
        )
        self.assertGreaterEqual(rbc_eng, 1)
        self.assertLessEqual(rbc_noise, 2)
        self.assertGreaterEqual(len(companies), 4)

    def test_db_claim_uses_priority_and_fairness(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            # Unique titles required: upsert dedupes company+title.
            for i in range(80):
                db.upsert_job(
                    _stub("RBC", f"Personal Banker {i}", jid=f"N{i}")
                )
            for i in range(8):
                db.upsert_job(
                    _stub(
                        "RBC",
                        f"Senior Data Engineer - Platform {i}",
                        jid=f"RE{i}",
                    )
                )
            for i in range(8):
                db.upsert_job(
                    _stub("TD", f"Data Engineer - Pipelines {i}", jid=f"TD{i}")
                )
            for i in range(6):
                db.upsert_job(
                    _stub(
                        "Intact",
                        f"Analytics Engineer - Metrics {i}",
                        jid=f"IN{i}",
                    )
                )
            prioritize_enrichment(db, search=SEARCH, profile=PROFILE, force=True)
            claimed = db.claim_enrichment_jobs(
                limit=20, worker_id="w1", lease_s=60, max_per_company=6
            )
            self.assertEqual(len(claimed), 20)
            companies = {r["company"] for r in claimed}
            self.assertGreaterEqual(len(companies), 3)
            eng = sum(
                1
                for r in claimed
                if "Engineer" in (r.get("title") or "")
                and "Banker" not in (r.get("title") or "")
            )
            self.assertGreaterEqual(eng, 15)
            db.close()


class LeaseOwnershipTests(unittest.TestCase):
    def test_two_workers_claim_simultaneously(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            for i in range(30):
                db.upsert_job(_stub("BMO", f"Data Engineer {i}", jid=f"B{i}"))
            prioritize_enrichment(db, search=SEARCH, profile=PROFILE, force=True)

            def _claim(wid: str) -> list[int]:
                return [
                    int(r["id"])
                    for r in db.claim_enrichment_jobs(limit=10, worker_id=wid, lease_s=60)
                ]

            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(_claim, "w-a")
                b = pool.submit(_claim, "w-b")
                ids = a.result() + b.result()
            self.assertEqual(len(ids), len(set(ids)))
            db.close()

    def test_stale_worker_cannot_complete_after_reclaim(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            jid, _ = db.upsert_job(_stub("TD", "Data Engineer", jid="X1"))
            first = db.claim_enrichment_jobs(limit=1, worker_id="old", lease_s=60)
            self.assertEqual(len(first), 1)
            token_old = first[0]["enrich_lease_token"]
            # Expire and reclaim
            db._conn.execute(
                "UPDATE jobs SET enrich_lease_until = ? WHERE id = ?",
                ("2000-01-01T00:00:00Z", jid),
            )
            db._conn.commit()
            second = db.claim_enrichment_jobs(limit=1, worker_id="new", lease_s=60)
            self.assertEqual(len(second), 1)
            token_new = second[0]["enrich_lease_token"]
            self.assertNotEqual(token_old, token_new)
            # Stale completion rejected
            ok = db.complete_enrichment(
                jid, ok=True, worker_id="old", lease_token=token_old
            )
            self.assertFalse(ok)
            row = db.get_job(jid)
            assert row is not None
            self.assertEqual(row["enrichment_status"], "processing")
            self.assertEqual(row["enrich_lease_owner"], "new")
            # New owner succeeds
            self.assertTrue(
                db.complete_enrichment(
                    jid, ok=True, worker_id="new", lease_token=token_new
                )
            )
            self.assertEqual(db.get_job(jid)["enrichment_status"], "complete")
            db.close()

    def test_lease_renewal_and_idempotent_complete(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            jid, _ = db.upsert_job(_stub("Intact", "Analytics Engineer", jid="Y1"))
            rows = db.claim_enrichment_jobs(limit=1, worker_id="w", lease_s=60)
            token = rows[0]["enrich_lease_token"]
            self.assertTrue(
                db.renew_enrichment_lease(
                    jid, worker_id="w", lease_token=token, lease_s=120
                )
            )
            self.assertFalse(
                db.renew_enrichment_lease(
                    jid, worker_id="other", lease_token=token, lease_s=120
                )
            )
            self.assertTrue(
                db.complete_enrichment(jid, ok=True, worker_id="w", lease_token=token)
            )
            # Idempotent re-complete of an already-complete job succeeds.
            self.assertTrue(
                db.complete_enrichment(jid, ok=True, worker_id="w", lease_token=token)
            )
            # Failure must not demote a complete description.
            self.assertFalse(
                db.complete_enrichment(
                    jid, ok=False, error="late fail", worker_id="w", lease_token=token
                )
            )
            self.assertEqual(db.get_job(jid)["enrichment_status"], "complete")
            db.close()

    def test_failure_sets_backoff_and_preserves_description(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            full = RawJob(
                company="Sun Life",
                title="Data Engineer",
                url="https://sunlife.example/job/1",
                source="workday",
                ats_provider="workday",
                ats_job_id="S1",
                description="FULL " + ("body " * 80),
                description_complete=True,
                description_fetched_at=_now(),
                location_raw="Toronto, ON",
            )
            jid, _ = db.upsert_job(full)
            db._conn.execute(
                "UPDATE jobs SET enrichment_status = 'stale' WHERE id = ?",
                (jid,),
            )
            db._conn.commit()
            rows = db.claim_enrichment_jobs(limit=1, worker_id="w", lease_s=30)
            token = rows[0]["enrich_lease_token"]
            self.assertTrue(
                db.complete_enrichment(
                    jid,
                    ok=False,
                    error="network timeout",
                    worker_id="w",
                    lease_token=token,
                    retry_backoff_s=3600,
                )
            )
            row = db.get_job(jid)
            assert row is not None
            self.assertEqual(row["enrichment_status"], "failed")
            self.assertIn("FULL", row["description"])
            self.assertEqual(row["description_complete"], 1)
            self.assertIsNotNone(row["enrich_next_retry_at"])
            # Immediate reclaim blocked by next_retry_at
            again = db.claim_enrichment_jobs(limit=5, worker_id="w2", lease_s=30)
            self.assertEqual(again, [])
            # Successful retry after backoff window
            past = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            db._conn.execute(
                "UPDATE jobs SET enrich_next_retry_at = ? WHERE id = ?",
                (past, jid),
            )
            db._conn.commit()
            retry = db.claim_enrichment_jobs(limit=1, worker_id="w3", lease_s=30)
            self.assertEqual(len(retry), 1)
            self.assertTrue(
                db.complete_enrichment(
                    jid,
                    ok=True,
                    worker_id="w3",
                    lease_token=retry[0]["enrich_lease_token"],
                )
            )
            db.close()

    def test_worker_crash_expired_lease_recoverable(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            jid, _ = db.upsert_job(_stub("RBC", "Data Engineer", jid="C1"))
            claimed = db.claim_enrichment_jobs(limit=1, worker_id="crash", lease_s=60)
            self.assertEqual(len(claimed), 1)
            db._conn.execute(
                "UPDATE jobs SET enrich_lease_until = ? WHERE id = ?",
                ("2000-01-01T00:00:00Z", jid),
            )
            db._conn.commit()
            recovered = db.claim_enrichment_jobs(limit=1, worker_id="rescue", lease_s=60)
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["id"], jid)
            db.close()


class RelevanceVsEligibilityTests(unittest.TestCase):
    def test_off_track_is_irrelevant_not_uncertain_geo(self):
        result = apply_hard_filters(
            {
                "title": "Customer Service Representative",
                "location_raw": "Toronto, ON",
                "description": "Help clients in branch.",
            },
            SEARCH,
            PROFILE,
        )
        self.assertEqual(result.relevance, "NO_MATCH")
        self.assertEqual(result.eligibility, "IRRELEVANT")
        self.assertFalse(result.title_match)

    def test_counts_separate_irrelevant_from_relevant_uncertain(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            j1, _ = db.upsert_job(
                RawJob(
                    company="RBC",
                    title="Teller",
                    url="https://example.com/1",
                    source="greenhouse",
                    description="branch",
                    location_raw="Toronto",
                    description_complete=True,
                    description_fetched_at=_now(),
                )
            )
            j2, _ = db.upsert_job(
                RawJob(
                    company="TD",
                    title="Senior Data Engineer",
                    url="https://example.com/2",
                    source="greenhouse",
                    description="Remote role. Location TBD.",
                    location_raw="Remote",
                    description_complete=True,
                    description_fetched_at=_now(),
                )
            )
            hf1 = apply_hard_filters(
                db.get_job(j1), SEARCH, PROFILE  # type: ignore[arg-type]
            ).to_dict()
            hf2 = apply_hard_filters(
                db.get_job(j2), SEARCH, PROFILE  # type: ignore[arg-type]
            ).to_dict()
            for jid, hf, score in ((j1, hf1, 10.0), (j2, hf2, 70.0)):
                row = db.get_job(jid)
                assert row is not None
                db.save_score(
                    jid,
                    overall=score,
                    scores={},
                    hard_filter=hf,
                    strengths=[],
                    gaps=[],
                    salary_alignment="ok",
                    rejection_reasons=[],
                    evidence=[],
                    model="test",
                    description_hash=row["description_hash"],
                    score_kind="deterministic",
                    config_fingerprint="x",
                )
            counts = db.count_scored_by_eligibility(score_kind="deterministic")
            self.assertGreaterEqual(counts["irrelevant"], 1)
            self.assertGreaterEqual(counts["relevant_uncertain"], 1)
            self.assertEqual(counts.get("IRRELEVANT", 0), 1)
            uncertain = db.list_jobs(limit=10, eligibility="UNCERTAIN")
            titles = [r["title"] for r in uncertain]
            self.assertIn("Senior Data Engineer", titles)
            self.assertNotIn("Teller", titles)
            db.close()


class PriorityFingerprintTests(unittest.TestCase):
    def test_profile_change_recalculates(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            db.upsert_job(_stub("TD", "Data Engineer", jid="P1"))
            a = prioritize_enrichment(db, search=SEARCH, profile=PROFILE, force=True)
            self.assertGreater(a["updated"], 0)
            b = prioritize_enrichment(db, search=SEARCH, profile=PROFILE, force=False)
            self.assertEqual(b.get("skipped"), "fingerprint_unchanged")
            profile2 = {
                **PROFILE,
                "skills": {"primary": ["Rust", "Go"]},
            }
            c = prioritize_enrichment(db, search=SEARCH, profile=profile2, force=False)
            self.assertGreater(c["updated"], 0)
            db.close()


class LeaseWriteSafetyTests(unittest.TestCase):
    def test_stale_worker_cannot_overwrite_newer_enrichment(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            jid, _ = db.upsert_job(_stub("TD", "Data Engineer", jid="LW1"))
            first = db.claim_enrichment_jobs(limit=1, worker_id="old", lease_s=60)
            token_old = first[0]["enrich_lease_token"]
            db._conn.execute(
                "UPDATE jobs SET enrich_lease_until = ? WHERE id = ?",
                ("2000-01-01T00:00:00Z", jid),
            )
            db._conn.commit()
            second = db.claim_enrichment_jobs(limit=1, worker_id="new", lease_s=60)
            token_new = second[0]["enrich_lease_token"]
            body_b = RawJob(
                company="TD",
                title="Data Engineer",
                url="https://td.example/job/LW1",
                source="workday",
                ats_provider="workday",
                ats_job_id="LW1",
                location_raw="Toronto, ON Remote Canada",
                description="WORKER B BODY " + ("x" * 400),
                description_complete=True,
                description_fetched_at=_now(),
            )
            self.assertTrue(
                db.apply_leased_enrichment(
                    jid, worker_id="new", lease_token=token_new, enriched=body_b
                )
            )
            body_a = RawJob(
                company="TD",
                title="Data Engineer",
                url="https://td.example/job/LW1",
                source="workday",
                ats_provider="workday",
                ats_job_id="LW1",
                location_raw="Toronto, ON",
                description="WORKER A STALE " + ("y" * 400),
                description_complete=True,
                description_fetched_at=_now(),
            )
            self.assertFalse(
                db.apply_leased_enrichment(
                    jid, worker_id="old", lease_token=token_old, enriched=body_a
                )
            )
            row = db.get_job(jid)
            assert row is not None
            self.assertIn("WORKER B BODY", row["description"])
            self.assertNotIn("WORKER A STALE", row["description"])
            self.assertEqual(row["enrichment_status"], "complete")
            db.close()


class MinPriorityClaimTests(unittest.TestCase):
    def test_quick_threshold_skips_off_track_padding(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            for i in range(40):
                db.upsert_job(_stub("RBC", f"Personal Banker {i}", jid=f"N{i}"))
            for i in range(5):
                db.upsert_job(
                    _stub(
                        "TD",
                        f"Data Engineer - Pipelines {i}",
                        jid=f"E{i}",
                        location="Remote - Canada",
                    )
                )
            prioritize_enrichment(db, search=SEARCH, profile=PROFILE, force=True)
            claimed = db.claim_enrichment_jobs(
                limit=50, worker_id="w", lease_s=60, min_priority=500, max_per_company=12
            )
            self.assertEqual(len(claimed), 5)
            self.assertTrue(all("Data Engineer" in (r["title"] or "") for r in claimed))
            self.assertFalse(any("Banker" in (r["title"] or "") for r in claimed))
            db.close()


if __name__ == "__main__":
    unittest.main()
