"""Regression: clearly foreign-only locations → INELIGIBLE for Canada candidates."""

from __future__ import annotations

import unittest

from jobseek.filters.location import classify_canada_eligibility


SEARCH = {
    "location": {
        "modes": ["remote_canada", "hybrid"],
        "cities": ["Toronto"],
        "provinces": ["Ontario", "ON"],
        "preferred": ["Remote - Canada"],
        "allow_us_employer_remote_with_canada_evidence": True,
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
    }
}

VANCOUVER = {
    "location": {
        **SEARCH["location"],
        "cities": ["Vancouver"],
        "provinces": ["British Columbia", "BC"],
        "modes": ["remote_canada", "hybrid"],
    }
}

TORONTO_HYBRID = {
    "location": {
        **SEARCH["location"],
        "cities": ["Toronto"],
        "provinces": ["Ontario", "ON"],
        "modes": ["remote_canada", "hybrid"],
    }
}


def _job(location: str, description: str = "Build data platforms.") -> dict:
    return {
        "title": "Data Engineer",
        "location_raw": location,
        "description": description,
    }


class ForeignGeoIneligibleTests(unittest.TestCase):
    def test_chengdu_sichuan_ineligible(self):
        elig, verdict, reasons, _ = classify_canada_eligibility(
            _job("Chengdu, Sichuan"), SEARCH
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_hong_kong_ineligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(_job("Hong Kong"), SEARCH)
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_quezon_city_philippines_ineligible(self):
        elig, _, _, _ = classify_canada_eligibility(
            _job("Quezon City, Philippines"), SEARCH
        )
        self.assertEqual(elig, "INELIGIBLE")

    def test_quezon_lapu_lapu_ineligible(self):
        elig, _, _, _ = classify_canada_eligibility(
            _job("Quezon City / Lapu-Lapu City"), SEARCH
        )
        self.assertEqual(elig, "INELIGIBLE")

    def test_chicago_il_usa_ineligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            _job("Chicago, IL, USA"), SEARCH
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_mount_laurel_nj_ineligible(self):
        elig, _, _, _ = classify_canada_eligibility(
            _job("Mount Laurel, New Jersey, USA"), SEARCH
        )
        self.assertEqual(elig, "INELIGIBLE")

    def test_remote_canada_eligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            _job("Remote - Canada"), SEARCH
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_remote_us_and_canada_eligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            _job("Remote US & Canada"), SEARCH
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_toronto_arrangement_may_be_uncertain(self):
        elig, verdict, reasons, _ = classify_canada_eligibility(
            _job("Toronto, ON", description="Join our Toronto team. Python SQL."),
            SEARCH,
        )
        self.assertEqual(elig, "UNCERTAIN")
        self.assertEqual(verdict, "FLAG")
        self.assertTrue(
            any("work arrangement not evidenced" in r.casefold() for r in reasons)
        )

    def test_ontario_hybrid_ineligible_for_vancouver(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            _job("Canada Hybrid (Ontario)"), VANCOUVER
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_ontario_hybrid_eligible_for_toronto(self):
        elig, verdict, reasons, _ = classify_canada_eligibility(
            _job(
                "Canada Hybrid (Ontario)",
                description="Hybrid role in Ontario. Python SQL.",
            ),
            TORONTO_HYBRID,
        )
        # Province hybrid matches Toronto candidate provinces → arrangement hybrid PASS
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_remote_usa_ineligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(_job("Remote, USA"), SEARCH)
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_french_montreal_recognized(self):
        cfg = {
            "location": {
                **SEARCH["location"],
                "cities": ["Montréal", "Montreal"],
                "provinces": ["Quebec", "QC"],
                "modes": ["remote_canada", "hybrid", "onsite"],
            }
        }
        elig, _, reasons, _ = classify_canada_eligibility(
            _job("Montréal, QC", description="Poste hybride à Montréal."),
            cfg,
        )
        # City match + onsite mode allowed → ELIGIBLE (or UNCERTAIN if arrangement unknown)
        self.assertIn(elig, ("ELIGIBLE", "UNCERTAIN"))
        self.assertFalse(elig == "INELIGIBLE")

    def test_multi_location_with_canada_stays_eligible(self):
        elig, _, _, _ = classify_canada_eligibility(
            _job("Toronto, ON | Chicago, IL, USA", description="Hybrid Toronto or Chicago."),
            SEARCH,
        )
        # Has Canadian location option — not foreign-only
        self.assertNotEqual(elig, "INELIGIBLE")

    def test_unknown_city_stays_uncertain(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            _job("Springfieldia"), SEARCH
        )
        self.assertEqual(elig, "UNCERTAIN")
        self.assertEqual(verdict, "FLAG")

    def test_missing_location_uncertain(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            _job(""), SEARCH
        )
        self.assertEqual(elig, "UNCERTAIN")
        self.assertEqual(verdict, "FLAG")

    def test_conflicting_canada_hire_vs_overseas_office(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            _job(
                "London, UK",
                description="Open to candidates in Canada. Office in London.",
            ),
            SEARCH,
        )
        # Overseas on-site + Canada hire phrase → UNCERTAIN (conflict), not ELIGIBLE
        self.assertIn(elig, ("UNCERTAIN", "INELIGIBLE"))
        self.assertNotEqual(elig, "ELIGIBLE")


if __name__ == "__main__":
    unittest.main()
