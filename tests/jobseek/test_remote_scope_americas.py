import unittest

from jobseek.public_shortlist.export import _remote_scope


class TestRemoteScopeAmericas(unittest.TestCase):
    def test_namer_remote(self):
        scope = _remote_scope("NAMER (Remote)", "remote", [])
        self.assertEqual(scope, "americas")

    def test_americas_remote(self):
        scope = _remote_scope("Remote - Americas", "remote", [])
        self.assertEqual(scope, "americas")


if __name__ == "__main__":
    unittest.main()

