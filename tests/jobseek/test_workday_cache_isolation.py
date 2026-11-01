"""Regression: Workday per-company cache isolation + geo-aware cache reuse."""

from __future__ import annotations

import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from jobseek.adapters.workday import (
    WorkdayAdapter,
    cached_location_usable,
    list_location_contradicts_cache,
    list_location_needs_detail,
    lookup_description_cache,
)
from jobseek.db.store import Database
from jobseek.http_client import HttpResponse
from jobseek.models import RawJob
from jobseek.rank.fingerprint import scoring_fingerprint
from jobseek.rank.scorer import STAGE1_MODELS


class _FakeClient:
    def __init__(self, post_pages: list, details: dict[str, object]):
        self.post_pages = list(post_pages)
        self.details = details
        self.get_calls: list[str] = []
        self.post_calls: list[str] = []
        self._lock = threading.Lock()

    def post(self, url, *, json_body=None, headers=None):
        with self._lock:
            self.post_calls.append(url)
            if not self.post_pages:
                return HttpResponse(200, json.dumps({"total": 0, "jobPostings": []}), url)
            payload = self.post_pages.pop(0)
        return HttpResponse(200, json.dumps(payload), url)

    def get(self, url, *, params=None, headers=None):
        with self._lock:
            self.get_calls.append(url)
        body = None
        for key, val in self.details.items():
            if key in url or url.endswith(key):
                body = val
                break
        if body is None:
            return HttpResponse(404, "{}", url)
        return HttpResponse(200, json.dumps(body), url)


BANKS = [
    "BMO",
    "RBC",
    "TD",
    "CIBC",
    "Manulife",
    "Intact",
    "Sun Life",
    "TELUS",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _company(name: str) -> dict:
    slug = name.lower().replace(" ", "")
    return {
        "name": name,
        "ats": "workday",
        "board_token": f"{slug}.wd3.myworkdayjobs.com/{slug}/{slug}",
    }


class GeoHelpersTests(unittest.TestCase):
    def test_stub_vs_usable_location(self):
        self.assertTrue(list_location_needs_detail("5 Locations"))
        self.assertTrue(list_location_needs_detail(""))
        self.assertFalse(list_location_needs_detail("Toronto, ON"))
        self.assertTrue(
            cached_location_usable({"location_raw": "Toronto, ON / Calgary, AB"})
        )
        self.assertFalse(cached_location_usable({"location_raw": "3 Locations"}))

    def test_list_contradicts_cache(self):
        cached = {"location_raw": "Calgary, AB"}
        listing = {"locationsText": "Toronto, ON"}
        self.assertTrue(list_location_contradicts_cache(listing, cached))
        self.assertFalse(
            list_location_contradicts_cache(
                {"locationsText": "5 Locations"}, cached
            )
        )
        self.assertFalse(
            list_location_contradicts_cache(
                {"locationsText": "Toronto, Ontario, Canada"},
                {"location_raw": "Toronto, ON"},
            )
        )


class CacheIsolationTests(unittest.TestCase):
    def test_concurrent_companies_cannot_swap_caches(self):
        """BMO…TELUS each see only their own cached description under concurrency."""

        def _run_one(name: str) -> tuple[str, str, int]:
            listing = {
                "title": f"{name} Engineer",
                "externalPath": f"/job/Toronto-ON/{name}-Role_R1",
                "locationsText": "Toronto, ON",
                "postedOn": "Posted Today",
                "bulletFields": ["R1"],
            }
            host = f"{name.lower().replace(' ', '')}.wd3.myworkdayjobs.com"
            site = name.lower().replace(" ", "")
            detail_url = f"https://{host}/wday/cxs/{site}/{site}/job/{name}-Role_R1"
            # Wrong body if this company somehow fetches (should not).
            details = {
                detail_url: {
                    "jobPostingInfo": {
                        "id": "R1",
                        "jobReqId": "R1",
                        "title": f"{name} Engineer",
                        "jobDescription": f"WRONG FETCHED BODY FOR {name}",
                        "location": "Toronto, ON",
                    }
                }
            }
            client = _FakeClient(
                [{"total": 1, "jobPostings": [listing]}],
                details,
            )
            cache = {
                "R1": {
                    "description": f"CACHED ONLY FOR {name}",
                    "description_complete": 1,
                    "description_fetched_at": _now(),
                    "location_raw": "Toronto, ON",
                }
            }
            # Shared template deliberately polluted like the old bug.
            shared = WorkdayAdapter(
                client,  # type: ignore[arg-type]
                description_cache={"R1": {"description": "POISON", "description_complete": 1}},
                list_budget_s=30,
                detail_budget_s=30,
            )
            # Concurrent workers each call set_description_cache (old bug) AND
            # the new request-scoped path — request-scoped must win.
            adapter = shared.clone(client=client, description_cache=cache)
            # Simulate race: another thread overwrites shared adapter cache mid-flight.
            def _poison():
                time.sleep(0.01)
                shared.set_description_cache(
                    {
                        "R1": {
                            "description": f"LEAKED FROM OTHER BANK into {name}",
                            "description_complete": 1,
                            "description_fetched_at": _now(),
                            "location_raw": "Toronto, ON",
                        }
                    }
                )

            t = threading.Thread(target=_poison)
            t.start()
            result = adapter.fetch_company(_company(name), description_cache=cache)
            t.join()
            self.assertEqual(len(result.jobs), 1)
            desc = result.jobs[0].description or ""
            return name, desc, len(client.get_calls)

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(_run_one, name) for name in BANKS]
            for fut in as_completed(futs):
                name, desc, gets = fut.result()
                self.assertIn(f"CACHED ONLY FOR {name}", desc)
                self.assertNotIn("LEAKED", desc)
                self.assertNotIn("POISON", desc)
                self.assertNotIn("WRONG FETCHED", desc)
                self.assertEqual(gets, 0, msg=f"{name} should reuse cache")

    def test_multi_key_lookup_by_path_id(self):
        cache = {
            "Senior-Engineer_R99": {
                "description": "via path",
                "description_complete": 1,
                "description_fetched_at": _now(),
                "location_raw": "Ottawa, ON",
            }
        }
        listing = {
            "externalPath": "/job/Ottawa/Senior-Engineer_R99",
            "locationsText": "Ottawa, ON",
            "bulletFields": [],
        }
        hit = lookup_description_cache(
            cache, listing=listing, path_id="Senior-Engineer_R99"
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["description"], "via path")


class ParallelPaginationTests(unittest.TestCase):
    def test_parallel_offsets_dedupe_and_complete(self):
        total = 80
        page = 20

        class _Pages:
            def __init__(self) -> None:
                self.lock = threading.Lock()
                self.calls: list[int] = []

            def post(self, url, *, json_body=None, headers=None):
                off = int((json_body or {}).get("offset") or 0)
                with self.lock:
                    self.calls.append(off)
                batch = [
                    {
                        "title": f"J{i}",
                        "externalPath": f"/job/x/Role_{i}",
                        "locationsText": "Toronto, ON",
                        "bulletFields": [f"R{i}"],
                    }
                    for i in range(off, min(off + page, total))
                ]
                return HttpResponse(
                    200, json.dumps({"total": total, "jobPostings": batch}), url
                )

            def get(self, *a, **k):
                return HttpResponse(404, "{}", "")

        client = _Pages()
        adapter = WorkdayAdapter(
            client,  # type: ignore[arg-type]
            fetch_details=False,
            list_page_concurrency=3,
            list_budget_s=60,
            detail_budget_s=1,
        )
        result = adapter.fetch_company(_company("RBC"))
        self.assertTrue(result.listing_complete)
        self.assertEqual(len(result.jobs), total)
        self.assertEqual(sorted(client.calls), [0, 20, 40, 60])

    def test_incomplete_cache_skipped_unless_force_refresh(self):
        listing = {
            "title": "Eng",
            "externalPath": "/job/x/Role_R1",
            "locationsText": "Toronto, ON",
            "bulletFields": ["R1"],
        }
        host = "bmo.wd3.myworkdayjobs.com"
        details = {
            f"https://{host}/wday/cxs/bmo/bmo/job/Role_R1": {
                "jobPostingInfo": {
                    "id": "R1",
                    "jobReqId": "R1",
                    "title": "Eng",
                    "jobDescription": "Should only fetch when forced",
                    "location": "Toronto, ON",
                }
            }
        }
        cache = {
            "R1": {
                "description": "",
                "description_complete": 0,
                "description_fetched_at": _now(),
                "location_raw": "Toronto, ON",
            }
        }
        client = _FakeClient([{"total": 1, "jobPostings": [listing]}], details)
        adapter = WorkdayAdapter(
            client,  # type: ignore[arg-type]
            description_cache=cache,
            force_refresh=False,
            list_budget_s=30,
            detail_budget_s=30,
        )
        result = adapter.fetch_company(_company("BMO"), description_cache=cache)
        self.assertEqual(len(client.get_calls), 0)
        self.assertEqual(result.details_requested, 0)

        client2 = _FakeClient([{"total": 1, "jobPostings": [listing]}], details)
        adapter2 = WorkdayAdapter(
            client2,  # type: ignore[arg-type]
            description_cache=cache,
            force_refresh=True,
            list_budget_s=30,
            detail_budget_s=30,
        )
        result2 = adapter2.fetch_company(_company("BMO"), description_cache=cache)
        self.assertEqual(len(client2.get_calls), 1)
        self.assertEqual(result2.details_fetched, 1)


class GeoCacheReuseTests(unittest.TestCase):
    def test_fresh_cache_with_resolved_geo_skips_stub_list_rehydrate(self):
        listing = {
            "title": "Data Engineer",
            "externalPath": "/job/Multi/Role_R7",
            "locationsText": "5 Locations",
            "postedOn": "Posted Today",
            "bulletFields": ["R7"],
        }
        host = "intact.wd3.myworkdayjobs.com"
        details = {
            f"https://{host}/wday/cxs/intact/intact/job/Role_R7": {
                "jobPostingInfo": {
                    "id": "R7",
                    "jobReqId": "R7",
                    "title": "Data Engineer",
                    "jobDescription": "SHOULD NOT FETCH",
                    "location": "Vancouver, BC",
                    "additionalLocations": ["Toronto, ON"],
                }
            }
        }
        client = _FakeClient([{"total": 1, "jobPostings": [listing]}], details)
        cache = {
            "R7": {
                "description": "Cached multi-loc body",
                "description_complete": 1,
                "description_fetched_at": _now(),
                "location_raw": "Toronto, ON; Vancouver, BC",
            }
        }
        adapter = WorkdayAdapter(
            client,  # type: ignore[arg-type]
            description_cache=cache,
            list_budget_s=30,
            detail_budget_s=30,
        )
        result = adapter.fetch_company(_company("Intact"), description_cache=cache)
        self.assertEqual(len(client.get_calls), 0)
        self.assertEqual(result.details_cached, 1)
        self.assertEqual(result.details_fetched, 0)
        job = result.jobs[0]
        self.assertIn("Cached multi-loc", job.description or "")
        self.assertIn("Toronto", job.location_raw or "")

    def test_specific_list_geo_change_forces_refresh(self):
        listing = {
            "title": "Analyst",
            "externalPath": "/job/Toronto/Role_R8",
            "locationsText": "Toronto, ON",
            "postedOn": "Posted Today",
            "bulletFields": ["R8"],
        }
        host = "td.wd3.myworkdayjobs.com"
        details = {
            f"https://{host}/wday/cxs/td/td/job/Role_R8": {
                "jobPostingInfo": {
                    "id": "R8",
                    "jobReqId": "R8",
                    "title": "Analyst",
                    "jobDescription": "Updated Toronto posting body",
                    "location": "Toronto, ON",
                }
            }
        }
        client = _FakeClient([{"total": 1, "jobPostings": [listing]}], details)
        cache = {
            "R8": {
                "description": "Old Calgary body",
                "description_complete": 1,
                "description_fetched_at": _now(),
                "location_raw": "Calgary, AB",
            }
        }
        adapter = WorkdayAdapter(
            client,  # type: ignore[arg-type]
            description_cache=cache,
            list_budget_s=30,
            detail_budget_s=30,
        )
        result = adapter.fetch_company(_company("TD"), description_cache=cache)
        self.assertEqual(len(client.get_calls), 1)
        self.assertEqual(result.details_fetched, 1)
        self.assertIn("Updated Toronto", result.jobs[0].description or "")


class IncrementalRankSkipTests(unittest.TestCase):
    def test_repeat_rank_skips_unchanged(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "rank.db")
            search = {
                "tracks": ["data_engineering"],
                "seniority": {"include": ["mid", "senior"], "exclude": []},
                "location": {"prefer_remote_canada": True},
                "salary": {"min_cad": 130000},
            }
            profile = {
                "skills": {"primary": ["Python", "SQL"]},
                "experience": {"years": 7},
            }
            fp = scoring_fingerprint(search, profile)
            job = RawJob(
                company="Acme",
                title="Senior Data Engineer",
                url="https://example.com/j1",
                source="greenhouse",
                description="Python SQL Spark Databricks remote Canada Ontario",
                location_raw="Remote - Canada",
            )
            jid, _ = db.upsert_job(job)
            row = db.get_job(jid)
            assert row is not None
            db.save_score(
                jid,
                overall=80.0,
                scores={"skills": 80},
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
                re_rank=False,
                score_kind="deterministic",
                current_model=STAGE1_MODELS,
                config_fingerprint=fp,
            )
            self.assertEqual(pending, 0)
            needing = db.jobs_needing_score(
                limit=10,
                re_rank=False,
                score_kind="deterministic",
                current_model=STAGE1_MODELS,
                config_fingerprint=fp,
            )
            self.assertEqual(needing, [])
            # Config change must invalidate.
            search2 = {**search, "salary": {"min_cad": 200000}}
            fp2 = scoring_fingerprint(search2, profile)
            pending2 = db.count_jobs_needing_score(
                re_rank=False,
                score_kind="deterministic",
                current_model=STAGE1_MODELS,
                config_fingerprint=fp2,
            )
            self.assertEqual(pending2, 1)
            db.close()

    def test_workday_cache_indexes_url_path(self):
        with TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "cache.db")
            job = RawJob(
                company="RBC",
                title="Engineer",
                url="https://rbc.wd3.myworkdayjobs.com/en-US/RBC/job/Toronto/Role_R42",
                source="workday",
                ats_provider="workday",
                ats_job_id="R42",
                description="Complete RBC body",
                description_complete=True,
                description_fetched_at=_now(),
                location_raw="Toronto, ON",
            )
            db.upsert_job(job)
            cache = db.workday_description_cache(company="RBC")
            self.assertIn("R42", cache)
            self.assertIn("Role_R42", cache)
            self.assertEqual(cache["Role_R42"]["description"], "Complete RBC body")
            db.close()


if __name__ == "__main__":
    unittest.main()
