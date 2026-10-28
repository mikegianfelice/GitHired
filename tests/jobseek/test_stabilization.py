"""Phase 1 stabilization regression tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from jobseek.adapters.base import AdapterResult
from jobseek.db.store import Database
from jobseek.discover import run_discover
from jobseek.filters.hard import apply_hard_filters, classify_canada_eligibility
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob
from jobseek.profile_util import profile_warnings
from jobseek.rank.scorer import score_deterministic
from jobseek.rank.selection import select_jobs_fairly


SEARCH = {
    "tracks": ["ai_engineering", "data_engineering", "software_engineering"],
    "track_aliases": {
        "ai_engineering": ["AI Engineer"],
        "data_engineering": ["Data Engineer"],
        "software_engineering": ["Software Engineer"],
    },
    "seniority": {
        "include": ["mid", "senior", "staff", "principal", "lead"],
        "exclude": ["intern", "coop", "student", "new_grad", "junior"],
    },
    "location": {
        "modes": ["remote_canada"],
        "preferred": ["Canada remote"],
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
        "cities": ["Toronto"],
        "provinces": ["Ontario"],
    },
    "salary": {"reject_missing": False, "floors": {"CAD": 120000}},
}


class HttpClientHeadersTests(unittest.TestCase):
    def test_get_accepts_headers_kwarg(self):
        client = RateLimitedClient(min_interval_s=0)
        with patch.object(client._client, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "ok"
            mock_resp.url = "https://example.com"
            mock_resp.headers = {}
            mock_get.return_value = mock_resp
            resp = client.get("https://example.com", headers={"User-Agent": "test"})
            self.assertEqual(resp.status_code, 200)
            kwargs = mock_get.call_args.kwargs
            self.assertIn("headers", kwargs)
            self.assertEqual(kwargs["headers"]["User-Agent"], "test")
        client.close()


class DiscoverPartialFailureTests(unittest.TestCase):
    def test_partial_board_failure_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            companies = [
                {
                    "name": "GoodCo",
                    "ats": "greenhouse",
                    "board_token": "good",
                    "enabled": True,
                    "careers_url": "https://example.com",
                },
                {
                    "name": "BadCo",
                    "ats": "greenhouse",
                    "board_token": "bad",
                    "enabled": True,
                    "careers_url": "https://example.com",
                },
            ]
            search = {
                "sources": {
                    "greenhouse": True,
                    "lever": False,
                    "ashby": False,
                    "career_pages": False,
                    "linkedin_search_index": False,
                }
            }

            def fetch(company):
                if company["name"] == "GoodCo":
                    return AdapterResult(
                        request_key="gh:good",
                        raw_status=200,
                        jobs=[
                            RawJob(
                                company="GoodCo",
                                title="AI Engineer",
                                url="https://example.com/1",
                                source="greenhouse",
                                description="Remote Canada",
                            )
                        ],
                    )
                return AdapterResult(
                    request_key="gh:bad",
                    raw_status=404,
                    errors=["greenhouse bad: HTTP 404"],
                )

            good_adapter = MagicMock()
            good_adapter.fetch_company.side_effect = fetch
            with (
                patch("jobseek.discover.load_companies", return_value=companies),
                patch("jobseek.discover.load_search", return_value=search),
                patch.dict("jobseek.discover.ADAPTERS", {"greenhouse": lambda client=None: good_adapter}),
            ):
                summary = run_discover(db, detect_unknown=False)

            self.assertTrue(summary.get("ok"), summary)
            self.assertEqual(summary.get("errors"), [])
            self.assertEqual(len(summary.get("board_failures") or []), 1)
            self.assertGreaterEqual(summary.get("fetched", 0), 1)
            db.close()

    def test_all_boards_fail_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            companies = [
                {
                    "name": "BadCo",
                    "ats": "greenhouse",
                    "board_token": "bad",
                    "enabled": True,
                    "careers_url": "https://example.com",
                }
            ]
            search = {
                "sources": {
                    "greenhouse": True,
                    "lever": False,
                    "ashby": False,
                    "career_pages": False,
                    "linkedin_search_index": False,
                }
            }
            bad_adapter = MagicMock()
            bad_adapter.fetch_company.return_value = AdapterResult(
                request_key="gh:bad", raw_status=500, errors=["HTTP 500"]
            )
            with (
                patch("jobseek.discover.load_companies", return_value=companies),
                patch("jobseek.discover.load_search", return_value=search),
                patch.dict("jobseek.discover.ADAPTERS", {"greenhouse": lambda client=None: bad_adapter}),
            ):
                summary = run_discover(db, detect_unknown=False)
            self.assertFalse(summary.get("ok"))
            self.assertTrue(summary.get("errors"))
            db.close()


class EligibilityTests(unittest.TestCase):
    def test_three_states(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "AI Engineer",
                "location_raw": "Remote - Canada",
                "description": "Work from Canada.",
            },
            SEARCH,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "AI Engineer",
                "location_raw": "Remote, United States",
                "description": "US remote team. Offices in NYC.",
            },
            SEARCH,
        )
        self.assertEqual(elig, "UNCERTAIN")
        self.assertEqual(verdict, "FLAG")

        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "AI Engineer",
                "location_raw": "Remote",
                "description": "Must be located in the United States only.",
            },
            SEARCH,
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")


class DigestGapsTests(unittest.TestCase):
    def test_hard_filter_reasons_not_in_gaps(self):
        job = {
            "title": "AI Engineer",
            "location_raw": "Remote - Canada",
            "description": "Remote in Canada. Python.",
            "first_seen": "2026-10-01T00:00:00Z",
        }
        scored = score_deterministic(
            job,
            search_cfg=SEARCH,
            profile={"skills": {"primary": ["Python"], "secondary": [], "domain": []}},
        )
        for gap in scored.gaps:
            self.assertNotIn("title matched", gap.casefold())
            self.assertNotIn("canada /", gap.casefold())
            self.assertNotIn("salary missing", gap.casefold())


class SelectionFairnessTests(unittest.TestCase):
    def test_round_robin_across_companies(self):
        candidates = []
        for company in ("A", "B", "C"):
            for i in range(10):
                candidates.append(
                    {
                        "id": len(candidates) + 1,
                        "company": company,
                        "title": "AI Engineer",
                        "location_raw": "Remote Canada",
                        "description": "Canada remote",
                        "first_seen": "2026-10-01T00:00:00Z",
                    }
                )
        # Without fairness, first_seen DESC within one company could dominate;
        # with fairness, at least 3 companies appear in a batch of 9.
        selected = select_jobs_fairly(candidates, limit=9, max_per_company=3)
        companies = {j["company"] for j in selected}
        self.assertEqual(companies, {"A", "B", "C"})
        self.assertEqual(len(selected), 9)

    def test_jobs_needing_score_distributes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            for company in ("Acme", "Beta", "Cohere"):
                for i in range(5):
                    db.upsert_job(
                        RawJob(
                            company=company,
                            title=f"AI Engineer {i}",
                            url=f"https://example.com/{company}/{i}",
                            source="greenhouse",
                            description="Remote in Canada. Python.",
                            location_raw="Remote Canada",
                        )
                    )
            selected = db.jobs_needing_score(limit=6, score_kind="deterministic")
            companies = {j["company"] for j in selected}
            self.assertGreaterEqual(len(companies), 2)
            db.close()


class ProfileWarningTests(unittest.TestCase):
    def test_placeholder_detected(self):
        warnings = profile_warnings(
            {
                "identity": {"name": "[YOUR_NAME]"},
                "skills": {"primary": [], "secondary": [], "domain": []},
            }
        )
        self.assertTrue(any("placeholder" in w or "empty" in w for w in warnings))


class UncertainPenaltyTests(unittest.TestCase):
    def test_uncertain_penalized_vs_eligible(self):
        profile = {"skills": {"primary": ["Python"], "secondary": [], "domain": []}}
        eligible = score_deterministic(
            {
                "title": "Senior AI Engineer",
                "location_raw": "Remote - Canada",
                "description": "Remote in Canada. Python.",
                "first_seen": "2026-10-01T00:00:00Z",
            },
            search_cfg=SEARCH,
            profile=profile,
        )
        uncertain = score_deterministic(
            {
                "title": "Senior AI Engineer",
                "location_raw": "Remote, United States",
                "description": "US remote. Python. Offices in NYC.",
                "first_seen": "2026-10-01T00:00:00Z",
            },
            search_cfg=SEARCH,
            profile=profile,
        )
        self.assertEqual(eligible.hard_filter.eligibility, "ELIGIBLE")
        self.assertEqual(uncertain.hard_filter.eligibility, "UNCERTAIN")
        self.assertGreater(eligible.overall, uncertain.overall)
        self.assertLessEqual(uncertain.overall, 68)


if __name__ == "__main__":
    unittest.main()
