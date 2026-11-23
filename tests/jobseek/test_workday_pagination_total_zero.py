import unittest
from typing import Any, Tuple, List
from jobseek.adapters.workday import WorkdayAdapter


class FakeAdapter(WorkdayAdapter):
    def __init__(self) -> None:
        super().__init__(fetch_details=False, list_budget_s=None, detail_budget_s=None, complete=True)
        self._calls: List[int] = []

    def _fetch_list_page(  # type: ignore[override]
        self, list_url: str, offset: int
    ) -> Tuple[int, int | None, list[dict[str, Any]], int | None, str | None]:
        # Simulate: page 0 total=80 with 20 postings; later pages total=0 but deliver data.
        self._calls.append(offset)
        def page(batch_n: int) -> list[dict[str, Any]]:
            return [
                {
                    "externalPath": f"/job/{offset+i}",
                    "title": f"Engineer {offset+i}",
                    "locationsText": "Toronto, ON",
                }
                for i in range(batch_n)
            ]
        if offset == 0:
            return 0, 200, page(20), 80, None
        if offset in (20, 40):
            return offset, 200, page(20), 0, None  # total=0 quirk on later pages
        if offset == 60:
            return offset, 200, page(10), 0, None  # final partial page
        return offset, 200, [], 0, None


class TestWorkdayPaginationTotalZero(unittest.TestCase):
    def test_later_pages_total_zero_are_ignored(self):
        fa = FakeAdapter()
        # Large-tenant heuristic uses serial pagination; exercise that path here.
        fa.list_page_concurrency = 1
        listings, status, errors, meta = fa._paginate_listings("https://example/wday/cxs/t/site/jobs")
        self.assertEqual(status, 200)
        # 20 + 20 + 20 + 10 = 70 unique
        self.assertEqual(len(listings), 70)
        self.assertTrue(meta["complete"])
        self.assertFalse(any("coverage shortfall" in e for e in errors))
        # Ensure we visited offsets 0,20,40,60
        self.assertEqual(sorted(set(fa._calls)), [0, 20, 40, 60])


if __name__ == "__main__":
    unittest.main()

