"""first_seen persistence across full snapshot rebuilds."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from jobseek.discovery_history import load_prior_first_seen, preserve_discovery_timestamps


class DiscoveryHistoryTests(unittest.TestCase):
    def test_preserves_earlier_first_seen_from_prior_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            prior = Path(tmp) / "prior.json"
            prior.write_text(
                json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "17c9fd3c7ceb9813",
                                "first_seen": "2026-11-23",
                                "last_verified": "2026-11-23",
                            },
                            {
                                "id": "72c508594c7a95ca",
                                "first_seen": "2026-11-20",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            jobs = [
                {
                    "id": "17c9fd3c7ceb9813",
                    "first_seen": "2026-11-26",
                    "last_verified": "2026-11-26",
                    "discovered_today": True,
                },
                {
                    "id": "72c508594c7a95ca",
                    "first_seen": "2026-11-26",
                    "last_verified": "2026-11-26",
                    "discovered_today": True,
                },
                {
                    "id": "brandnew00000001",
                    "first_seen": "2026-11-26",
                    "last_verified": "2026-11-26",
                    "discovered_today": True,
                },
            ]
            preserve_discovery_timestamps(
                jobs,
                prior_snapshot_path=prior,
                today=date(2026, 11, 26),
            )
            by_id = {j["id"]: j for j in jobs}
            self.assertEqual(by_id["17c9fd3c7ceb9813"]["first_seen"], "2026-11-23")
            self.assertEqual(by_id["17c9fd3c7ceb9813"]["last_verified"], "2026-11-26")
            self.assertFalse(by_id["17c9fd3c7ceb9813"]["discovered_today"])
            self.assertEqual(by_id["72c508594c7a95ca"]["first_seen"], "2026-11-20")
            self.assertEqual(by_id["brandnew00000001"]["first_seen"], "2026-11-26")
            self.assertTrue(by_id["brandnew00000001"]["discovered_today"])

    def test_does_not_move_first_seen_forward(self):
        prior = {"abc": "2026-11-25"}
        jobs = [{"id": "abc", "first_seen": "2026-11-20", "discovered_today": False}]
        preserve_discovery_timestamps(jobs, prior_first_seen=prior, today=date(2026, 11, 26))
        self.assertEqual(jobs[0]["first_seen"], "2026-11-20")

    def test_load_prior_missing_file(self):
        self.assertEqual(load_prior_first_seen(Path("/no/such/file.json")), {})


if __name__ == "__main__":
    unittest.main()
