import unittest

from jobseek.filters.location import find_any_canadian_province


class TestCitySuburbsProvince(unittest.TestCase):
    def test_gta_suburbs(self):
        self.assertEqual(find_any_canadian_province("Mississauga, Canada"), ["Ontario"])
        self.assertEqual(find_any_canadian_province("Markham, ON"), ["Ontario"])
        self.assertEqual(find_any_canadian_province("Richmond Hill"), ["Ontario"])
        self.assertEqual(find_any_canadian_province("North York, Canada"), ["Ontario"])
        self.assertEqual(find_any_canadian_province("Etobicoke, ON, Canada"), ["Ontario"])

    def test_greater_montreal(self):
        self.assertEqual(find_any_canadian_province("Laval, Canada"), ["Quebec"])
        self.assertEqual(find_any_canadian_province("Brossard, QC"), ["Quebec"])
        self.assertEqual(find_any_canadian_province("Longueuil, QC, Canada"), ["Quebec"])

    def test_ottawa_kanata(self):
        self.assertEqual(find_any_canadian_province("Kanata, Canada"), ["Ontario"])

    def test_bc_suburbs(self):
        self.assertEqual(find_any_canadian_province("Burnaby, Canada"), ["British Columbia"])
        self.assertEqual(find_any_canadian_province("Richmond, BC"), ["British Columbia"])


if __name__ == "__main__":
    unittest.main()

