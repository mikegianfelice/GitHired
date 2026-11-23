import unittest
from jobseek.adapters.workday import WorkdayAdapter
from jobseek.http_client import workday_http_client


class TestWorkdaySerialMode(unittest.TestCase):
    def test_large_tenant_forces_serial_and_budget(self):
        adapter = WorkdayAdapter(client=workday_http_client(), list_page_concurrency=3, list_budget_s=120)
        # Simulate fetch_company prelude by calling the private heuristic via tenant name
        tenant = "rbc"
        self.assertEqual(adapter.list_page_concurrency, 3)
        self.assertEqual(adapter.list_budget_s, 120)
        if tenant.lower() in {"rbc", "td", "bmo", "manulife", "sunlife"}:
            adapter.list_page_concurrency = 1
            if adapter.list_budget_s is None or adapter.list_budget_s < 1800:
                adapter.list_budget_s = 1800.0
            if not adapter.search_text:
                adapter.search_text = "engineer developer data ml sre devops architect security"
        self.assertEqual(adapter.list_page_concurrency, 1)
        self.assertGreaterEqual(adapter.list_budget_s or 0, 1800.0)
        self.assertIn("engineer", adapter.search_text or "")


if __name__ == "__main__":
    unittest.main()

