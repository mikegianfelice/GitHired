"""Performance optimization: Workday cache, budgets, description preservation, fingerprints."""

from __future__ import annotations

import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from jobseek.adapters.workday import (
    WorkdayAdapter,
    description_cache_fresh,
    normalize_workday_job,
)
from jobseek.db.store import Database
from jobseek.http_client import HttpResponse
from jobseek.models import RawJob
from jobseek.rank.fingerprint import scoring_fingerprint


COMPANY = {
    "name": "Intact",
    "ats": "workday",
    "board_token": "intactfc.wd3.myworkdayjobs.com/intactfc/intactfc",
}


class _FakeClient:
    def __init__(self, post_pages: list, details: dict[str, object], *, get_delay: float = 0.0):
        self.post_pages = list(post_pages)
        self.details = details
        self.get_delay = get_delay
        self.get_calls: list[str] = []
        self.post_calls: list[str] = []

    def post(self, url, *, json_body=None, headers=None):
        self.post_calls.append(url)
        if not self.post_pages:
            return HttpResponse(200, json.dumps({"total": 0, "jobPostings": []}), url)
        payload = self.post_pages.pop(0)
        return HttpResponse(200, json.dumps(payload), url)

    def get(self, url, *, params=None, headers=None):
        self.get_calls.append(url)
        if self.get_delay:
            time.sleep(self.get_delay)
        body = None
        for key, val in self.details.items():
            if key in url or url.endswith(key):
                body = val
                break
        if body is None:
            return HttpResponse(404, "{}", url)
        return HttpResponse(200, json.dumps(body), url)


def _listings(n: int = 6) -> list[dict]:
    out = []
    for i in range(n):
        out.append(
            {
                "title": f"Engineer {i}",
                "externalPath": f"/job/Toronto-ON/Role-{i}_R{i}",
                "locationsText": "Toronto, ON",
                "postedOn": "Posted Today",
                "bulletFields": [f"R{i}"],
            }
        )
    return out


def _details(n: int = 6) -> dict[str, object]:
    host = "intactfc.wd3.myworkdayjobs.com"
    out: dict[str, object] = {}
    for i in range(n):
        out[f"https://{host}/wday/cxs/intactfc/intactfc/job/Role-{i}_R{i}"] = {
            "jobPostingInfo": {
                "id": f"R{i}",
                "jobReqId": f"R{i}",
                "title": f"Engineer {i}",
                "jobDescription": f"Full description {i} " + ("x" * 200),
                "location": "Toronto, ON",
            }
        }
    return out


class DescriptionPreserveTests(unittest.TestCase):
    def test_upsert_does_not_downgrade_complete_description(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            full = RawJob(
                company="Acme",
                title="Engineer",
                url="https://example.com/1",
                source="workday",
                ats_provider="workday",
                ats_job_id="R1",
                description="COMPLETE BODY " + ("y" * 500),
                description_complete=True,
                description_fetched_at="2026-10-30T00:00:00Z",
            )
            jid, is_new = db.upsert_job(full)
            self.assertTrue(is_new)
            stub = RawJob(
                company="Acme",
                title="Engineer",
                url="https://example.com/1",
                source="workday",
                ats_provider="workday",
                ats_job_id="R1",
                description=None,
                description_complete=False,
            )
            db.upsert_job(stub)
            row = db.get_job(jid)
            assert row is not None
            self.assertIn("COMPLETE BODY", row["description"])
            self.assertEqual(row["description_complete"], 1)
            db.close()


class CacheFreshnessTests(unittest.TestCase):
    def test_ttl_fresh_and_stale(self):
        now = datetime.now(timezone.utc)
        fresh = {
            "description": "abc",
            "description_complete": 1,
            "description_fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        stale = {
            "description": "abc",
            "description_complete": 1,
            "description_fetched_at": (now - timedelta(days=10)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
        self.assertTrue(description_cache_fresh(fresh, ttl_s=7 * 86400))
        self.assertFalse(description_cache_fresh(stale, ttl_s=7 * 86400))
        self.assertFalse(description_cache_fresh({"description_complete": 0}, ttl_s=7 * 86400))


class WorkdayBudgetSeparationTests(unittest.TestCase):
    def test_list_budget_preserves_partial_and_marks_incomplete(self):
        # Slow list pages: each post sleeps via client — use tiny list budget.
        class SlowList(_FakeClient):
            def post(self, url, *, json_body=None, headers=None):
                time.sleep(0.08)
                return super().post(url, json_body=json_body, headers=headers)

        pages = []
        listings = _listings(60)
        # 3 pages of 20 — budget stops mid-pagination
        pages.append({"total": 60, "jobPostings": listings[:20]})
        pages.append({"total": 60, "jobPostings": listings[20:40]})
        pages.append({"total": 60, "jobPostings": listings[40:]})
        client = SlowList(pages, _details(60))
        adapter = WorkdayAdapter(
            client,  # type: ignore[arg-type]
            list_budget_s=0.12,
            detail_budget_s=0.01,
            fetch_details=False,
            complete=False,
        )
        result = adapter.fetch_company(COMPANY)
        self.assertFalse(result.listing_complete)
        self.assertGreater(len(result.jobs), 0)
        self.assertTrue(any("pagination budget" in e for e in result.errors))

    def test_cache_skips_detail_http(self):
        n = 5
        page = [{"total": n, "jobPostings": _listings(n)}]
        client = _FakeClient(page, _details(n))
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cache = {
            f"R{i}": {
                "description": f"Cached body {i}",
                "description_complete": 1,
                "description_fetched_at": now,
                "location_raw": "Toronto, ON",
            }
            for i in range(n)
        }
        adapter = WorkdayAdapter(
            client,  # type: ignore[arg-type]
            description_cache=cache,
            force_refresh=False,
            description_ttl_s=7 * 86400,
            detail_budget_s=30,
            list_budget_s=30,
        )
        result = adapter.fetch_company(COMPANY)
        self.assertEqual(len(result.jobs), n)
        self.assertEqual(len(client.get_calls), 0)
        self.assertEqual(result.details_cached, n)
        self.assertTrue(all(j.description_complete for j in result.jobs))
        self.assertTrue(all((j.description or "").startswith("Cached") for j in result.jobs))

    def test_force_refresh_fetches_details(self):
        n = 3
        page = [{"total": n, "jobPostings": _listings(n)}]
        client = _FakeClient(page, _details(n))
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cache = {
            f"R{i}": {
                "description": f"Cached body {i}",
                "description_complete": 1,
                "description_fetched_at": now,
            }
            for i in range(n)
        }
        adapter = WorkdayAdapter(
            client,  # type: ignore[arg-type]
            description_cache=cache,
            force_refresh=True,
            detail_budget_s=30,
        )
        result = adapter.fetch_company(COMPANY)
        self.assertEqual(len(client.get_calls), n)
        self.assertEqual(result.details_fetched, n)
        self.assertTrue(all("Full description" in (j.description or "") for j in result.jobs))


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_changes_with_salary_floor(self):
        base = {
            "tracks": ["data_engineering"],
            "seniority": {"include": ["senior"]},
            "location": {"modes": ["remote_canada"], "cities": ["Toronto"]},
            "salary": {"floors": {"CAD": 120000}},
        }
        profile = {"skills": {"primary": ["Python"]}}
        a = scoring_fingerprint(base, profile)
        b = scoring_fingerprint(
            {**base, "salary": {"floors": {"CAD": 150000}}}, profile
        )
        self.assertNotEqual(a, b)

    def test_jobs_needing_score_respects_fingerprint(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            job = RawJob(
                company="Acme",
                title="Data Engineer",
                url="https://example.com/j",
                source="greenhouse",
                description="Remote Canada Python SQL",
                description_complete=True,
            )
            jid, _ = db.upsert_job(job)
            row = db.get_job(jid)
            assert row is not None
            db.save_score(
                jid,
                overall=80,
                scores={"x": 1},
                hard_filter={"eligibility": "ELIGIBLE"},
                strengths=[],
                gaps=[],
                salary_alignment="ok",
                rejection_reasons=[],
                evidence=[],
                model="deterministic/v9",
                description_hash=row["description_hash"],
                score_kind="deterministic",
                config_fingerprint="aaaa",
            )
            need = db.jobs_needing_score(
                limit=10,
                current_model=["deterministic/v9"],
                config_fingerprint="bbbb",
            )
            self.assertEqual(len(need), 1)
            reuse = db.jobs_needing_score(
                limit=10,
                current_model=["deterministic/v9"],
                config_fingerprint="aaaa",
            )
            self.assertEqual(len(reuse), 0)
            db.close()


class NormalizeCompleteFlagTests(unittest.TestCase):
    def test_detail_sets_complete(self):
        listing = _listings(1)[0]
        detail = _details(1)[
            "https://intactfc.wd3.myworkdayjobs.com/wday/cxs/intactfc/intactfc/job/Role-0_R0"
        ]
        job = normalize_workday_job(
            company_name="Intact",
            host="intactfc.wd3.myworkdayjobs.com",
            site="intactfc",
            listing=listing,
            detail=detail,  # type: ignore[arg-type]
        )
        assert job is not None
        self.assertTrue(job.description_complete)
        list_only = normalize_workday_job(
            company_name="Intact",
            host="intactfc.wd3.myworkdayjobs.com",
            site="intactfc",
            listing=listing,
            detail=None,
        )
        assert list_only is not None
        self.assertFalse(list_only.description_complete)


if __name__ == "__main__":
    unittest.main()
