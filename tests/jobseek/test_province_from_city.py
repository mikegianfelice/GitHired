from __future__ import annotations

import unittest

from jobseek.public_shortlist.export import _province_code


class ProvinceFromCityTests(unittest.TestCase):
    def test_city_only_location_maps_to_province(self):
        self.assertEqual(_province_code("Toronto, Canada"), "ON")
        self.assertEqual(_province_code("Vancouver (Hybrid)"), "BC")
        self.assertEqual(_province_code("Montreal, Canada"), "QC")
        self.assertEqual(_province_code("Montréal (Remote)"), "QC")
        self.assertEqual(_province_code("Calgary"), "AB")
        self.assertEqual(_province_code("Ottawa, Canada"), "ON")
        self.assertEqual(_province_code("St. John's, Canada"), "NL")
        self.assertEqual(_province_code("Charlottetown"), "PE")
        self.assertEqual(_province_code("Whitehorse - Remote"), "YT")
        self.assertEqual(_province_code("Yellowknife"), "NT")
        self.assertEqual(_province_code("Iqaluit, Canada"), "NU")
        # London should map to Ontario only when Canadian context is present; location has Canada token here
        self.assertEqual(_province_code("London, Canada"), "ON")

    def test_explicit_province_wins_over_city_fallback(self):
        # If a province is explicitly present, it should be used directly
        self.assertEqual(_province_code("Toronto, Ontario"), "ON")
        self.assertEqual(_province_code("Vancouver, BC"), "BC")


if __name__ == "__main__":
    unittest.main()

