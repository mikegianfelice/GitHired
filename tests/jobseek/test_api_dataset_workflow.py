"""Regression guards for the API dataset sync GitHub Actions workflow."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "api-dataset.yml"


class ApiDatasetWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_file_exists(self) -> None:
        self.assertTrue(WORKFLOW.is_file())

    def test_installs_dev_extras_so_pytest_is_available(self) -> None:
        # Root cause of sync #1/#2: `pip install -e .` left pytest missing.
        self.assertRegex(
            self.text,
            r"""pip install -e ["']\.\[dev\]["']""",
        )
        self.assertIn("python -m pytest", self.text)

    def test_setup_does_not_pass_unsupported_email_flag(self) -> None:
        # `githired setup` has no --email; `|| true` previously hid the failure.
        setup_blocks = re.findall(
            r"githired setup --non-interactive.*?(?=\n\n|\n      - name:)",
            self.text,
            flags=re.S,
        )
        self.assertTrue(setup_blocks, "expected a non-interactive setup step")
        for block in setup_blocks:
            self.assertNotIn("--email", block)
            self.assertNotIn("|| true", block)

    def test_export_and_pytest_are_separate_steps(self) -> None:
        # Keep export success visible; missing pytest must not discard a good snapshot silently.
        self.assertIn("Export API snapshot", self.text)
        self.assertIn("Snapshot schema tests", self.text)
        export_idx = self.text.index("Export API snapshot")
        test_idx = self.text.index("Snapshot schema tests")
        self.assertLess(export_idx, test_idx)

    def test_refuses_empty_snapshot(self) -> None:
        self.assertIn("Refusing to publish empty API snapshot", self.text)

    def test_deploys_worker_after_successful_export(self) -> None:
        # GITHUB_TOKEN commits do not trigger api-worker.yml — deploy here.
        self.assertIn("wrangler deploy", self.text)
        self.assertIn("ENVIRONMENT:production", self.text)
        self.assertIn("refusing to leave production on a stale bundled snapshot", self.text.casefold())

    def test_does_not_print_cloudflare_secrets(self) -> None:
        # Ensure we never echo secret *values* into logs (names in error text are OK).
        self.assertNotRegex(self.text, r"echo\s+\"\$\{\{\s*secrets\.CLOUDFLARE_")
        self.assertNotRegex(self.text, r"echo\s+\"\$CLOUDFLARE_(API_TOKEN|ACCOUNT_ID)\"")
        self.assertNotIn("print(os.environ[\"CLOUDFLARE_API_TOKEN\"])", self.text)


if __name__ == "__main__":
    unittest.main()
