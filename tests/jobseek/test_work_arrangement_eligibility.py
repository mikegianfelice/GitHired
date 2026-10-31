"""Work arrangement is a separate gate from geographic eligibility (Phase 1 / P0)."""

from __future__ import annotations

import unittest

from jobseek.filters.location import (
    classify_canada_eligibility,
    infer_work_arrangement,
    work_arrangement_compatible,
)
from jobseek.rank.scorer import SCORER_VERSION


def _cfg(
    *,
    city: str = "Toronto",
    provinces: list[str] | None = None,
    modes: list[str] | None = None,
) -> dict:
    return {
        "tracks": ["software_engineering"],
        "track_aliases": {},
        "seniority": {"include": ["mid", "senior"], "exclude": ["intern"]},
        "location": {
            "modes": modes or ["remote_canada", "hybrid"],
            "preferred": [
                "Canada remote",
                "Remote Canada",
                "Remote - Canada",
                "Canada (Remote)",
                "Anywhere in Canada",
            ],
            "reject_us_only_remote": True,
            "unknown_location_policy": "flag",
            "cities": [city],
            "provinces": provinces
            or (
                ["Ontario", "ON"]
                if city == "Toronto"
                else ["British Columbia", "BC"]
                if city == "Vancouver"
                else ["Alberta", "AB"]
                if city == "Calgary"
                else ["Quebec", "QC"]
            ),
        },
        "salary": {"reject_missing": False, "floors": {}},
    }


class InferArrangementTests(unittest.TestCase):
    def test_location_onsite_token(self):
        self.assertEqual(
            infer_work_arrangement("Toronto, Ontario (On-site)", ""),
            "onsite",
        )

    def test_description_five_days_office(self):
        self.assertEqual(
            infer_work_arrangement(
                "Toronto, Ontario",
                "Must work in office five days per week",
            ),
            "onsite",
        )

    def test_hybrid_location(self):
        self.assertEqual(infer_work_arrangement("Hybrid - Toronto", ""), "hybrid")

    def test_remote_canada(self):
        self.assertEqual(infer_work_arrangement("Remote, Canada", ""), "remote")

    def test_unknown_when_bare_city(self):
        self.assertEqual(infer_work_arrangement("Toronto, Ontario", ""), "unknown")


class ArrangementModeMatrixTests(unittest.TestCase):
    def test_onsite_requires_onsite_mode(self):
        self.assertEqual(
            work_arrangement_compatible("onsite", {"remote_canada", "hybrid"}),
            "FAIL",
        )
        self.assertEqual(
            work_arrangement_compatible("onsite", {"onsite", "hybrid"}),
            "PASS",
        )

    def test_hybrid_requires_hybrid_mode(self):
        self.assertEqual(
            work_arrangement_compatible("hybrid", {"remote_canada"}),
            "FAIL",
        )
        self.assertEqual(
            work_arrangement_compatible("hybrid", {"remote_canada", "hybrid"}),
            "PASS",
        )

    def test_unknown_is_flag(self):
        self.assertEqual(
            work_arrangement_compatible("unknown", {"remote_canada", "hybrid"}),
            "FLAG",
        )


class ReproductionAndMatrixTests(unittest.TestCase):
    """Parameterized geography × arrangement cases from the Phase 1 brief."""

    def test_toronto_onsite_fails_for_remote_hybrid_only(self):
        """Primary reproduction: city match must not override on-site."""
        elig, verdict, reasons, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Toronto, Ontario (On-site)",
                "description": "Must work in office five days per week",
            },
            _cfg(city="Toronto", modes=["remote_canada", "hybrid"]),
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")
        self.assertTrue(any("work arrangement incompatible" in r for r in reasons))

    def test_toronto_onsite_passes_when_onsite_allowed(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Toronto, Ontario (On-site)",
                "description": "Must work in office five days per week",
            },
            _cfg(city="Toronto", modes=["remote_canada", "hybrid", "onsite"]),
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_toronto_hybrid_passes_for_toronto_hybrid_candidate(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Data Engineer",
                "location_raw": "Hybrid - Toronto",
                "description": "Hybrid in Toronto office 2–3 days/week.",
            },
            _cfg(city="Toronto", modes=["remote_canada", "hybrid"]),
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_ontario_hybrid_fails_for_vancouver(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Canada Hybrid (Ontario)",
                "description": "Hybrid role in Ontario.",
            },
            _cfg(
                city="Vancouver",
                provinces=["British Columbia", "BC"],
                modes=["remote_canada", "hybrid"],
            ),
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_remote_canada_passes(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Backend Engineer",
                "location_raw": "Remote, Canada",
                "description": "Fully remote in Canada.",
            },
            _cfg(city="Calgary", provinces=["Alberta", "AB"]),
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_us_only_remote_fails(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Remote - US",
                "description": "Must be located in the United States. US only.",
            },
            _cfg(city="Toronto"),
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_ambiguous_city_without_arrangement_is_uncertain(self):
        elig, verdict, reasons, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Toronto, Ontario",
                "description": "Join our engineering team.",
            },
            _cfg(city="Toronto", modes=["remote_canada", "hybrid"]),
        )
        self.assertEqual(elig, "UNCERTAIN")
        self.assertEqual(verdict, "FLAG")
        self.assertTrue(any("not evidenced" in r for r in reasons))

    def test_multi_location_hybrid_includes_candidate_city(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Toronto; Vancouver; Montreal",
                "description": "Hybrid possible across Canadian offices.",
            },
            _cfg(
                city="Vancouver",
                provinces=["British Columbia", "BC"],
                modes=["remote_canada", "hybrid"],
            ),
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_conflicting_description_does_not_invent_remote(self):
        """On-site location + remote marketing fluff stays on-site."""
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Platform Engineer",
                "location_raw": "Mississauga (On-site)",
                "description": (
                    "We are a remote-friendly company culture. "
                    "This role requires on-site presence five days per week."
                ),
            },
            _cfg(
                city="Toronto",
                modes=["remote_canada", "hybrid"],
            ),
        )
        # Mississauga ≠ Toronto → geo fail; even if city matched, on-site would fail modes.
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_scorer_version_bumped_for_stale_pass_invalidation(self):
        self.assertEqual(SCORER_VERSION, "v9")


if __name__ == "__main__":
    unittest.main()
