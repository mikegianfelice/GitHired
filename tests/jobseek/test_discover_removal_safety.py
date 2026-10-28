"""Failed ATS fetches must not mark existing jobs removed."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from jobseek.adapters.base import AdapterResult
from jobseek.db.store import Database
from jobseek.discover import run_discover
from jobseek.models import RawJob


class RemovalSafetyTests(unittest.TestCase):
    def test_failed_fetch_does_not_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            existing = RawJob(
                company="Shopify",
                title="AI Engineer",
                url="https://boards.greenhouse.io/shopify/jobs/1",
                source="greenhouse",
                ats_provider="greenhouse",
                ats_job_id="1",
                description="Remote Canada",
            )
            job_id, _ = db.upsert_job(existing)

            companies = [
                {
                    "name": "Shopify",
                    "ats": "greenhouse",
                    "board_token": "shopify",
                    "enabled": True,
                    "careers_url": "https://www.shopify.com/careers",
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

            failed = AdapterResult(
                request_key="greenhouse:shopify",
                raw_status=500,
                errors=["greenhouse shopify: HTTP 500"],
            )

            inst = MagicMock()
            inst.fetch_company.return_value = failed
            with (
                patch("jobseek.discover.load_companies", return_value=companies),
                patch("jobseek.discover.load_search", return_value=search),
                patch.dict("jobseek.discover.ADAPTERS", {"greenhouse": lambda client=None: inst}),
            ):
                summary = run_discover(db, detect_unknown=False)

            self.assertTrue(summary["errors"])
            row = db.get_job(job_id)
            self.assertIsNone(row["removed_at"])
            self.assertNotEqual(row["status"], "removed")
            self.assertEqual(summary.get("removed_marked", 0), 0)
            db.close()


if __name__ == "__main__":
    unittest.main()
