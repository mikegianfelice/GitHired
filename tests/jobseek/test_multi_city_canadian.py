import unittest

from jobseek.filters.location import classify_canada_eligibility

PUBLIC_LOC = {
    "location": {
        "modes": ["remote_canada", "hybrid", "onsite", "remote_province"],
        "cities": [],
        "provinces": [],
    }
}


class TestMultiCityCanadian(unittest.TestCase):
    def test_semicolon_multi_city_canada(self):
        job = {"location_raw": "Montréal; Lévis; The work arrangement for the position is hybrid work", "description": ""}
        elig, verdict, reasons, evidence = classify_canada_eligibility(job, PUBLIC_LOC)
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_slash_multi_city_canada(self):
        job = {"location_raw": "Toronto / Waterloo (Hybrid)", "description": ""}
        elig, verdict, reasons, evidence = classify_canada_eligibility(job, PUBLIC_LOC)
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")


if __name__ == "__main__":
    unittest.main()

