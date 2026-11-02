"""Confirmed shortlist requires hard-filter PASS, not geo ELIGIBLE alone."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from jobseek.db.store import Database
from jobseek.filters.hard import apply_hard_filters
from jobseek.models import RawJob
from jobseek.rank.scorer import score_deterministic
from jobseek.shortlist import is_confirmed_match


SEARCH = {
    "tracks": ["data_engineering", "analytics_engineering"],
    "track_aliases": {
        "data_engineering": [
            "Data Engineer",
            "Senior Data Engineer",
            "Staff Data Engineer",
        ],
        "analytics_engineering": ["Analytics Engineer"],
    },
    "seniority": {"include": ["senior", "staff", "mid"], "exclude": ["intern", "junior"]},
    "location": {
        "modes": ["remote_canada", "hybrid", "remote_province"],
        "cities": ["Toronto"],
        "provinces": ["Ontario", "ON"],
        "preferred": ["Remote - Canada", "Canada remote"],
        "allow_us_employer_remote_with_canada_evidence": True,
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
    },
    "salary": {"floors": {"CAD": 130000, "USD": 95000}, "reject_missing": False},
}

PROFILE = {
    "skills": {"primary": ["Python", "SQL", "Databricks", "Spark"]},
    "experience": {"years": 7},
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _score_and_save(db: Database, job: RawJob, search=SEARCH, profile=PROFILE):
    jid, _ = db.upsert_job(job)
    row = db.get_job(jid)
    assert row is not None
    scored = score_deterministic(row, search_cfg=search, profile=profile)
    db.save_score(
        jid,
        overall=scored.overall,
        scores=scored.scores,
        hard_filter=scored.hard_filter.to_dict() if scored.hard_filter else None,
        strengths=scored.strengths,
        gaps=scored.gaps,
        salary_alignment=scored.salary_alignment,
        rejection_reasons=scored.rejection_reasons,
        evidence=scored.evidence,
        model=scored.model,
        description_hash=row["description_hash"],
        score_kind="deterministic",
        config_fingerprint="test",
    )
    db._conn.execute("UPDATE jobs SET status = 'ranked' WHERE id = ?", (jid,))
    db._conn.commit()
    return jid, scored


class ManulifeSalaryRegressionTests(unittest.TestCase):
    def test_cad_113k_excluded_when_floor_130k(self):
        hard = apply_hard_filters(
            {
                "title": "Senior Data Engineer",
                "company": "Manulife",
                "location_raw": "Remote - Canada",
                "description": "Remote Canada. Base salary CAD $113,000.",
                "salary_min": 113000,
                "salary_max": 113000,
                "salary_currency": "CAD",
                "url": "https://manulife.example/job/1",
            },
            SEARCH,
            PROFILE,
        )
        self.assertEqual(hard.eligibility, "ELIGIBLE")
        self.assertEqual(hard.salary_verdict, "FAIL")
        self.assertEqual(hard.verdict, "FAIL")
        self.assertFalse(
            is_confirmed_match(
                {
                    "description_complete": 1,
                    "overall": 0,
                    "score_kind": "deterministic",
                    "hard_filter_json": hard.to_dict(),
                }
            )
        )

    def test_jobs_shortlist_excludes_manulife_below_floor(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            _score_and_save(
                db,
                RawJob(
                    company="Manulife",
                    title="Senior Data Engineer",
                    url="https://manulife.example/sde",
                    source="workday",
                    description=(
                        "Senior Data Engineer. Remote Canada. "
                        "Python SQL Databricks Spark. Base salary CAD 113000."
                    ),
                    location_raw="Remote - Canada",
                    salary_min=113000,
                    salary_max=113000,
                    salary_currency="CAD",
                    description_complete=True,
                    description_fetched_at=_now(),
                ),
            )
            _score_and_save(
                db,
                RawJob(
                    company="TD",
                    title="Senior Data Engineer",
                    url="https://td.example/sde",
                    source="greenhouse",
                    description=(
                        "Senior Data Engineer. Remote Canada. "
                        "Python SQL Databricks Spark. Base salary CAD 145000."
                    ),
                    location_raw="Remote - Canada",
                    salary_min=145000,
                    salary_max=160000,
                    salary_currency="CAD",
                    description_complete=True,
                    description_fetched_at=_now(),
                ),
            )
            confirmed = db.list_jobs(limit=20, eligibility="ELIGIBLE", confirmed_only=True)
            companies = {r["company"] for r in confirmed}
            self.assertNotIn("Manulife", companies)
            self.assertIn("TD", companies)
            counts = db.count_scored_by_eligibility()
            self.assertEqual(counts["confirmed"], 1)
            self.assertGreaterEqual(counts["geo_eligible_hard_fail"], 1)
            digestish = db.top_new_scored(limit=10, min_score=0, eligibility="ELIGIBLE")
            self.assertEqual([r["company"] for r in digestish], ["TD"])
            db.close()

    def test_usd_below_floor_excluded_with_normalization(self):
        hard = apply_hard_filters(
            {
                "title": "Data Engineer",
                "location_raw": "Remote - Canada",
                "description": "Remote Canada. Salary USD $80,000.",
                "salary_min": 80000,
                "salary_max": 80000,
                "salary_currency": "USD",
            },
            SEARCH,
            PROFILE,
        )
        self.assertEqual(hard.salary_verdict, "FAIL")
        self.assertEqual(hard.verdict, "FAIL")

    def test_missing_salary_not_auto_rejected(self):
        hard = apply_hard_filters(
            {
                "title": "Analytics Engineer",
                "location_raw": "Remote - Canada",
                "description": "Remote Canada. Python SQL. Compensation competitive.",
            },
            SEARCH,
            PROFILE,
        )
        self.assertEqual(hard.salary_verdict, "PASS")
        self.assertNotEqual(hard.verdict, "FAIL")

    def test_stale_score_replaced_after_salary_fail_rescore(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            job = RawJob(
                company="Manulife",
                title="Senior Data Engineer",
                url="https://manulife.example/stale",
                source="greenhouse",
                description="Remote Canada. Python SQL. Competitive pay.",
                location_raw="Remote - Canada",
                description_complete=True,
                description_fetched_at=_now(),
            )
            jid, scored = _score_and_save(db, job)
            self.assertEqual(scored.hard_filter.verdict, "PASS")
            self.assertEqual(len(db.list_jobs(eligibility="ELIGIBLE")), 1)

            # Same description hash but updated structured salary → rescore FAIL.
            row = db.get_job(jid)
            assert row is not None
            row = dict(row)
            row["salary_min"] = 113000
            row["salary_max"] = 113000
            row["salary_currency"] = "CAD"
            scored2 = score_deterministic(row, search_cfg=SEARCH, profile=PROFILE)
            assert scored2.hard_filter is not None
            self.assertEqual(scored2.hard_filter.verdict, "FAIL")
            db.save_score(
                jid,
                overall=scored2.overall,
                scores=scored2.scores,
                hard_filter=scored2.hard_filter.to_dict() if scored2.hard_filter else None,
                strengths=[],
                gaps=[],
                salary_alignment=scored2.salary_alignment,
                rejection_reasons=scored2.rejection_reasons,
                evidence=scored2.evidence,
                model=scored2.model,
                description_hash=row["description_hash"],
                score_kind="deterministic",
                config_fingerprint="test",
            )
            self.assertEqual(db.list_jobs(eligibility="ELIGIBLE", confirmed_only=True), [])
            db.close()


if __name__ == "__main__":
    unittest.main()
