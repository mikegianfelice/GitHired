"""Legacy seen_jobs + tracker migration into SQLite."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from jobseek.db.store import Database


class MigrationTests(unittest.TestCase):
    def test_import_seen_and_tracker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = Database(root / "test.db")
            seen_path = root / "seen_jobs.json"
            seen_path.write_text(
                json.dumps(
                    {
                        "seen": {
                            "acme_ai-engineer": {
                                "company": "Acme",
                                "title": "AI Engineer",
                                "url": "https://example.com/jobs/1",
                                "location": "Remote Canada",
                                "portal": "greenhouse",
                                "rank_score": 72,
                                "gaps": ["No Rust"],
                                "status": "ranked",
                                "description": "Build models remotely in Canada.",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            tracker = root / "tracker.csv"
            with tracker.open("w", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(
                    fh,
                    fieldnames=[
                        "date",
                        "company",
                        "role",
                        "status",
                        "cv_file",
                        "cover_letter_file",
                        "source",
                        "notes",
                    ],
                )
                w.writeheader()
                w.writerow(
                    {
                        "date": "2026-01-01",
                        "company": "OtherCo",
                        "role": "Data Engineer",
                        "status": "applied",
                        "cv_file": "",
                        "cover_letter_file": "",
                        "source": "manual",
                        "notes": "ok",
                    }
                )

            n_seen = db.import_seen_jobs_json(seen_path)
            n_tracker = db.import_tracker_csv(tracker)
            self.assertEqual(n_seen, 1)
            self.assertEqual(n_tracker, 1)

            job = db._conn.execute("SELECT * FROM jobs").fetchone()
            self.assertEqual(job["company"], "Acme")
            score = db._conn.execute("SELECT * FROM job_scores").fetchone()
            self.assertEqual(float(score["overall"]), 72.0)
            self.assertEqual(score["score_kind"], "deterministic")
            self.assertTrue(db.is_tracked("OtherCo", "Data Engineer"))
            db.close()


if __name__ == "__main__":
    unittest.main()
