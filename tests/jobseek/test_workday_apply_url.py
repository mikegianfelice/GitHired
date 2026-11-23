import unittest
from jobseek.adapters.workday import workday_apply_url, normalize_workday_job


class TestWorkdayApplyUrl(unittest.TestCase):
    def test_accepts_external_path_without_leading_slash(self):
        url = workday_apply_url("example.wd3.myworkdayjobs.com", "RBCGLOBAL1", "job/RBCGLOBAL1/abc123")
        self.assertTrue(url.endswith("/RBCGLOBAL1/job/RBCGLOBAL1/abc123"))

    def test_normalize_with_missing_slash_listing(self):
        listing = {"title": "Software Engineer", "externalPath": "job/TST/xyz789", "locationsText": "Toronto, ON"}
        job = normalize_workday_job(
            company_name="TestCo",
            host="example.wd3.myworkdayjobs.com",
            site="TST",
            listing=listing,
            detail=None,
        )
        self.assertIsNotNone(job)
        self.assertIn("myworkdayjobs.com", job.apply_url or "")


if __name__ == "__main__":
    unittest.main()

