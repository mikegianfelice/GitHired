import unittest
from jobseek.filters.tracks import title_matches_selected_tracks


class TestTrackAliases(unittest.TestCase):
    def setUp(self):
        # Select software_engineering only for precise matching
        self.search_cfg = {"tracks": ["software_engineering"]}

    def test_qa_automation_is_software_engineering(self):
        titles = [
            "QA Automation Engineer",
            "QA Automation Developer",
            "Test Automation Engineer",
            "SDET",
        ]
        for t in titles:
            with self.subTest(title=t):
                self.assertTrue(title_matches_selected_tracks(t, self.search_cfg))

    def test_business_systems_analyst_is_excluded(self):
        self.assertFalse(title_matches_selected_tracks("Business Systems Analyst", self.search_cfg))

    def test_data_scientist_is_not_software_engineering(self):
        self.assertFalse(title_matches_selected_tracks("Senior Data Scientist", self.search_cfg))


if __name__ == "__main__":
    unittest.main()

