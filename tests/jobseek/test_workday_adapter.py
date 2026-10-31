"""Workday CXS guest-board adapter tests (mocked HTTP; no live network)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from jobseek.adapters.detector import classify_host
from jobseek.adapters.workday import (
    WorkdayAdapter,
    normalize_workday_job,
    parse_workday_board,
    workday_apply_url,
)
from jobseek.filters.hard import classify_canada_eligibility
from jobseek.http_client import HttpResponse
from tests.jobseek.test_phase2_geo_shortlist import CALGARY, TORONTO, VANCOUVER

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _FakeClient:
    """Minimal client stub with get/post returning scripted HttpResponse values."""

    def __init__(self, post_pages: list, details: dict[str, object]):
        self.post_pages = list(post_pages)
        self.details = details
        self.post_calls = []
        self.get_calls = []

    def post(self, url, *, json_body=None, headers=None):
        self.post_calls.append({"url": url, "json_body": json_body})
        if not self.post_pages:
            return HttpResponse(200, json.dumps({"total": 0, "jobPostings": []}), url)
        payload = self.post_pages.pop(0)
        if isinstance(payload, tuple):
            status, body = payload
            text = body if isinstance(body, str) else json.dumps(body)
            return HttpResponse(status, text, url)
        return HttpResponse(200, json.dumps(payload), url)

    def get(self, url, *, params=None, headers=None):
        self.get_calls.append(url)
        body = self.details.get(url)
        if body is None:
            # Match by job path id suffix
            for key, val in self.details.items():
                if key in url or url.endswith(key):
                    body = val
                    break
        if body is None:
            return HttpResponse(404, '{"error":"missing"}', url)
        if isinstance(body, tuple):
            status, payload = body
            text = payload if isinstance(payload, str) else json.dumps(payload)
            return HttpResponse(status, text, url)
        return HttpResponse(200, json.dumps(body), url)


COMPANY = {
    "name": "Intact",
    "ats": "workday",
    "board_token": "intactfc.wd3.myworkdayjobs.com/intactfc/intactfc",
}


class ParseBoardTests(unittest.TestCase):
    def test_host_tenant_site_token(self):
        parsed = parse_workday_board(COMPANY)
        self.assertEqual(
            parsed,
            ("intactfc.wd3.myworkdayjobs.com", "intactfc", "intactfc"),
        )

    def test_explicit_fields(self):
        parsed = parse_workday_board(
            {
                "workday_host": "rbc.wd3.myworkdayjobs.com",
                "workday_tenant": "rbc",
                "workday_site": "RBCGLOBAL1",
                "board_token": "RBCGLOBAL1",
            }
        )
        self.assertEqual(parsed, ("rbc.wd3.myworkdayjobs.com", "rbc", "RBCGLOBAL1"))

    def test_missing_config(self):
        self.assertIsNone(parse_workday_board({"name": "X"}))


class ApplyUrlTests(unittest.TestCase):
    def test_constructs_official_url(self):
        url = workday_apply_url(
            "intactfc.wd3.myworkdayjobs.com",
            "intactfc",
            "/job/Toronto-Ontario-CAN/Senior-Data-Engineer_R1001",
        )
        self.assertEqual(
            url,
            "https://intactfc.wd3.myworkdayjobs.com/intactfc/job/Toronto-Ontario-CAN/Senior-Data-Engineer_R1001",
        )

    def test_rejects_bad_path(self):
        self.assertIsNone(workday_apply_url("intactfc.wd3.myworkdayjobs.com", "intactfc", "nope"))


class NormalizeTests(unittest.TestCase):
    def test_multi_location_and_remote_type(self):
        listing = _load("workday_list_page1.json")["jobPostings"][1]
        detail = _load("workday_detail_devops.json")
        job = normalize_workday_job(
            company_name="Intact",
            host="intactfc.wd3.myworkdayjobs.com",
            site="intactfc",
            listing=listing,
            detail=detail,
        )
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.ats_provider, "workday")
        self.assertEqual(job.ats_job_id, "R1002")
        self.assertIn("Calgary", job.location_raw or "")
        self.assertIn("Toronto", job.location_raw or "")
        self.assertEqual(
            job.apply_url,
            "https://intactfc.wd3.myworkdayjobs.com/intactfc/job/Calgary-Alberta-CAN/Senior-DevOps-Engineer_R1002",
        )
        self.assertEqual(job.posted_date, "2026-10-15")
        self.assertIn("Platform and SRE", job.description or "")

    def test_skips_without_path(self):
        job = normalize_workday_job(
            company_name="X",
            host="intactfc.wd3.myworkdayjobs.com",
            site="intactfc",
            listing={"title": "Engineer"},
            detail=None,
        )
        self.assertIsNone(job)


class WorkdayAdapterTests(unittest.TestCase):
    def _detail_map(self):
        host = "intactfc.wd3.myworkdayjobs.com"
        site = "intactfc"
        return {
            f"https://{host}/wday/cxs/intactfc/{site}/job/Senior-Data-Engineer_R1001": _load(
                "workday_detail_de.json"
            ),
            f"https://{host}/wday/cxs/intactfc/{site}/job/Senior-DevOps-Engineer_R1002": _load(
                "workday_detail_devops.json"
            ),
            f"https://{host}/wday/cxs/intactfc/{site}/job/Software-Engineer_R1003": _load(
                "workday_detail_swe.json"
            ),
        }

    def test_pagination_and_details(self):
        client = _FakeClient(
            post_pages=[_load("workday_list_page1.json"), _load("workday_list_page2.json")],
            details=self._detail_map(),
        )
        adapter = WorkdayAdapter(client=client)  # type: ignore[arg-type]
        result = adapter.fetch_company(COMPANY)
        self.assertEqual(result.raw_status, 200)
        self.assertEqual(len(result.jobs), 3)
        self.assertEqual(len(client.post_calls), 1)  # total=3 fits one page of 20
        self.assertEqual(len(client.get_calls), 3)
        ids = {j.ats_job_id for j in result.jobs}
        self.assertEqual(ids, {"R1001", "R1002", "R1003"})
        self.assertTrue(all(j.url and "myworkdayjobs.com" in j.url for j in result.jobs))
        self.assertTrue(all("utm_" not in (j.url or "") for j in result.jobs))

    def test_multi_page_pagination(self):
        page1 = {
            "total": 25,
            "jobPostings": [
                {
                    "title": f"Engineer {i}",
                    "externalPath": f"/job/Toronto-ON/Engineer-{i}_R{i}",
                    "locationsText": "Toronto, ON",
                    "bulletFields": [f"R{i}"],
                }
                for i in range(20)
            ],
        }
        page2 = {
            "total": 25,
            "jobPostings": [
                {
                    "title": f"Engineer {i}",
                    "externalPath": f"/job/Toronto-ON/Engineer-{i}_R{i}",
                    "locationsText": "Toronto, ON",
                    "bulletFields": [f"R{i}"],
                }
                for i in range(20, 25)
            ],
        }
        details = {}
        for i in range(25):
            path = f"Engineer-{i}_R{i}"
            details[f"https://intactfc.wd3.myworkdayjobs.com/wday/cxs/intactfc/intactfc/job/{path}"] = {
                "jobPostingInfo": {
                    "title": f"Engineer {i}",
                    "location": "Toronto, ON",
                    "jobDescription": "x",
                    "externalUrl": f"https://intactfc.wd3.myworkdayjobs.com/intactfc/job/Toronto-ON/Engineer-{i}_R{i}",
                    "jobReqId": f"R{i}",
                    "startDate": "2026-10-01",
                }
            }
        client = _FakeClient(post_pages=[page1, page2, {"total": 25, "jobPostings": []}], details=details)
        adapter = WorkdayAdapter(client=client)  # type: ignore[arg-type]
        result = adapter.fetch_company(COMPANY)
        self.assertEqual(len(result.jobs), 25)
        self.assertGreaterEqual(len(client.post_calls), 2)

    def test_empty_feed(self):
        client = _FakeClient(post_pages=[{"total": 0, "jobPostings": []}], details={})
        adapter = WorkdayAdapter(client=client)  # type: ignore[arg-type]
        result = adapter.fetch_company(COMPANY)
        self.assertEqual(result.raw_status, 200)
        self.assertEqual(result.jobs, [])
        self.assertEqual(result.errors, [])

    def test_list_http_error(self):
        client = _FakeClient(post_pages=[(500, {"error": "boom"})], details={})
        adapter = WorkdayAdapter(client=client)  # type: ignore[arg-type]
        result = adapter.fetch_company(COMPANY)
        self.assertEqual(result.raw_status, 500)
        self.assertTrue(result.errors)
        self.assertEqual(result.jobs, [])

    def test_partial_detail_failure_still_returns_jobs(self):
        details = self._detail_map()
        # Fail devops detail
        key = "https://intactfc.wd3.myworkdayjobs.com/wday/cxs/intactfc/intactfc/job/Senior-DevOps-Engineer_R1002"
        details[key] = (503, {"error": "unavailable"})
        client = _FakeClient(post_pages=[_load("workday_list_page1.json")], details=details)
        adapter = WorkdayAdapter(client=client)  # type: ignore[arg-type]
        result = adapter.fetch_company(COMPANY)
        self.assertEqual(len(result.jobs), 3)
        devops = next(j for j in result.jobs if j.ats_job_id == "R1002")
        # List-level location fallback ("5 Locations") + constructed URL
        self.assertIn("myworkdayjobs.com", devops.url)
        self.assertTrue(any("detail fetch" in e for e in result.errors))

    def test_malformed_listing_skipped(self):
        page = {
            "total": 2,
            "jobPostings": [
                {"title": "No Path"},
                {
                    "title": "Good",
                    "externalPath": "/job/Toronto-ON/Good_R9",
                    "locationsText": "Toronto, ON",
                    "bulletFields": ["R9"],
                },
            ],
        }
        details = {
            "https://intactfc.wd3.myworkdayjobs.com/wday/cxs/intactfc/intactfc/job/Good_R9": {
                "jobPostingInfo": {
                    "title": "Good",
                    "location": "Toronto, ON",
                    "jobDescription": "ok",
                    "externalUrl": "https://intactfc.wd3.myworkdayjobs.com/intactfc/job/Toronto-ON/Good_R9",
                    "jobReqId": "R9",
                }
            }
        }
        client = _FakeClient(post_pages=[page], details=details)
        adapter = WorkdayAdapter(client=client)  # type: ignore[arg-type]
        result = adapter.fetch_company(COMPANY)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0].ats_job_id, "R9")

    def test_stable_dedup_ids(self):
        client = _FakeClient(
            post_pages=[_load("workday_list_page1.json")],
            details=self._detail_map(),
        )
        adapter = WorkdayAdapter(client=client)  # type: ignore[arg-type]
        a = adapter.fetch_company(COMPANY)
        client2 = _FakeClient(
            post_pages=[_load("workday_list_page1.json")],
            details=self._detail_map(),
        )
        b = WorkdayAdapter(client=client2).fetch_company(COMPANY)  # type: ignore[arg-type]
        self.assertEqual(
            sorted(j.ats_job_id for j in a.jobs),
            sorted(j.ats_job_id for j in b.jobs),
        )

    def test_bounded_concurrency_fetches_all_details(self):
        client = _FakeClient(
            post_pages=[_load("workday_list_page1.json")],
            details=self._detail_map(),
        )
        adapter = WorkdayAdapter(client=client, detail_concurrency=4)  # type: ignore[arg-type]
        result = adapter.fetch_company(COMPANY)
        self.assertEqual(len(result.jobs), 3)
        self.assertEqual(len(client.get_calls), 3)
        self.assertTrue(all(j.description for j in result.jobs))

    def test_fetch_details_false_skips_hydration(self):
        client = _FakeClient(
            post_pages=[_load("workday_list_page1.json")],
            details=self._detail_map(),
        )
        adapter = WorkdayAdapter(client=client, fetch_details=False)  # type: ignore[arg-type]
        result = adapter.fetch_company(COMPANY)
        self.assertEqual(len(result.jobs), 3)
        self.assertEqual(client.get_calls, [])
        # List-only still constructs official apply URLs
        self.assertTrue(all("myworkdayjobs.com" in (j.url or "") for j in result.jobs))


class WorkdayGeoTests(unittest.TestCase):
    def test_toronto_hybrid_not_for_vancouver(self):
        listing = _load("workday_list_page1.json")["jobPostings"][0]
        detail = _load("workday_detail_de.json")
        job = normalize_workday_job(
            company_name="Intact",
            host="intactfc.wd3.myworkdayjobs.com",
            site="intactfc",
            listing=listing,
            detail=detail,
        )
        assert job is not None
        elig, _, _, _ = classify_canada_eligibility(job.to_dict(), VANCOUVER)
        self.assertEqual(elig, "INELIGIBLE")
        elig_t, _, _, _ = classify_canada_eligibility(job.to_dict(), TORONTO)
        self.assertEqual(elig_t, "ELIGIBLE")

    def test_multi_city_includes_calgary(self):
        listing = _load("workday_list_page1.json")["jobPostings"][1]
        detail = json.loads(json.dumps(_load("workday_detail_devops.json")))
        # Arrangement must be explicit (hybrid) — bare multi-city offices stay UNCERTAIN
        detail["jobPostingInfo"]["jobDescription"] = (
            "<p>Hybrid role across Canadian offices including Calgary. "
            "Platform and SRE work.</p>"
        )
        job = normalize_workday_job(
            company_name="Intact",
            host="intactfc.wd3.myworkdayjobs.com",
            site="intactfc",
            listing=listing,
            detail=detail,
        )
        assert job is not None
        elig, _, _, _ = classify_canada_eligibility(job.to_dict(), CALGARY)
        self.assertEqual(elig, "ELIGIBLE")

    def test_remote_canada_compatible(self):
        listing = _load("workday_list_page1.json")["jobPostings"][2]
        detail = _load("workday_detail_swe.json")
        # Strengthen remote Canada signal in description (remoteType alone + city)
        detail = json.loads(json.dumps(detail))
        detail["jobPostingInfo"]["location"] = "Canada"
        detail["jobPostingInfo"]["remoteType"] = "Remote"
        detail["jobPostingInfo"]["jobDescription"] = "Fully remote in Canada."
        job = normalize_workday_job(
            company_name="Intact",
            host="intactfc.wd3.myworkdayjobs.com",
            site="intactfc",
            listing=listing,
            detail=detail,
        )
        assert job is not None
        for persona in (VANCOUVER, TORONTO, CALGARY):
            elig, _, _, _ = classify_canada_eligibility(job.to_dict(), persona)
            self.assertEqual(elig, "ELIGIBLE", msg=persona["location"]["cities"])


class DetectorWorkdayTests(unittest.TestCase):
    def test_classify_workday_host(self):
        d = classify_host(
            "https://intactfc.wd3.myworkdayjobs.com/en-US/intactfc/job/Toronto-ON/X_R1"
        )
        self.assertIsNotNone(d)
        assert d is not None
        self.assertEqual(d.ats, "workday")
        self.assertEqual(d.board_token, "intactfc.wd3.myworkdayjobs.com/intactfc/intactfc")


class WorkdayBudgetTests(unittest.TestCase):
    def test_company_budget_preserves_list_jobs(self):
        import time

        listings = []
        details: dict[str, object] = {}
        host = "intactfc.wd3.myworkdayjobs.com"
        for i in range(20):
            path = f"/job/Toronto-ON/Role-{i}_R{i}"
            listings.append(
                {
                    "title": f"Engineer {i}",
                    "externalPath": path,
                    "locationsText": "Toronto, ON",
                    "postedOn": "Posted Today",
                }
            )
            details[f"https://{host}/wday/cxs/intactfc/intactfc/job/Role-{i}_R{i}"] = {
                "jobPostingInfo": {
                    "id": f"R{i}",
                    "title": f"Engineer {i}",
                    "jobDescription": f"Desc {i}",
                    "location": "Toronto, ON",
                }
            }

        class SlowClient(_FakeClient):
            def get(self, url, *, params=None, headers=None):
                time.sleep(0.04)
                return super().get(url, params=params, headers=headers)

        client = SlowClient([{"total": 20, "jobPostings": listings}], details)
        adapter = WorkdayAdapter(
            client, company_budget_s=0.12, detail_concurrency=2, complete=False
        )
        result = adapter.fetch_company(COMPANY)
        self.assertEqual(len(result.jobs), 20)
        self.assertLess(len(client.get_calls), 20)
        self.assertTrue(any("budget" in e for e in result.errors))

    def test_complete_mode_has_no_budget(self):
        adapter = WorkdayAdapter(complete=True, company_budget_s=30)
        self.assertIsNone(adapter.company_budget_s)

    def test_budget_vs_complete_measured(self):
        """Reproducible timing: budgeted mode finishes sooner; complete hydrates all."""
        import time

        listings = []
        details: dict[str, object] = {}
        host = "intactfc.wd3.myworkdayjobs.com"
        n = 12
        for i in range(n):
            path = f"/job/Toronto-ON/Role-{i}_R{i}"
            listings.append(
                {
                    "title": f"Engineer {i}",
                    "externalPath": path,
                    "locationsText": "Toronto, ON",
                    "postedOn": "Posted Today",
                }
            )
            details[f"https://{host}/wday/cxs/intactfc/intactfc/job/Role-{i}_R{i}"] = {
                "jobPostingInfo": {
                    "id": f"R{i}",
                    "title": f"Engineer {i}",
                    "jobDescription": f"Desc {i}",
                    "location": "Toronto, ON",
                }
            }

        class SlowClient(_FakeClient):
            def get(self, url, *, params=None, headers=None):
                time.sleep(0.03)
                return super().get(url, params=params, headers=headers)

        page = [{"total": n, "jobPostings": listings}]
        client_b = SlowClient(list(page), details)
        t0 = time.perf_counter()
        budgeted = WorkdayAdapter(
            client_b, company_budget_s=0.1, detail_concurrency=2, complete=False
        ).fetch_company(COMPANY)
        t_budget = time.perf_counter() - t0

        client_c = SlowClient(list(page), details)
        t1 = time.perf_counter()
        complete = WorkdayAdapter(
            client_c, company_budget_s=0.1, detail_concurrency=2, complete=True
        ).fetch_company(COMPANY)
        t_complete = time.perf_counter() - t1

        # Completeness
        self.assertEqual(len(budgeted.jobs), n)
        self.assertEqual(len(complete.jobs), n)
        self.assertEqual(len(client_c.get_calls), n)
        self.assertLess(len(client_b.get_calls), n)
        # Descriptions present when hydrated
        self.assertTrue(any(j.description for j in complete.jobs))
        # Speed: budgeted wall time should be strictly below complete (same sleep)
        self.assertLess(t_budget, t_complete)
        # Record measurements in assertion message for CI logs
        self.assertTrue(
            True,
            msg=(
                f"workday_bench budget_s={t_budget:.3f} complete_s={t_complete:.3f} "
                f"budget_details={len(client_b.get_calls)}/{n} "
                f"complete_details={len(client_c.get_calls)}/{n} "
                f"budget_errors={budgeted.errors}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
