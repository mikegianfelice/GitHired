"""Freehire adapter normalization, URL policy, and default-off wiring."""

from __future__ import annotations

import json
import unittest

from jobseek.adapters.freehire import (
    FreehireAdapter,
    default_freehire_queries,
    normalize_freehire_job,
)
from jobseek.discover import _source_status
from jobseek.http_client import HttpResponse
from jobseek.config_loader import Settings


class _FakeClient:
    def __init__(self, pages: list):
        self.pages = list(pages)
        self.gets = []

    def get(self, url, *, params=None, headers=None):
        self.gets.append(url)
        if not self.pages:
            return HttpResponse(200, json.dumps({"data": [], "meta": {"total": 0}}), url)
        page = self.pages.pop(0)
        if isinstance(page, tuple):
            status, body = page
            text = body if isinstance(body, str) else json.dumps(body)
            return HttpResponse(status, text, url)
        return HttpResponse(200, json.dumps(page), url)


def _item(**overrides):
    base = {
        "public_slug": "swe-acme-abc123",
        "source": "greenhouse",
        "external_id": "1",
        "url": "https://boards.greenhouse.io/acme/jobs/1",
        "title": "Senior Software Engineer",
        "company": "Acme",
        "company_slug": "acme",
        "location": "Remote, Canada",
        "description": "Build things remotely in Canada.",
        "skills": ["python"],
        "work_mode": "remote",
        "regions": ["north_america"],
        "countries": ["ca"],
        "cities": [],
        "posted_at": "2026-10-20T00:00:00Z",
        "created_at": "2026-10-20T00:00:00Z",
        "enrichment": {},
    }
    base.update(overrides)
    return base


class NormalizeTests(unittest.TestCase):
    def test_direct_ats_is_actionable(self):
        job, meta = normalize_freehire_job(_item())
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.source, "freehire")
        self.assertTrue(meta["actionable"])
        self.assertIn("greenhouse.io", job.apply_url or "")

    def test_whatjobs_goes_to_review(self):
        job, meta = normalize_freehire_job(
            _item(url="https://ca.whatjobs.com/job/xyz", source="whatjobs")
        )
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.source, "freehire_review")
        self.assertTrue(meta["affiliate"])
        self.assertFalse(meta["actionable"])

    def test_provenance_preserved(self):
        job, meta = normalize_freehire_job(_item())
        assert job is not None
        self.assertEqual(job.raw_payload["freehire_slug"], "swe-acme-abc123")
        self.assertEqual(job.raw_payload["apply_url_verdict"]["kind"], "direct")

    def test_dedupe_within_adapter(self):
        client = _FakeClient(
            [
                {
                    "data": [
                        _item(public_slug="a", url="https://boards.greenhouse.io/a/1"),
                        _item(public_slug="b", url="https://boards.greenhouse.io/a/1"),
                        _item(
                            public_slug="c",
                            url="https://ca.whatjobs.com/job/1",
                            source="whatjobs",
                        ),
                    ]
                }
            ]
        )
        adapter = FreehireAdapter(client=client)  # type: ignore[arg-type]
        result = adapter.search([{"q": "engineer", "countries": "ca"}])
        self.assertEqual(len(result.jobs), 2)
        stats = adapter.last_stats
        self.assertEqual(stats["unique"], 2)
        self.assertEqual(stats["affiliate_rejected"], 1)
        self.assertEqual(stats["actionable"], 1)

    def test_provider_failure_is_soft(self):
        client = _FakeClient([(503, {"error": "down"})])
        adapter = FreehireAdapter(client=client)  # type: ignore[arg-type]
        result = adapter.search([{"q": "x", "countries": "ca"}])
        self.assertEqual(result.jobs, [])
        self.assertTrue(any("HTTP 503" in e for e in result.errors))

    def test_unreachable_is_soft(self):
        class Boom:
            def get(self, *a, **k):
                raise RuntimeError("dns")

        adapter = FreehireAdapter(client=Boom())  # type: ignore[arg-type]
        result = adapter.search([{"q": "x"}])
        self.assertEqual(result.jobs, [])
        self.assertTrue(any("unreachable" in e for e in result.errors))


class ConfigTests(unittest.TestCase):
    def test_default_off_in_source_status(self):
        info = _source_status({"freehire": False}, Settings.from_env())
        self.assertNotIn("freehire", info["sources_enabled"])
        self.assertTrue(
            any(s.get("source") == "freehire" for s in info["sources_skipped"])
        )

    def test_enabled_when_on(self):
        info = _source_status({"freehire": True}, Settings.from_env())
        self.assertIn("freehire", info["sources_enabled"])

    def test_default_queries_canada(self):
        qs = default_freehire_queries({})
        self.assertTrue(qs)
        self.assertTrue(all(q.get("countries") == "ca" for q in qs))


if __name__ == "__main__":
    unittest.main()
