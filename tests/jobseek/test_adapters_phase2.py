"""Phase 2 adapter + detector tests (mocked HTTP)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from jobseek.adapters.detector import classify_host, detect_from_html
from jobseek.adapters.gem import GemAdapter
from jobseek.adapters.rippling import RipplingAdapter
from jobseek.adapters.rss import RssAdapter, parse_feed_xml
from jobseek.adapters.workable import WorkableAdapter
from jobseek.http_client import HttpResponse

FIXTURES = Path(__file__).parent / "fixtures"


def _client(payload, status=200, url="https://example.test"):
    client = MagicMock()
    text = payload if isinstance(payload, str) else json.dumps(payload)
    client.get.return_value = HttpResponse(status, text, url)
    return client


class WorkableAdapterTests(unittest.TestCase):
    def test_parses_jobs(self):
        data = json.loads((FIXTURES / "workable_jobs.json").read_text())
        adapter = WorkableAdapter(client=_client(data))
        result = adapter.fetch_company({"name": "Example", "board_token": "example"})
        self.assertEqual(result.raw_status, 200)
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual(result.jobs[0].ats_provider, "workable")
        self.assertEqual(result.jobs[0].ats_job_id, "ABC123")
        self.assertIn("Toronto", result.jobs[0].location_raw or "")


class RssAdapterTests(unittest.TestCase):
    def test_parses_shopify_style_feed(self):
        xml = (FIXTURES / "shopify_jobs.xml").read_text()
        jobs = parse_feed_xml(xml, company_name="Shopify", source_url="https://example/feed.xml")
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].ats_provider, "rss")
        self.assertEqual(jobs[0].ats_job_id, "job-1")
        self.assertIn("Remote", jobs[0].location_raw or "")

    def test_adapter_fetch(self):
        xml = (FIXTURES / "shopify_jobs.xml").read_text()
        adapter = RssAdapter(client=_client(xml, url="https://www.shopify.com/careers/feed.xml"))
        result = adapter.fetch_company(
            {
                "name": "Shopify",
                "board_token": "https://www.shopify.com/careers/feed.xml",
            }
        )
        self.assertEqual(result.raw_status, 200)
        self.assertEqual(len(result.jobs), 2)

    def test_empty_standard_rss_is_ok(self):
        xml = '<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
        adapter = RssAdapter(client=_client(xml))
        result = adapter.fetch_company(
            {"name": "Empty", "board_token": "https://example.com/feed.xml"}
        )
        self.assertEqual(result.raw_status, 200)
        self.assertEqual(result.jobs, [])
        self.assertEqual(result.errors, [])


class RipplingAdapterTests(unittest.TestCase):
    def test_parses_jobs(self):
        data = json.loads((FIXTURES / "rippling_jobs.json").read_text())
        adapter = RipplingAdapter(client=_client(data))
        result = adapter.fetch_company({"name": "Rippling", "board_token": "rippling"})
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0].ats_provider, "rippling")
        self.assertIn("Canada", result.jobs[0].location_raw or "")


class GemAdapterTests(unittest.TestCase):
    def test_empty_page_without_links_is_empty_not_crash(self):
        html = "<html><body><h1>Careers at Gem</h1><p>No openings.</p></body></html>"
        adapter = GemAdapter(client=_client(html, url="https://jobs.gem.com/retool"))
        result = adapter.fetch_company({"name": "Retool", "board_token": "retool"})
        self.assertEqual(result.raw_status, 200)
        self.assertEqual(result.jobs, [])


class DetectorPhase2Tests(unittest.TestCase):
    def test_workable_host(self):
        d = classify_host("https://apply.workable.com/huggingface/")
        self.assertIsNotNone(d)
        self.assertEqual(d.ats, "workable")
        self.assertEqual(d.board_token, "huggingface")

    def test_rippling_api_host(self):
        d = classify_host("https://ats.rippling.com/api/v2/board/rippling/jobs")
        self.assertIsNotNone(d)
        self.assertEqual(d.ats, "rippling")
        self.assertEqual(d.board_token, "rippling")

    def test_gem_host(self):
        d = classify_host("https://jobs.gem.com/retool")
        self.assertIsNotNone(d)
        self.assertEqual(d.ats, "gem")
        self.assertEqual(d.board_token, "retool")

    def test_html_workable(self):
        html = '<a href="https://apply.workable.com/acme/j/XYZ/">Apply</a>'
        d = detect_from_html(html, "https://acme.example/careers")
        self.assertIsNotNone(d)
        self.assertEqual(d.ats, "workable")
        self.assertEqual(d.board_token, "acme")


if __name__ == "__main__":
    unittest.main()
