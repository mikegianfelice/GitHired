import unittest

from jobseek.filters.tracks import match_track, DEFAULT_TRACK_ALIASES


class TestTrackMatchSuffixes(unittest.TestCase):
    def setUp(self) -> None:
        # Default config selects all engineering families by default (when tracks unset)
        self.cfg = {"tracks": list(DEFAULT_TRACK_ALIASES.keys())}

    def test_software_developer_ii(self):
        m = match_track("Software Developer II", self.cfg)
        self.assertTrue(m.matched, f"expected match for 'Software Developer II', got {m.reasons}")

    def test_software_engineer_2(self):
        m = match_track("Senior Software Engineer 2", self.cfg)
        self.assertTrue(m.matched, f"expected match for 'Software Engineer 2', got {m.reasons}")

    def test_sre_ii(self):
        m = match_track("SRE II", self.cfg)
        self.assertTrue(m.matched, f"expected match for 'SRE II', got {m.reasons}")

    def test_engineering_not_overrun(self):
        # Ensure we don't overmatch into words like 'Engineering'
        m = match_track("Director of Engineering", self.cfg)
        self.assertFalse(m.matched, "must not match bare 'Engineering' without a role phrase")


if __name__ == "__main__":
    unittest.main()

