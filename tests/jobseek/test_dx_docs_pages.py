"""Guards for agent/developer DX pages and Cursor install deeplink."""

from __future__ import annotations

import base64
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
AGENTS = SITE / "agents" / "index.html"
DEVELOPERS = SITE / "developers" / "index.html"
DOCS_JS = SITE / "docs.js"


class DxDocsPagesTests(unittest.TestCase):
    def test_required_docs_files_exist(self) -> None:
        for path in (AGENTS, DEVELOPERS, DOCS_JS, SITE / "openapi.json", SITE / "llms.txt"):
            self.assertTrue(path.is_file(), path)

    def test_agents_page_has_official_cursor_deeplink(self) -> None:
        html = AGENTS.read_text(encoding="utf-8")
        self.assertIn("Give your AI agent access to Canadian tech jobs", html)
        self.assertIn(
            "cursor://anysphere.cursor-deeplink/mcp/install?name=githired&amp;config=",
            html,
        )
        # Config must decode to the production remote URL object (official Stripe-style).
        match = re.search(
            r"cursor://anysphere\.cursor-deeplink/mcp/install\?name=githired&amp;config=([A-Za-z0-9+/=]+)",
            html,
        )
        self.assertIsNotNone(match)
        raw = base64.b64decode(match.group(1))
        cfg = json.loads(raw)
        self.assertEqual(cfg, {"url": "https://api.githired.ca/mcp"})
        self.assertIn("data-copy=\"mcp-url\"", html)
        self.assertIn("data-copy=\"mcp-config\"", html)
        self.assertIn("api-status", html)
        self.assertIn("docs.js", html)
        # Do not claim Claude/ChatGPT one-click.
        self.assertIn("no official", html.casefold())

    def test_developers_page_covers_core_topics(self) -> None:
        html = DEVELOPERS.read_text(encoding="utf-8")
        for needle in (
            "Pagination",
            "Salary filtering",
            "Rate limits",
            "Dataset freshness",
            "Errors",
            "openapi.json",
            "next_cursor",
            "api-status",
        ):
            self.assertIn(needle, html)

    def test_docs_js_fetches_live_health(self) -> None:
        js = DOCS_JS.read_text(encoding="utf-8")
        self.assertIn("https://api.githired.ca/api/v1/health", js)
        self.assertIn("navigator.clipboard", js)

    def test_default_snapshot_limit_covers_inventory_headroom(self) -> None:
        from jobseek.public_shortlist.export import DEFAULT_LIMIT

        # 400 covers current ~358 eligible roles with modest headroom; keeps Worker bundle small.
        self.assertGreaterEqual(DEFAULT_LIMIT, 350)
        self.assertLessEqual(DEFAULT_LIMIT, 500)


if __name__ == "__main__":
    unittest.main()
