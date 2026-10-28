"""CLI smoke tests for githired commands."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobseek.cli.main import main


class CliSmokeTests(unittest.TestCase):
    def test_doctor_json(self):
        code = main(["doctor", "--json"])
        self.assertIn(code, (0, 1))

    def test_setup_non_interactive(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config"
            db = Path(tmp) / "jobseek.db"
            env = {
                **os.environ,
                "JOBSEEK_CONFIG_DIR": str(cfg),
                "JOBSEEK_DB_PATH": str(db),
            }
            with patch.dict(os.environ, env, clear=False):
                with patch("jobseek.cli.main.Path.cwd", return_value=Path(tmp)):
                    code = main(
                        [
                            "setup",
                            "--non-interactive",
                            "--config-dir",
                            str(cfg),
                            "--tracks",
                            "ai_engineering",
                            "--modes",
                            "remote_canada",
                        ]
                    )
            self.assertEqual(code, 0)
            self.assertTrue((cfg / "search.yaml").is_file())

    def test_jobs_empty_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "empty.db"
            env = {**os.environ, "JOBSEEK_DB_PATH": str(db)}
            with patch.dict(os.environ, env, clear=False):
                code = main(["jobs", "--json"])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
