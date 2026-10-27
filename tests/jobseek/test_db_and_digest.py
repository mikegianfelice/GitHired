"""SQLite persistence, dedup, removed_at, digest selection."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jobseek.db.store import Database
from jobseek.digest.build import build_digest, render_digest_markdown
from jobseek.identity import JobIdentity, canonical_url
from jobseek.models import RawJob
from jobseek.rank.scorer import score_job


SEARCH = {
    "target_titles": ["AI Engineer", "Senior AI Engineer"],
    "title_aliases": [],
    "location": {
        "preferred": ["Canada remote"],
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
        "allow_us_employer_remote_with_canada_evidence": True,
    },
    "salary": {"reject_missing": False, "floors": {"CAD": 100000}},
    "digest": {"top_n": 10, "min_score": 50},
}

PROFILE = {
    "identity": {"work_authorization": "Canada", "languages": [{"name": "English", "level": "native"}]},
    "skills": {"primary": ["Python"], "secondary": [], "domain": ["AI"]},
    "experience": {},
    "behavioral": {},
    "career_goals": [],
    "deal_breakers": [],
}


class IdentityTests(unittest.TestCase):
    def test_canonical_url_strips_utm(self):
        url = "https://Example.com/jobs/1/?utm_source=x&gh_src=y"
        self.assertEqual(canonical_url(url), "https://example.com/jobs/1")

    def test_identity_key(self):
        ident = JobIdentity.from_fields(
            company="Acme Corp",
            title="AI Engineer",
            url="https://boards.greenhouse.io/acme/jobs/1",
            ats_provider="greenhouse",
            ats_job_id="1",
        )
        self.assertTrue(ident.canonical_key)
        self.assertEqual(ident.ats_provider, "greenhouse")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_upsert_dedup_by_ats_id(self):
        job = RawJob(
            company="Acme",
            title="AI Engineer",
            url="https://boards.greenhouse.io/acme/jobs/1",
            source="greenhouse",
            ats_provider="greenhouse",
            ats_job_id="1",
            location_raw="Remote - Canada",
            description="Remote in Canada. Python.",
        )
        id1, new1 = self.db.upsert_job(job)
        job2 = RawJob(
            company="Acme",
            title="AI Engineer (Updated)",
            url="https://boards.greenhouse.io/acme/jobs/1?utm_source=x",
            source="greenhouse",
            ats_provider="greenhouse",
            ats_job_id="1",
            description="Remote in Canada. Python LLM.",
        )
        id2, new2 = self.db.upsert_job(job2)
        self.assertEqual(id1, id2)
        self.assertTrue(new1)
        self.assertFalse(new2)

    def test_mark_removed(self):
        a = RawJob(
            company="Acme",
            title="AI Engineer",
            url="https://example.com/a",
            source="greenhouse",
            ats_provider="greenhouse",
            ats_job_id="a",
            description="Canada remote",
        )
        b = RawJob(
            company="Acme",
            title="Senior AI Engineer",
            url="https://example.com/b",
            source="greenhouse",
            ats_provider="greenhouse",
            ats_job_id="b",
            description="Canada remote",
        )
        id_a, _ = self.db.upsert_job(a)
        id_b, _ = self.db.upsert_job(b)
        n = self.db.mark_missing_removed(
            source_prefix="greenhouse",
            seen_ids={id_a},
            companies={"Acme"},
        )
        self.assertEqual(n, 1)
        gone = self.db.get_job(id_b)
        self.assertIsNotNone(gone["removed_at"])

    def test_tracker_skip_and_digest(self):
        job = RawJob(
            company="Acme",
            title="AI Engineer",
            url="https://example.com/c",
            source="greenhouse",
            location_raw="Remote Canada",
            description="Remote in Canada. Python LLM engineer role.",
        )
        job_id, _ = self.db.upsert_job(job)
        row = self.db.get_job(job_id)
        scored = score_job(row, search_cfg=SEARCH, profile=PROFILE)
        self.db.save_score(
            job_id,
            overall=max(scored.overall, 70),
            scores=scored.scores,
            hard_filter=scored.hard_filter.to_dict() if scored.hard_filter else None,
            strengths=scored.strengths or ["fit"],
            gaps=scored.gaps,
            salary_alignment=scored.salary_alignment,
            rejection_reasons=[],
            evidence=scored.evidence,
            model=scored.model,
            description_hash=row["description_hash"],
        )
        # Force overall high enough for digest
        self.db.save_score(
            job_id,
            overall=80,
            scores={"technical": 80, "experience": 80, "behavioral": 80, "career": 80},
            hard_filter={"verdict": "PASS"},
            strengths=["strong"],
            gaps=[],
            salary_alignment="ok",
            rejection_reasons=[],
            evidence=[],
            model="test",
            description_hash=row["description_hash"],
        )
        digest = build_digest(self.db, since=None)
        self.assertGreaterEqual(digest["count"], 1)
        md = render_digest_markdown(digest)
        self.assertIn("AI Engineer", md)

        self.db.sync_application("Acme", "AI Engineer", "applied")
        self.assertTrue(self.db.should_skip_recommendation("Acme", "AI Engineer"))
        digest2 = build_digest(self.db, since=None)
        self.assertEqual(digest2["count"], 0)


class RankHeuristicTests(unittest.TestCase):
    def test_hard_fail_short_circuits(self):
        job = {
            "title": "AI Engineer",
            "location_raw": "US Remote",
            "description": "Must be located in the United States only.",
            "company": "X",
            "url": "https://example.com/x",
        }
        scored = score_job(job, search_cfg=SEARCH, profile=PROFILE)
        self.assertEqual(scored.model, "hard_filter")
        self.assertEqual(scored.overall, 0)
        self.assertTrue(scored.rejection_reasons)


if __name__ == "__main__":
    unittest.main()
