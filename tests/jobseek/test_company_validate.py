"""Company validation pipeline outcomes."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from jobseek.adapters.base import AdapterResult
from jobseek.companies.validate import (
    should_skip_validation,
    validate_company,
    persist_validation,
)
from jobseek.db.store import Database
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob


class FakeAdapter:
    def __init__(self, client=None, result: AdapterResult | None = None):
        self.client = client
        self._result = result or AdapterResult(raw_status=200, jobs=[])

    def fetch_company(self, company):
        return self._result


class ValidateTests(unittest.TestCase):
    def test_http_200_alone_with_bad_structure_is_invalid(self):
        result = AdapterResult(
            raw_status=200,
            jobs=[],
            errors=["workable x: invalid JSON (boom)"],
        )
        adapters = {"workable": lambda client: FakeAdapter(client, result)}
        out = validate_company(
            {"name": "X", "ats": "workable", "board_token": "x"},
            adapters=adapters,
            client=MagicMock(),
        )
        self.assertEqual(out.status, "invalid")
        self.assertFalse(out.enable)

    def test_empty_board_is_empty_not_invalid(self):
        result = AdapterResult(raw_status=200, jobs=[], errors=[])
        adapters = {"rss": lambda client: FakeAdapter(client, result)}
        out = validate_company(
            {
                "name": "FeedCo",
                "ats": "rss",
                "board_token": "https://example.com/feed.xml",
                "careers_url": "https://feedco.example/careers",
                "domain": "feedco.example",
            },
            adapters=adapters,
            client=MagicMock(),
            auto_enable=True,
        )
        self.assertEqual(out.status, "empty")
        self.assertTrue(out.enable)

    def test_transient_on_429(self):
        result = AdapterResult(raw_status=429, jobs=[], errors=["rate limited"])
        adapters = {"greenhouse": lambda client: FakeAdapter(client, result)}
        out = validate_company(
            {"name": "G", "ats": "greenhouse", "board_token": "g"},
            adapters=adapters,
            client=MagicMock(),
        )
        self.assertEqual(out.status, "transient")

    def test_unsupported_without_adapter(self):
        out = validate_company(
            {"name": "W", "ats": "workday", "board_token": "w"},
            adapters={},
            client=MagicMock(),
        )
        self.assertEqual(out.status, "unsupported")

    def test_skip_invalid_without_force(self):
        reason = should_skip_validation({"validation_status": "invalid", "name": "X"})
        self.assertEqual(reason, "skip_invalid")
        self.assertIsNone(
            should_skip_validation(
                {"validation_status": "invalid", "name": "X"}, force=True
            )
        )

    def test_persist_increments_failure_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            try:
                db.upsert_company(name="FailCo", ats="greenhouse", board_token="f")
                from jobseek.companies.validate import ValidationResult

                persist_validation(
                    db,
                    {"name": "FailCo", "ats": "greenhouse", "board_token": "f"},
                    ValidationResult(status="invalid", evidence={}, error="HTTP 404"),
                )
                row = db.list_companies()[0]
                self.assertEqual(row["validation_status"], "invalid")
                self.assertEqual(row["failure_count"], 1)
            finally:
                db.close()

    def test_ok_with_matching_jobs_enables(self):
        jobs = [
            RawJob(
                company="Acme Corp",
                title="Engineer",
                url="https://boards.greenhouse.io/acme/jobs/1",
                source="greenhouse",
                ats_provider="greenhouse",
                ats_job_id="1",
            )
        ]
        result = AdapterResult(raw_status=200, jobs=jobs, errors=[])
        adapters = {"greenhouse": lambda client: FakeAdapter(client, result)}
        out = validate_company(
            {
                "name": "Acme",
                "ats": "greenhouse",
                "board_token": "acme",
                "careers_url": "https://acme.example/careers",
                "domain": "acme.example",
            },
            adapters=adapters,
            client=MagicMock(),
            auto_enable=True,
        )
        self.assertEqual(out.status, "ok")
        self.assertTrue(out.enable)


if __name__ == "__main__":
    unittest.main()
