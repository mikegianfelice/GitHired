"""Adapter tests with mocked HTTP responses."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from jobseek.adapters.ashby import AshbyAdapter
from jobseek.adapters.detector import classify_host, detect_from_html
from jobseek.adapters.greenhouse import GreenhouseAdapter
from jobseek.adapters.lever import LeverAdapter
from jobseek.adapters.linkedin_compliant import import_alert_file, parse_alert_html
from jobseek.http_client import HttpResponse

FIXTURES = Path(__file__).parent / "fixtures"


def _client(payload, status=200, url="https://example.test"):
    client = MagicMock()
    text = payload if isinstance(payload, str) else json.dumps(payload)
    client.get.return_value = HttpResponse(status, text, url)
    return client


class GreenhouseAdapterTests(unittest.TestCase):
    def test_parses_jobs(self):
        data = json.loads((FIXTURES / "greenhouse_jobs.json").read_text())
        adapter = GreenhouseAdapter(client=_client(data))
        result = adapter.fetch_company({"name": "Example", "board_token": "example"})
        self.assertEqual(result.raw_status, 200)
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual(result.jobs[0].ats_provider, "greenhouse")
        self.assertEqual(result.jobs[0].ats_job_id, "1001")
        self.assertIn("Canada", result.jobs[0].location_raw or "")


class LeverAdapterTests(unittest.TestCase):
    def test_parses_jobs(self):
        data = json.loads((FIXTURES / "lever_jobs.json").read_text())
        adapter = LeverAdapter(client=_client(data))
        result = adapter.fetch_company({"name": "Example", "board_token": "example"})
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0].title, "Staff Data Engineer")
        self.assertEqual(result.jobs[0].salary_currency, "CAD")


class AshbyAdapterTests(unittest.TestCase):
    def test_parses_jobs(self):
        data = json.loads((FIXTURES / "ashby_jobs.json").read_text())
        adapter = AshbyAdapter(client=_client(data))
        result = adapter.fetch_company({"name": "Example", "board_token": "example"})
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual(result.jobs[0].ats_provider, "ashby")


class DetectorTests(unittest.TestCase):
    def test_greenhouse_host(self):
        d = classify_host("https://boards.greenhouse.io/acme/jobs/1")
        self.assertIsNotNone(d)
        self.assertEqual(d.ats, "greenhouse")
        self.assertEqual(d.board_token, "acme")

    def test_lookalike_rejected(self):
        d = classify_host("https://evil-greenhouse.io/acme/jobs/1")
        self.assertIsNone(d)

    def test_html_ashby(self):
        html = '<a href="https://jobs.ashbyhq.com/startup/abc">Apply</a>'
        d = detect_from_html(html, "https://startup.example/careers")
        self.assertIsNotNone(d)
        self.assertEqual(d.ats, "ashby")
        self.assertEqual(d.board_token, "startup")


class LinkedInAlertTests(unittest.TestCase):
    def test_parse_html_links(self):
        html = '''
        <a href="https://www.linkedin.com/jobs/view/1234567890">Role</a>
        <a href="https://www.linkedin.com/jobs/view/1234567890?ref=x">dup</a>
        '''
        jobs = parse_alert_html(html)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].ats_job_id, "1234567890")

    def test_import_json(self):
        path = FIXTURES / "alert_jobs.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "title": "AI Engineer",
                        "company": "Acme",
                        "url": "https://www.linkedin.com/jobs/view/999",
                    }
                ]
            ),
            encoding="utf-8",
        )
        result = import_alert_file(path)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0].company, "Acme")


if __name__ == "__main__":
    unittest.main()
