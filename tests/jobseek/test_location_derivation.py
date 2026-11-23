import unittest

from jobseek.filters.location import find_any_canadian_province


class TestProvinceDerivation(unittest.TestCase):
    def test_city_parentheses_hybrid(self):
        self.assertEqual(find_any_canadian_province("Toronto (Hybrid)"), ["Ontario"])

    def test_city_country_suffix(self):
        self.assertEqual(find_any_canadian_province("Vancouver, Canada"), ["British Columbia"])

    def test_remote_canada(self):
        self.assertEqual(find_any_canadian_province("Remote (Canada)"), [])

    def test_montreal_accents(self):
        self.assertEqual(find_any_canadian_province("Montréal, QC, Canada"), ["Quebec"])
        # Without explicit province token, infer from city
        self.assertEqual(find_any_canadian_province("Montréal, Canada"), ["Quebec"])

    def test_multiple_parts(self):
        self.assertEqual(find_any_canadian_province("Toronto / New York"), ["Ontario"])

    def test_greater_toronto_area(self):
        self.assertEqual(find_any_canadian_province("Greater Toronto Area"), ["Ontario"])
        self.assertEqual(find_any_canadian_province("GTA"), ["Ontario"])

    def test_bc_lower_mainland(self):
        self.assertEqual(find_any_canadian_province("Lower Mainland"), ["British Columbia"])

    def test_quebec_city_accents(self):
        self.assertEqual(find_any_canadian_province("Québec City"), ["Quebec"])


if __name__ == "__main__":
    unittest.main()

