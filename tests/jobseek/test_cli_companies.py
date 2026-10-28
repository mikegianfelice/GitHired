"""CLI tests for nested `githired companies` commands."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobseek.cli.main import build_parser, main
from jobseek.db.store import Database


class CompaniesCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "jobseek.db"
        self.db = Database(self.db_path)
        self.db.upsert_company(
            name="Acme",
            ats="greenhouse",
            board_token="acme",
            validation_status="ok",
            enabled=True,
            discovery_source="builtin",
        )
        self.db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def _env(self):
        return patch.dict(
            "os.environ",
            {"GITHIRED_DB_PATH": str(self.db_path), "JOBSEEK_DB_PATH": str(self.db_path)},
        )

    def test_parser_has_companies_subcommands(self):
        parser = build_parser("githired")
        args = parser.parse_args(["companies", "list", "--json"])
        self.assertEqual(args.companies_command, "list")

    def test_list_json(self):
        with self._env():
            code = main(["companies", "list", "--json"])
        self.assertEqual(code, 0)

    def test_stats(self):
        with self._env():
            code = main(["companies", "stats"])
        self.assertEqual(code, 0)

    def test_export_import_roundtrip(self):
        out = Path(self.tmp.name) / "export.yaml"
        with self._env():
            code = main(["companies", "export", "--validated", "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertTrue(out.is_file())
        with self._env():
            code = main(["companies", "import", str(out)])
        self.assertEqual(code, 0)

    def test_discover_no_validate_offline(self):
        with self._env():
            with patch(
                "jobseek.companies.discover.collect_search_index_candidates",
                return_value=([], ["search skipped"]),
            ):
                with patch(
                    "jobseek.companies.discover.collect_career_page_candidates",
                    return_value=([], []),
                ):
                    code = main(["companies", "discover", "--no-validate"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
