"""Company search-index free path must not hang forever."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from jobseek.companies.providers import search_index
from jobseek.http_client import RateLimitedClient


class SearchIndexTimeoutTests(unittest.TestCase):
    def test_ddgs_timeout_returns_empty(self):
        def hang(_query: str, *, max_results: int = 8):
            import time

            time.sleep(2)
            return [{"url": "https://boards.greenhouse.io/x", "title": "x"}]

        client = RateLimitedClient(min_interval_s=0)
        try:
            with patch.object(search_index, "_DDGS_TIMEOUT_S", 0.2):
                with patch.object(search_index, "_ddgs_text", side_effect=hang):
                    with patch.object(
                        client,
                        "get",
                        side_effect=RuntimeError("skip html fallback"),
                    ):
                        rows = search_index._ddg_results("software engineer Canada", client)
            self.assertEqual(rows, [])
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
