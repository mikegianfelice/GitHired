import unittest

from jobseek.filters.tracks import match_track, DEFAULT_TRACK_ALIASES


class TestDeveloperAlias(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = {"tracks": list(DEFAULT_TRACK_ALIASES.keys())}

    def test_senior_developer_matches(self):
        m = match_track("Senior Developer", self.cfg)
        self.assertTrue(m.matched, f"Expected generic 'Senior Developer' to match, got {m.reasons}")

    def test_software_architect_matches(self):
        m = match_track("Software Architect", self.cfg)
        self.assertTrue(m.matched, f"Expected 'Software Architect' to match, got {m.reasons}")

    def test_data_developer_matches_data_engineering(self):
        m = match_track("Data Developer", self.cfg)
        self.assertTrue(m.matched, f"Expected 'Data Developer' to match data engineering, got {m.reasons}")


if __name__ == "__main__":
    unittest.main()

