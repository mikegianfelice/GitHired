"""Phase 2 regressions: candidate-city geo, shortlist padding, seniority."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jobseek.db.store import Database
from jobseek.filters.hard import apply_hard_filters, classify_canada_eligibility
from jobseek.filters.tracks import seniority_gate
from jobseek.models import RawJob


def _persona(
    *,
    city: str,
    provinces: list[str],
    tracks: list[str],
    seniority_include: list[str],
    seniority_exclude: list[str] | None = None,
) -> dict:
    return {
        "tracks": tracks,
        "track_aliases": {},
        "seniority": {
            "include": seniority_include,
            "exclude": seniority_exclude
            or ["intern", "coop", "student", "new_grad"],
        },
        "location": {
            "modes": ["remote_canada", "hybrid"],
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
            "provinces": provinces,
        },
        "salary": {"reject_missing": False, "floors": {"CAD": 70000}},
    }


VANCOUVER = _persona(
    city="Vancouver",
    provinces=["British Columbia", "BC"],
    tracks=["software_engineering", "ai_engineering"],
    seniority_include=["mid", "senior", "staff", "principal", "lead"],
    seniority_exclude=["intern", "coop", "student", "new_grad", "junior"],
)
TORONTO = _persona(
    city="Toronto",
    provinces=["Ontario", "ON"],
    tracks=["data_engineering", "analytics_engineering"],
    seniority_include=["mid", "senior", "staff", "principal", "lead"],
    seniority_exclude=["intern", "coop", "student", "new_grad", "junior"],
)
MONTREAL = _persona(
    city="Montreal",
    provinces=["Quebec", "QC"],
    tracks=["software_engineering"],
    seniority_include=["junior", "mid"],
    seniority_exclude=["intern", "coop", "student", "new_grad", "senior", "staff", "principal", "lead"],
)
CALGARY = _persona(
    city="Calgary",
    provinces=["Alberta", "AB"],
    tracks=["devops_sre", "platform_engineering", "cloud_engineering"],
    seniority_include=["mid", "senior", "staff", "principal", "lead"],
    seniority_exclude=["intern", "coop", "student", "new_grad", "junior"],
)


class CandidateCityGeoTests(unittest.TestCase):
    def test_vancouver_washington_not_canadian_vancouver(self):
        """US 'Vancouver, Washington' must not count as Vancouver BC."""
        elig, verdict, reasons, evidence = classify_canada_eligibility(
            {
                "title": "Senior Software Engineer, Data Infrastructure",
                "location_raw": (
                    "Bethesda, Maryland, United States; "
                    "Vancouver, Washington, United States; "
                    "Waltham, Massachusetts, United States"
                ),
                "description": "Build data infrastructure. Offices in the US.",
            },
            VANCOUVER,
        )
        # Must not be confirmed ELIGIBLE (US Vancouver, WA ≠ Vancouver BC).
        self.assertNotEqual(elig, "ELIGIBLE")
        self.assertIn(elig, ("INELIGIBLE", "UNCERTAIN"))
        self.assertNotIn("Vancouver", evidence)

    def test_vancouver_bc_still_eligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Vancouver, BC",
                "description": "Hybrid in Vancouver office.",
            },
            VANCOUVER,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_vancouver_toronto_hybrid_ineligible(self):
        elig, verdict, reasons, evidence = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Hybrid - Toronto",
                "description": "Hybrid role in Toronto office.",
            },
            VANCOUVER,
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")
        self.assertTrue(any("Toronto" in e for e in evidence) or any("incompatible" in r for r in reasons))

    def test_canada_hybrid_ontario_ineligible_for_montreal(self):
        """Phase 6: 'Canada Hybrid (Ontario)' is province-restricted, not nationwide."""
        elig, verdict, reasons, evidence = classify_canada_eligibility(
            {
                "title": "Software Engineer II, Toast International",
                "location_raw": "Canada Hybrid (Ontario)",
                "description": "Hybrid role in Ontario.",
            },
            MONTREAL,
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")
        self.assertTrue(
            any("Ontario" in e for e in evidence)
            or any("province-restricted" in r for r in reasons)
        )

    def test_canada_hybrid_ontario_eligible_for_toronto(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Canada Hybrid (Ontario)",
                "description": "Hybrid role in Ontario.",
            },
            TORONTO,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_canada_hybrid_alberta_eligible_for_calgary(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "DevOps Engineer",
                "location_raw": "Canada Hybrid (Alberta)",
                "description": "Hybrid in Alberta.",
            },
            CALGARY,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_remote_ontario_ineligible_for_quebec(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Backend Engineer",
                "location_raw": "Remote, Ontario",
                "description": "Remote within Ontario only.",
            },
            MONTREAL,
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_remote_canada_no_province_still_eligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Backend Engineer",
                "location_raw": "Remote, Canada",
                "description": "Fully remote in Canada.",
            },
            MONTREAL,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_remote_canada_with_conflicting_province_uncertain(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Backend Engineer",
                "location_raw": "Remote Canada; Ontario",
                "description": "Remote in Canada with Ontario hub.",
            },
            MONTREAL,
        )
        self.assertEqual(elig, "UNCERTAIN")
        self.assertEqual(verdict, "FLAG")

    def test_vancouver_remote_canada_eligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Remote, Canada",
                "description": "Fully remote in Canada.",
            },
            VANCOUVER,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_toronto_toronto_hybrid_eligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Data Engineer",
                "location_raw": "Hybrid - Toronto",
                "description": "Hybrid in Toronto.",
            },
            TORONTO,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_calgary_montreal_onsite_ineligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Site Reliability Engineer",
                "location_raw": "Montreal, QC",
                "description": "On-site in Montreal.",
            },
            CALGARY,
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_unknown_arrangement_uncertain(self):
        elig, verdict, reasons, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "",
                "description": "We have teammates across North America.",
            },
            VANCOUVER,
        )
        self.assertEqual(elig, "UNCERTAIN")
        self.assertEqual(verdict, "FLAG")

    def test_multi_city_includes_candidate(self):
        elig, _, _, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Toronto; Vancouver; Montreal",
                "description": "Office locations listed; hybrid possible.",
            },
            VANCOUVER,
        )
        self.assertEqual(elig, "ELIGIBLE")

    def test_multi_city_without_candidate_not_inferred_remote(self):
        elig, _, reasons, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Toronto; Montreal",
                "description": "Offices in Toronto and Montreal.",
            },
            VANCOUVER,
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertTrue(any("not remote" in r.casefold() or "incompatible" in r.casefold() for r in reasons))

    def test_province_list_includes_candidate(self):
        elig, _, _, _ = classify_canada_eligibility(
            {
                "title": "Senior Software Engineer",
                "location_raw": "British Columbia; Ontario",
                "description": "Canadian engineering hubs.",
            },
            VANCOUVER,
        )
        self.assertEqual(elig, "ELIGIBLE")

    def test_hub_remote_other_city_uncertain(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "Toronto (Remote)",
                "description": "Remote role listed under Toronto hub.",
            },
            VANCOUVER,
        )
        self.assertEqual(elig, "UNCERTAIN")
        self.assertEqual(verdict, "FLAG")

    def test_english_on_not_ontario(self):
        elig, _, _, _ = classify_canada_eligibility(
            {
                "title": "Software Engineer",
                "location_raw": "London, UK",
                "description": "Work on on-premises systems on call.",
            },
            VANCOUVER,
        )
        self.assertEqual(elig, "INELIGIBLE")

    def test_montreal_remote_canada_eligible(self):
        elig, _, _, _ = classify_canada_eligibility(
            {
                "title": "Backend Engineer",
                "location_raw": "Remote - Canada",
                "description": "Remote within Canada.",
            },
            MONTREAL,
        )
        self.assertEqual(elig, "ELIGIBLE")

    def test_toronto_canada_without_remote_not_eligible_for_montreal(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Backend Engineer, Payments & Risk",
                "location_raw": "Toronto, Canada",
                "description": "Stripe Toronto office.",
            },
            MONTREAL,
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_wfa_description_does_not_override_other_city_offices(self):
        elig, verdict, reasons, _ = classify_canada_eligibility(
            {
                "title": "Staff Software Engineer, High Availability",
                "location_raw": "Seattle, San Francisco, Seattle, New York, Toronto",
                "description": (
                    "Work from anywhere. Flexible remote culture. "
                    "Offices in Seattle, SF, NYC, and Toronto."
                ),
            },
            VANCOUVER,
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")
        self.assertTrue(
            any(
                "incompatible" in r.casefold() or "not remote" in r.casefold()
                for r in reasons
            )
        )


class SeniorityPhase2Tests(unittest.TestCase):
    def test_junior_blocks_staff_title(self):
        gate = seniority_gate("Staff Software Engineer", MONTREAL)
        self.assertFalse(gate.allowed)

    def test_junior_blocks_principal_and_lead(self):
        self.assertFalse(seniority_gate("Principal Software Engineer", MONTREAL).allowed)
        self.assertFalse(seniority_gate("Lead Software Engineer", MONTREAL).allowed)

    def test_junior_allows_mid_and_intermediate(self):
        self.assertTrue(seniority_gate("Intermediate Software Engineer", MONTREAL).allowed)
        self.assertTrue(seniority_gate("Mid-Level Backend Engineer", MONTREAL).allowed)

    def test_junior_allows_unknown_title(self):
        self.assertTrue(seniority_gate("Backend Engineer", MONTREAL).allowed)

    def test_junior_blocks_high_years_requirement(self):
        gate = seniority_gate(
            "Backend Engineer",
            MONTREAL,
            description="Requires 7+ years of experience building APIs.",
            candidate_years=2,
        )
        self.assertFalse(gate.allowed)

    def test_senior_profile_allows_staff(self):
        self.assertTrue(seniority_gate("Staff Data Engineer", TORONTO).allowed)

    def test_hard_filter_junior_staff_fails(self):
        result = apply_hard_filters(
            {
                "title": "Staff Software Engineer",
                "location_raw": "Remote, Canada",
                "description": "Staff IC role.",
            },
            MONTREAL,
            {"experience": {"years": 2}},
        )
        self.assertEqual(result.verdict, "FAIL")


class ShortlistNoPaddingTests(unittest.TestCase):
    def test_list_jobs_defaults_to_eligible_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "t.db"
            db = Database(db_path)
            try:
                j_ok, _ = db.upsert_job(
                    RawJob(
                        company="Cohere",
                        title="Software Engineer",
                        location_raw="Remote, Canada",
                        url="https://example.com/a",
                        source="test",
                        ats_provider="test",
                        ats_job_id="a",
                        description="x",
                    )
                )
                j_unc, _ = db.upsert_job(
                    RawJob(
                        company="Figma",
                        title="Software Engineer",
                        location_raw="San Francisco",
                        url="https://example.com/b",
                        source="test",
                        ats_provider="test",
                        ats_job_id="b",
                        description="y",
                    )
                )
                row_ok = db.get_job(j_ok)
                row_unc = db.get_job(j_unc)
                assert row_ok and row_unc
                db._conn.execute("UPDATE jobs SET status='ranked' WHERE id=?", (j_ok,))
                db._conn.execute("UPDATE jobs SET status='ranked' WHERE id=?", (j_unc,))
                db._conn.commit()
                db.save_score(
                    j_ok,
                    overall=90,
                    scores={},
                    hard_filter={"eligibility": "ELIGIBLE", "verdict": "PASS"},
                    strengths=[],
                    gaps=[],
                    salary_alignment="",
                    rejection_reasons=[],
                    evidence=[],
                    model="deterministic/v5",
                    description_hash=row_ok["description_hash"],
                    score_kind="deterministic",
                )
                db.save_score(
                    j_unc,
                    overall=47,
                    scores={},
                    hard_filter={"eligibility": "UNCERTAIN", "verdict": "FLAG"},
                    strengths=[],
                    gaps=[],
                    salary_alignment="",
                    rejection_reasons=[],
                    evidence=[],
                    model="deterministic/v5",
                    description_hash=row_unc["description_hash"],
                    score_kind="deterministic",
                )
                confirmed = db.list_jobs(limit=10, eligibility="ELIGIBLE")
                self.assertEqual(len(confirmed), 1)
                self.assertEqual(confirmed[0]["company"], "Cohere")
                uncertain = db.list_jobs(limit=10, eligibility="UNCERTAIN")
                self.assertEqual(len(uncertain), 1)
                self.assertEqual(uncertain[0]["company"], "Figma")
                counts = db.count_scored_by_eligibility()
                self.assertEqual(counts["ELIGIBLE"], 1)
                self.assertEqual(counts["UNCERTAIN"], 1)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
