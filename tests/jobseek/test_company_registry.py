"""Company registry merge, dedupe, and override precedence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jobseek.companies.registry import (
    load_merged_companies,
    validate_community_shape,
)
from jobseek.db.store import Database


class RegistryMergeTests(unittest.TestCase):
    def test_override_wins_enabled_and_exclude(self):
        builtin = [
            {
                "name": "Acme",
                "ats": "greenhouse",
                "board_token": "acme",
                "careers_url": "https://boards.greenhouse.io/acme",
                "enabled": True,
            },
            {
                "name": "Beta",
                "ats": "ashby",
                "board_token": "beta",
                "careers_url": "https://jobs.ashbyhq.com/beta",
                "enabled": True,
            },
        ]
        overrides = {
            "companies": [{"name": "Acme", "enabled": False, "notes": "user off"}],
            "exclude": [{"name": "Beta"}],
        }
        merged = load_merged_companies(
            builtin=builtin,
            community=[],
            db_rows=[],
            overrides=overrides,
        )
        names = {c["name"]: c for c in merged}
        self.assertIn("Acme", names)
        self.assertFalse(names["Acme"]["enabled"])
        self.assertEqual(names["Acme"]["notes"], "user off")
        self.assertNotIn("Beta", names)

        with_excluded = load_merged_companies(
            builtin=builtin,
            community=[],
            db_rows=[],
            overrides=overrides,
            include_excluded=True,
        )
        beta = next(c for c in with_excluded if c["name"] == "Beta")
        self.assertTrue(beta["excluded"])

    def test_dedupe_by_ats_token(self):
        builtin = [
            {
                "name": "Acme Inc",
                "ats": "greenhouse",
                "board_token": "acme",
                "careers_url": "https://acme.example/careers",
            }
        ]
        community = [
            {
                "name": "Acme",
                "ats": "greenhouse",
                "board_token": "acme",
                "careers_url": "https://boards.greenhouse.io/acme",
                "notes": "community",
            }
        ]
        merged = load_merged_companies(
            builtin=builtin,
            community=community,
            db_rows=[],
            overrides={"companies": [], "exclude": []},
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["notes"], "community")
        self.assertEqual(merged[0]["board_token"], "acme")

    def test_db_layer_overlays_builtin(self):
        builtin = [
            {
                "name": "Acme",
                "ats": "unknown",
                "board_token": None,
                "careers_url": "https://acme.example/careers",
                "enabled": True,
            }
        ]
        db_rows = [
            {
                "name": "Acme",
                "ats": "workable",
                "board_token": "acme",
                "careers_url": "https://apply.workable.com/acme/",
                "validation_status": "ok",
                "discovery_source": "detect",
            }
        ]
        merged = load_merged_companies(
            builtin=builtin,
            community=[],
            db_rows=db_rows,
            overrides={"companies": [], "exclude": []},
        )
        self.assertEqual(merged[0]["ats"], "workable")
        self.assertEqual(merged[0]["board_token"], "acme")
        self.assertEqual(merged[0]["validation_status"], "ok")


class CommunityShapeTests(unittest.TestCase):
    def test_requires_token_for_greenhouse(self):
        errors = validate_community_shape(
            [{"name": "X", "ats": "greenhouse", "board_token": None}]
        )
        self.assertTrue(any("board_token" in e for e in errors))

    def test_accepts_valid_row(self):
        errors = validate_community_shape(
            [
                {
                    "name": "X",
                    "ats": "greenhouse",
                    "board_token": "x",
                    "careers_url": "https://boards.greenhouse.io/x",
                }
            ]
        )
        self.assertEqual(errors, [])


class SchemaMigrationTests(unittest.TestCase):
    def test_new_company_columns_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "t.db")
            try:
                db.upsert_company(
                    name="Zed",
                    ats="greenhouse",
                    board_token="zed",
                    domain="zed.example",
                    discovery_source="builtin",
                    failure_count=2,
                    excluded=False,
                    validation_evidence_json='{"http_status":200}',
                )
                rows = db.list_companies()
                self.assertEqual(rows[0]["domain"], "zed.example")
                self.assertEqual(rows[0]["failure_count"], 2)
                stats = db.company_stats()
                self.assertEqual(stats["total"], 1)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
