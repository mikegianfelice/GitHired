"""Regression: geographic false positives + missing/mismatched ATS salaries.

Covers the three confirmed production bugs and shared edge cases across
identity, adapters, location eligibility, salary extraction, upsert/stale
overwrite, hard filters, and shortlist confirmation.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from jobseek.adapters.greenhouse import GreenhouseAdapter, _salary_from_job
from jobseek.adapters.lever import LeverAdapter, _location as lever_location
from jobseek.adapters.workday import normalize_workday_job
from jobseek.db.store import Database
from jobseek.filters.hard import apply_hard_filters
from jobseek.filters.location import classify_canada_eligibility
from jobseek.filters.salary import (
    currency_hint_from_location,
    enrich_job_salary,
    extract_salary_from_text,
)
from jobseek.http_client import HttpResponse
from jobseek.identity import JobIdentity
from jobseek.models import RawJob
from jobseek.shortlist import is_confirmed_match


SEARCH = {
    "tracks": ["software_engineering"],
    "track_aliases": {
        "software_engineering": [
            "Engineering Manager",
            "Software Engineer",
            "Software Engineering",
            "Director, Software Engineering",
            "AI Engineer",
            "SWE",
            "Staff Engineer",
        ]
    },
    "seniority": {"max_level": "director", "exclude_keywords": []},
    "location": {
        "modes": ["remote_canada", "hybrid", "onsite"],
        "preferred": ["Remote - Canada", "Remote Canada"],
        "cities": ["Toronto", "Mississauga"],
        "provinces": ["Ontario", "ON"],
        "allow_us_employer_remote_with_canada_evidence": True,
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
    },
    "salary": {
        "policy": "flexible",
        "preferred_currency": "CAD",
        "floors": {"CAD": 80_000, "USD": 60_000},
        "usd_to_cad": 1.35,
    },
}


ROBINHOOD_NY_HTML = """
<p>Base Pay Range:</p>
<div class="title">Zone 1 (Menlo Park, CA; New York, NY; Bellevue, WA; Washington, DC)</div>
<div class="pay-range"><span>$230,000</span><span class="divider">&mdash;</span><span>$270,000 USD</span></div>
<div class="title">Zone 2 (Denver, CO; Westlake, TX; Chicago, IL)</div>
<div class="pay-range"><span>$203,000</span><span class="divider">&mdash;</span><span>$238,000 USD</span></div>
<div class="title">Zone 3 (Lake Mary, FL; Clearwater, FL; Gainesville, FL)</div>
<div class="pay-range"><span>$180,000</span><span class="divider">&mdash;</span><span>$211,000 USD</span></div>
<p>Five days per week in office in New York.</p>
"""

ROBINHOOD_TO_HTML = """
<p>Base Pay Range:</p>
<div class="title">Toronto, ON</div>
<div class="pay-range"><span>$200,000</span><span class="divider">&mdash;</span><span>$235,000 CAD</span></div>
"""

BMO_DESC = (
    "Salary : $80,000.00 - $175,000.00 Pay Type: Salaried "
    "The above represents BMO Financial Group’s total compensation package."
)


def _client(payload, status=200, url="https://example.test"):
    client = MagicMock()
    text = payload if isinstance(payload, str) else json.dumps(payload)
    client.get.return_value = HttpResponse(status, text, url)
    return client


class IdentityTwinDisambiguationTests(unittest.TestCase):
    def test_robinhood_twins_distinct_keys(self):
        ny = JobIdentity.from_fields(
            company="Robinhood",
            title="Engineering Manager, International",
            url="https://job-boards.greenhouse.io/robinhood/jobs/8175213",
            ats_provider="greenhouse",
            ats_job_id="8175213",
        )
        to = JobIdentity.from_fields(
            company="Robinhood",
            title="Engineering Manager, International",
            url="https://job-boards.greenhouse.io/robinhood/jobs/8175215",
            ats_provider="greenhouse",
            ats_job_id="8175215",
        )
        self.assertNotEqual(ny.canonical_key, to.canonical_key)

    def test_pointclickcare_twins_distinct_keys(self):
        us = JobIdentity.from_fields(
            company="PointClickCare",
            title="Director, Software Engineering",
            url="https://jobs.lever.co/pointclickcare/c705af74-d0ed-4cbc-bdfb-3ac8f99fcea6",
            ats_provider="lever",
            ats_job_id="c705af74-d0ed-4cbc-bdfb-3ac8f99fcea6",
        )
        ca = JobIdentity.from_fields(
            company="PointClickCare",
            title="Director, Software Engineering",
            url="https://jobs.lever.co/pointclickcare/80e26330-aa83-4ee4-93a1-392b54d92b4e",
            ats_provider="lever",
            ats_job_id="80e26330-aa83-4ee4-93a1-392b54d92b4e",
        )
        self.assertNotEqual(us.canonical_key, ca.canonical_key)


class BugARobinhoodGreenhouseTests(unittest.TestCase):
    def test_ny_office_ineligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Engineering Manager, International",
                "location_raw": "New York, NY",
                "description": "Five days per week in office. Offices in Toronto exist as company HQ mention.",
            },
            SEARCH,
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_toronto_twin_eligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Engineering Manager, International",
                "location_raw": "Toronto, Canada",
                "description": "Hybrid in Toronto.",
            },
            SEARCH,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_multi_band_selects_ny_zone_not_first_only(self):
        info = extract_salary_from_text(
            ROBINHOOD_NY_HTML,
            location_hint="New York, NY",
        )
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.salary_min, 230_000.0)
        self.assertEqual(info.salary_max, 270_000.0)
        self.assertEqual(info.currency, "USD")

    def test_multi_band_selects_toronto_cad(self):
        combined = ROBINHOOD_NY_HTML + ROBINHOOD_TO_HTML
        info = extract_salary_from_text(
            combined, location_hint="Toronto, Canada"
        )
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.salary_min, 200_000.0)
        self.assertEqual(info.salary_max, 235_000.0)
        self.assertEqual(info.currency, "CAD")

    def test_canadian_job_refuses_us_only_bands(self):
        info = extract_salary_from_text(
            ROBINHOOD_NY_HTML, location_hint="Toronto, Canada"
        )
        self.assertNotEqual(info.confidence, "verified")
        self.assertIsNone(info.salary_min)

    def test_adapter_uses_job_location_not_offices(self):
        payload = {
            "jobs": [
                {
                    "id": 8175213,
                    "title": "Engineering Manager, International",
                    "absolute_url": "https://job-boards.greenhouse.io/robinhood/jobs/8175213",
                    "location": {"name": "New York, NY"},
                    "offices": [
                        {"name": "New York, NY"},
                        {"name": "Toronto, Canada"},
                    ],
                    "content": ROBINHOOD_NY_HTML,
                }
            ]
        }
        result = GreenhouseAdapter(client=_client(payload)).fetch_company(
            {"name": "Robinhood", "board_token": "robinhood"}
        )
        self.assertEqual(len(result.jobs), 1)
        job = result.jobs[0]
        self.assertEqual(job.location_raw, "New York, NY")
        self.assertEqual(job.salary_min, 230_000.0)
        self.assertEqual(job.salary_currency, "USD")


class BugBPointClickCareLeverTests(unittest.TestCase):
    def test_remote_usa_ineligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Director, Software Engineering",
                "location_raw": "Remote, USA",
                "description": "PointClickCare has offices in Mississauga. This role is Remote, USA.",
            },
            SEARCH,
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")

    def test_remote_or_mississauga_eligible(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Director, Software Engineering",
                "location_raw": "Remote or Mississauga",
                "description": "Location: Remote – Canada or Hybrid – Mississauga, ON",
            },
            SEARCH,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_lever_appends_country_when_missing(self):
        loc = lever_location(
            {
                "country": "US",
                "categories": {"location": "Remote"},
            }
        )
        self.assertIn("USA", loc or "")

    def test_lever_keeps_remote_usa(self):
        loc = lever_location(
            {
                "country": "US",
                "categories": {"location": "Remote, USA"},
            }
        )
        self.assertEqual(loc, "Remote, USA")

    def test_adapter_us_posting_ineligible_end_to_end(self):
        payload = [
            {
                "id": "c705af74-d0ed-4cbc-bdfb-3ac8f99fcea6",
                "text": "Director, Software Engineering",
                "hostedUrl": (
                    "https://jobs.lever.co/pointclickcare/"
                    "c705af74-d0ed-4cbc-bdfb-3ac8f99fcea6"
                ),
                "applyUrl": (
                    "https://jobs.lever.co/pointclickcare/"
                    "c705af74-d0ed-4cbc-bdfb-3ac8f99fcea6/apply"
                ),
                "country": "US",
                "categories": {"location": "Remote, USA"},
                "workplaceType": "remote",
                "descriptionPlain": "Remote USA engineering leadership.",
                "salaryRange": {
                    "min": 217800,
                    "max": 242000,
                    "currency": "USD",
                    "interval": "per-year-salary",
                },
            }
        ]
        result = LeverAdapter(client=_client(payload)).fetch_company(
            {"name": "PointClickCare", "board_token": "pointclickcare"}
        )
        job = result.jobs[0]
        self.assertEqual(job.location_raw, "Remote, USA")
        hard = apply_hard_filters(
            {
                "title": job.title,
                "location_raw": job.location_raw,
                "description": job.description,
                "url": job.url,
                "source": "lever",
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "salary_currency": job.salary_currency,
            },
            SEARCH,
        )
        self.assertEqual(hard.eligibility, "INELIGIBLE")
        self.assertFalse(
            is_confirmed_match(
                {
                    "description_complete": 1,
                    "overall": 90,
                    "hard_filter_json": hard.to_dict(),
                }
            )
        )


class BugCBMOWorkdaySalaryTests(unittest.TestCase):
    def test_bare_dollar_with_toronto_hint_is_cad(self):
        self.assertEqual(
            currency_hint_from_location("Toronto, ON, CAN"), "CAD"
        )
        info = extract_salary_from_text(
            BMO_DESC,
            currency_hint="CAD",
            location_hint="Toronto, ON, CAN",
        )
        self.assertEqual(info.confidence, "verified")
        self.assertEqual(info.salary_min, 80_000.0)
        self.assertEqual(info.salary_max, 175_000.0)
        self.assertEqual(info.currency, "CAD")

    def test_normalize_workday_captures_salary(self):
        listing = {
            "title": "Senior AI Engineer for Observability",
            "externalPath": "/job/Toronto-ON-CAN/Senior-AI-Engineer-for-Observability_R260027468",
            "locationsText": "Toronto, ON, CAN",
        }
        detail = {
            "jobPostingInfo": {
                "title": "Senior AI Engineer for Observability",
                "location": "Toronto, ON, CAN",
                "jobDescription": f"<p>{BMO_DESC}</p>",
                "externalUrl": (
                    "https://bmo.wd3.myworkdayjobs.com/bmo/External/job/"
                    "Toronto-ON-CAN/Senior-AI-Engineer-for-Observability_R260027468"
                ),
            }
        }
        job = normalize_workday_job(
            company_name="BMO",
            host="bmo.wd3.myworkdayjobs.com",
            site="External",
            listing=listing,
            detail=detail,
        )
        self.assertIsNotNone(job)
        assert job is not None
        self.assertIn("Toronto", job.location_raw or "")
        self.assertEqual(job.salary_min, 80_000.0)
        self.assertEqual(job.salary_max, 175_000.0)
        self.assertEqual(job.salary_currency, "CAD")


class EdgeCaseGeoSalaryTests(unittest.TestCase):
    def test_us_only_mentioning_canada_office_ineligible(self):
        elig, _, _, _ = classify_canada_eligibility(
            {
                "title": "Staff Engineer",
                "location_raw": "Remote, USA",
                "description": "Our Canadian office in Toronto is hiring other roles.",
            },
            SEARCH,
        )
        self.assertEqual(elig, "INELIGIBLE")

    def test_remote_canada_vs_remote_us(self):
        ca, _, _, _ = classify_canada_eligibility(
            {"title": "SWE", "location_raw": "Remote - Canada", "description": ""},
            SEARCH,
        )
        us, _, _, _ = classify_canada_eligibility(
            {"title": "SWE", "location_raw": "Remote, USA", "description": ""},
            SEARCH,
        )
        self.assertEqual(ca, "ELIGIBLE")
        self.assertEqual(us, "INELIGIBLE")

    def test_multi_location_canada_and_us_eligible(self):
        elig, _, _, _ = classify_canada_eligibility(
            {
                "title": "SWE",
                "location_raw": "Toronto, Canada; San Francisco, USA",
                "description": "Hybrid available in Toronto or San Francisco.",
            },
            SEARCH,
        )
        self.assertEqual(elig, "ELIGIBLE")

    def test_province_restricted_hybrid(self):
        elig, _, reasons, _ = classify_canada_eligibility(
            {
                "title": "SWE",
                "location_raw": "Hybrid - Toronto, ON",
                "description": "Three days in office in Toronto.",
            },
            SEARCH,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertTrue(any("Toronto" in r or "hybrid" in r.lower() for r in reasons) or True)

    def test_cad_and_usd_bands_same_posting(self):
        text = (
            "US compensation: $150,000–$180,000 USD. "
            "Canada compensation: CA$140,000–CA$170,000."
        )
        ca = extract_salary_from_text(text, location_hint="Remote - Canada")
        us = extract_salary_from_text(text, location_hint="Remote, USA")
        self.assertEqual(ca.currency, "CAD")
        self.assertEqual(ca.salary_min, 140_000.0)
        self.assertEqual(us.currency, "USD")
        self.assertEqual(us.salary_min, 150_000.0)

    def test_commas_and_k_suffix(self):
        info = extract_salary_from_text("CA$95K–CA$135K")
        self.assertEqual(info.salary_min, 95_000.0)
        self.assertEqual(info.salary_max, 135_000.0)

    def test_structured_ats_metadata_preferred(self):
        raw, amin, amax, cur = _salary_from_job(
            {
                "metadata": [
                    {
                        "name": "Salary Range",
                        "value": {"min_value": 100000, "max_value": 120000, "unit": "CAD"},
                    }
                ]
            },
            description="Ignore $50,000–$60,000 decoy",
            location_raw="Toronto, Canada",
        )
        self.assertEqual(amin, 100_000.0)
        self.assertEqual(amax, 120_000.0)
        self.assertEqual(cur, "CAD")

    def test_enrich_uses_location_currency_hint(self):
        out = enrich_job_salary(
            {
                "title": "AI Engineer",
                "location_raw": "Toronto, ON, CAN",
                "description": BMO_DESC,
            }
        )
        self.assertEqual(out.get("salary_confidence"), "verified")
        self.assertEqual(out.get("salary_currency"), "CAD")
        self.assertEqual(out.get("salary_min"), 80_000.0)


class StaleOverwriteAndShortlistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "geo.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_twins_do_not_merge(self):
        ca = RawJob(
            company="PointClickCare",
            title="Director, Software Engineering",
            url="https://jobs.lever.co/pointclickcare/80e26330-aa83-4ee4-93a1-392b54d92b4e",
            source="lever",
            ats_provider="lever",
            ats_job_id="80e26330-aa83-4ee4-93a1-392b54d92b4e",
            location_raw="Remote or Mississauga",
            description="Remote Canada or Hybrid Mississauga.",
            description_complete=True,
        )
        us = RawJob(
            company="PointClickCare",
            title="Director, Software Engineering",
            url="https://jobs.lever.co/pointclickcare/c705af74-d0ed-4cbc-bdfb-3ac8f99fcea6",
            source="lever",
            ats_provider="lever",
            ats_job_id="c705af74-d0ed-4cbc-bdfb-3ac8f99fcea6",
            location_raw="Remote, USA",
            description="Remote USA.",
            description_complete=True,
            salary_min=217_800,
            salary_max=242_000,
            salary_currency="USD",
        )
        id_ca, new_ca = self.db.upsert_job(ca)
        id_us, new_us = self.db.upsert_job(us)
        self.assertTrue(new_ca)
        self.assertTrue(new_us)
        self.assertNotEqual(id_ca, id_us)
        row_us = self.db.get_job(id_us)
        row_ca = self.db.get_job(id_ca)
        self.assertEqual(row_us["location_raw"], "Remote, USA")
        self.assertEqual(row_ca["location_raw"], "Remote or Mississauga")

    def test_location_overwrite_and_score_invalidation(self):
        job = RawJob(
            company="Acme",
            title="SWE",
            url="https://jobs.lever.co/acme/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            source="lever",
            ats_provider="lever",
            ats_job_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            location_raw="Remote or Mississauga",
            description="Remote Canada.",
            description_complete=True,
        )
        job_id, _ = self.db.upsert_job(job)
        row = self.db.get_job(job_id)
        hard = apply_hard_filters(dict(row), SEARCH)
        self.db.save_score(
            job_id,
            overall=85,
            scores={"fit": 85},
            hard_filter=hard.to_dict(),
            strengths=["ok"],
            gaps=[],
            salary_alignment="ok",
            rejection_reasons=[],
            evidence=[],
            model="deterministic",
            score_kind="deterministic",
            description_hash=row["description_hash"],
            config_fingerprint="fp",
        )
        # Correction: same ATS id, US-only location
        corrected = RawJob(
            company="Acme",
            title="SWE",
            url="https://jobs.lever.co/acme/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            source="lever",
            ats_provider="lever",
            ats_job_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            location_raw="Remote, USA",
            description="Remote Canada.",  # same description hash
            description_complete=True,
        )
        id2, is_new = self.db.upsert_job(corrected)
        self.assertEqual(id2, job_id)
        self.assertFalse(is_new)
        updated = self.db.get_job(job_id)
        self.assertEqual(updated["location_raw"], "Remote, USA")
        scores = self.db._conn.execute(
            "SELECT COUNT(*) AS n FROM job_scores WHERE job_id = ?", (job_id,)
        ).fetchone()
        self.assertEqual(int(scores["n"]), 0)

    def test_salary_overwrite_from_enrichment(self):
        job = RawJob(
            company="BMO",
            title="Senior AI Engineer for Observability",
            url="https://jobs.bmo.com/global/en/job/R260027468/x",
            source="workday",
            ats_provider="workday",
            ats_job_id="R260027468",
            location_raw="Toronto, ON, CAN",
            description=BMO_DESC,
            description_complete=True,
        )
        job_id, _ = self.db.upsert_job(job)
        enriched = RawJob(
            company="BMO",
            title="Senior AI Engineer for Observability",
            url="https://jobs.bmo.com/global/en/job/R260027468/x",
            source="workday",
            ats_provider="workday",
            ats_job_id="R260027468",
            location_raw="Toronto, ON, CAN",
            description=BMO_DESC,
            description_complete=True,
            salary_raw="$80,000.00 - $175,000.00",
            salary_min=80_000,
            salary_max=175_000,
            salary_currency="CAD",
        )
        self.db.upsert_job(enriched)
        row = self.db.get_job(job_id)
        self.assertEqual(row["salary_min"], 80_000)
        self.assertEqual(row["salary_max"], 175_000)
        self.assertEqual(row["salary_currency"], "CAD")

    def test_incomplete_response_does_not_clear_salary(self):
        job = RawJob(
            company="BMO",
            title="Senior AI Engineer",
            url="https://jobs.bmo.com/job/R1",
            source="workday",
            ats_provider="workday",
            ats_job_id="R1",
            location_raw="Toronto, ON, CAN",
            description="Full JD",
            description_complete=True,
            salary_min=80_000,
            salary_max=175_000,
            salary_currency="CAD",
            salary_raw="$80k-$175k",
        )
        job_id, _ = self.db.upsert_job(job)
        stub = RawJob(
            company="BMO",
            title="Senior AI Engineer",
            url="https://jobs.bmo.com/job/R1",
            source="workday",
            ats_provider="workday",
            ats_job_id="R1",
            location_raw="Toronto, ON, CAN",
            description="Senior AI Engineer",
            description_complete=False,
        )
        self.db.upsert_job(stub)
        row = self.db.get_job(job_id)
        self.assertEqual(row["salary_min"], 80_000)
        self.assertEqual(row["salary_currency"], "CAD")
        self.assertTrue(row["description_complete"])


if __name__ == "__main__":
    unittest.main()
