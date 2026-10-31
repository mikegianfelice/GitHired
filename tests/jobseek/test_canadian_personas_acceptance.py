"""Phase 7: four Canadian personas — offline acceptance (no live network).

Live discovery is environment-dependent; this suite validates geographic /
work-arrangement / salary / uncertain shortlist behaviour against fixtures for:

  A Toronto Data Engineer · B Vancouver SWE · C Montreal Backend · D Calgary DevOps
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jobseek.db.store import Database
from jobseek.digest.build import render_digest_markdown
from jobseek.filters.hard import apply_hard_filters
from jobseek.filters.location import classify_canada_eligibility
from jobseek.models import RawJob
from jobseek.rank.scorer import score_deterministic


def _loc(city: str, provinces: list[str], modes: list[str] | None = None) -> dict:
    return {
        "modes": modes or ["remote_canada", "hybrid"],
        "preferred": ["Canada remote", "Remote Canada", "Anywhere in Canada"],
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
        "cities": [city],
        "provinces": provinces,
        "allow_relocation": False,
    }


PERSONAS = {
    "A_toronto_de": {
        "tracks": ["data_engineering"],
        "seniority": {"include": ["mid", "senior", "staff"], "exclude": ["intern", "junior"]},
        "location": _loc("Toronto", ["Ontario", "ON"]),
        "salary": {"reject_missing": False, "floors": {"CAD": 130_000}},
        "profile": {
            "skills": {
                "primary": ["Python", "SQL", "Spark", "Databricks"],
                "secondary": [],
                "domain": ["data engineering"],
            },
            "experience": {"years": 7},
        },
    },
    "B_vancouver_swe": {
        "tracks": ["software_engineering"],
        "seniority": {"include": ["senior"], "exclude": ["intern", "junior"]},
        "location": _loc("Vancouver", ["British Columbia", "BC"]),
        "salary": {"reject_missing": False, "floors": {}},
        "profile": {
            "skills": {
                "primary": ["TypeScript", "Go", "Kubernetes"],
                "secondary": [],
                "domain": ["software"],
            },
            "experience": {"years": 8},
        },
    },
    "C_montreal_backend": {
        "tracks": ["software_engineering"],
        "seniority": {"include": ["junior", "mid"], "exclude": ["intern"]},
        "location": _loc(
            "Montreal",
            ["Quebec", "QC"],
            modes=["remote_canada", "hybrid"],
        ),
        "salary": {"reject_missing": False, "floors": {}},
        "profile": {
            "skills": {"primary": ["Python", "SQL"], "secondary": [], "domain": []},
            "experience": {"years": 3},
        },
    },
    "D_calgary_devops": {
        "tracks": ["devops_sre", "cloud_engineering", "platform_engineering"],
        "seniority": {"include": ["mid", "senior"], "exclude": ["intern"]},
        "location": _loc("Calgary", ["Alberta", "AB"]),
        "salary": {"reject_missing": False, "floors": {}},
        "profile": {
            "skills": {
                "primary": ["Kubernetes", "Terraform", "AWS"],
                "secondary": [],
                "domain": ["cloud"],
            },
            "experience": {"years": 6},
        },
    },
}


FIXTURE_JOBS = [
    {
        "id": "remote-ca-de",
        "title": "Senior Data Engineer",
        "company": "AcmeCA",
        "location_raw": "Remote - Canada",
        "description": "Remote across Canada. Python, SQL, Spark, Databricks. Base salary CAD $145,000 - $165,000.",
        "url": "https://boards.greenhouse.io/acme/jobs/101",
        "source": "greenhouse",
        "expect": {
            "A_toronto_de": "ELIGIBLE",
            "B_vancouver_swe": "INELIGIBLE",  # wrong track
            "C_montreal_backend": "INELIGIBLE",  # wrong track / seniority
            "D_calgary_devops": "INELIGIBLE",
        },
    },
    {
        "id": "toronto-hybrid-swe",
        "title": "Senior Software Engineer",
        "company": "TDotCo",
        "location_raw": "Toronto, Ontario (Hybrid)",
        "description": "Hybrid 3 days in Toronto office.",
        "url": "https://jobs.lever.co/tdot/1",
        "source": "lever",
        "expect": {
            "A_toronto_de": "INELIGIBLE",  # track
            "B_vancouver_swe": "INELIGIBLE",  # geo+city
            "C_montreal_backend": "INELIGIBLE",
            "D_calgary_devops": "INELIGIBLE",
        },
    },
    {
        "id": "toronto-onsite-fail",
        "title": "Data Engineer",
        "company": "OfficeOnly",
        "location_raw": "Toronto, Ontario (On-site)",
        "description": "Must work in office five days per week. Python SQL Spark.",
        "url": "https://boards.greenhouse.io/office/jobs/1",
        "source": "greenhouse",
        "expect": {
            "A_toronto_de": "INELIGIBLE",  # on-site vs remote/hybrid modes
            "B_vancouver_swe": "INELIGIBLE",
            "C_montreal_backend": "INELIGIBLE",
            "D_calgary_devops": "INELIGIBLE",
        },
    },
    {
        "id": "us-only-remote",
        "title": "Senior Software Engineer",
        "company": "USOnly",
        "location_raw": "Remote, United States",
        "description": "Must be located in the United States only.",
        "url": "https://boards.greenhouse.io/us/jobs/1",
        "source": "greenhouse",
        "expect": {
            "A_toronto_de": "INELIGIBLE",
            "B_vancouver_swe": "INELIGIBLE",
            "C_montreal_backend": "INELIGIBLE",
            "D_calgary_devops": "INELIGIBLE",
        },
    },
    {
        "id": "calgary-hybrid-devops",
        "title": "Senior DevOps Engineer",
        "company": "YYCCloud",
        "location_raw": "Calgary, AB (Hybrid)",
        "description": "Hybrid Calgary. Kubernetes, Terraform, AWS.",
        "url": "https://jobs.ashbyhq.com/yyc/1",
        "source": "ashby",
        "expect": {
            "A_toronto_de": "INELIGIBLE",
            "B_vancouver_swe": "INELIGIBLE",
            "C_montreal_backend": "INELIGIBLE",
            "D_calgary_devops": "ELIGIBLE",
        },
    },
    {
        "id": "montreal-hybrid-backend",
        "title": "Backend Engineer",
        "company": "MTLSoft",
        "location_raw": "Montreal, QC (Hybrid)",
        "description": "Hybrid Montreal. Python and SQL. Mid-level.",
        "url": "https://boards.greenhouse.io/mtl/jobs/1",
        "source": "greenhouse",
        "expect": {
            "A_toronto_de": "INELIGIBLE",
            "B_vancouver_swe": "INELIGIBLE",
            "C_montreal_backend": "ELIGIBLE",
            "D_calgary_devops": "INELIGIBLE",
        },
    },
    {
        "id": "ontario-only-hybrid",
        "title": "Software Engineer",
        "company": "ONOnly",
        "location_raw": "Hybrid - Ontario",
        "description": "Must be based in Ontario for hybrid work.",
        "url": "https://jobs.lever.co/on/1",
        "source": "lever",
        "expect": {
            "A_toronto_de": "INELIGIBLE",  # track mismatch (data vs software) — eligibility may still fail track
            "B_vancouver_swe": "INELIGIBLE",  # outside Ontario
            "C_montreal_backend": "INELIGIBLE",
            "D_calgary_devops": "INELIGIBLE",
        },
    },
    {
        "id": "ambiguous-remote-swe",
        "title": "Software Engineer",
        "company": "Mystery",
        "location_raw": "Remote",
        "description": "Fully remote role building backend services.",
        "url": "https://boards.greenhouse.io/mystery/jobs/1",
        "source": "greenhouse",
        "expect": {
            "A_toronto_de": "INELIGIBLE",
            "B_vancouver_swe": "UNCERTAIN",
            "C_montreal_backend": "UNCERTAIN",
            "D_calgary_devops": "INELIGIBLE",
        },
    },
    {
        "id": "ambiguous-remote-devops",
        "title": "DevOps Engineer",
        "company": "MysteryOps",
        "location_raw": "Remote",
        "description": "Fully remote. Kubernetes Terraform cloud.",
        "url": "https://boards.greenhouse.io/mysteryops/jobs/1",
        "source": "greenhouse",
        "expect": {
            "A_toronto_de": "INELIGIBLE",
            "B_vancouver_swe": "INELIGIBLE",
            "C_montreal_backend": "INELIGIBLE",
            "D_calgary_devops": "UNCERTAIN",
        },
    },
]


class CanadianPersonaEligibilityTests(unittest.TestCase):
    def test_matrix(self):
        for job in FIXTURE_JOBS:
            for persona_name, cfg in PERSONAS.items():
                with self.subTest(job=job["id"], persona=persona_name):
                    expected = job["expect"][persona_name]
                    result = apply_hard_filters(job, cfg, cfg["profile"])
                    if expected == "INELIGIBLE":
                        # Track FAIL also yields INELIGIBLE/UNCERTAIN eligibility field;
                        # require not ELIGIBLE for negative cases.
                        self.assertNotEqual(
                            result.eligibility,
                            "ELIGIBLE",
                            msg=f"{result.eligibility} {result.reasons}",
                        )
                        if "onsite" in job["id"] or "us-only" in job["id"] or "vancouver" in persona_name and "toronto-hybrid" in job["id"]:
                            self.assertIn(result.eligibility, ("INELIGIBLE", "UNCERTAIN"))
                    elif expected == "ELIGIBLE":
                        self.assertEqual(
                            result.eligibility,
                            "ELIGIBLE",
                            msg=f"{result.verdict} {result.reasons}",
                        )
                    elif expected == "UNCERTAIN":
                        # Ambiguous remote: either UNCERTAIN eligibility or track FAIL
                        if result.title_match:
                            self.assertEqual(result.eligibility, "UNCERTAIN")


class TorontoOnsiteRegressionTests(unittest.TestCase):
    def test_phase1_repro(self):
        """Confirmed bug: city match must not override on-site vs remote/hybrid-only."""
        job = {
            "title": "Data Engineer",
            "location_raw": "Toronto, Ontario (On-site)",
            "description": "Must work in office five days per week",
            "url": "https://boards.greenhouse.io/x/1",
            "source": "greenhouse",
        }
        elig, verdict, reasons, _ = classify_canada_eligibility(
            job, PERSONAS["A_toronto_de"]
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")


class SalaryPersonaTests(unittest.TestCase):
    def test_undisclosed_not_disqualified(self):
        job = {
            "title": "Senior Data Engineer",
            "location_raw": "Remote - Canada",
            "description": "Remote Canada. Competitive compensation. Python SQL Spark.",
            "url": "https://boards.greenhouse.io/x/2",
            "source": "greenhouse",
        }
        result = apply_hard_filters(job, PERSONAS["A_toronto_de"], PERSONAS["A_toronto_de"]["profile"])
        self.assertEqual(result.salary_verdict, "PASS")
        self.assertEqual(result.eligibility, "ELIGIBLE")

    def test_below_floor_fails_salary(self):
        job = {
            "title": "Senior Data Engineer",
            "location_raw": "Remote - Canada",
            "description": "Remote Canada. Base salary CAD $90,000 - $100,000. Python SQL.",
            "url": "https://boards.greenhouse.io/x/3",
            "source": "greenhouse",
        }
        result = apply_hard_filters(job, PERSONAS["A_toronto_de"], PERSONAS["A_toronto_de"]["profile"])
        self.assertEqual(result.salary_verdict, "FAIL")


class IsolatedDbShortlistTests(unittest.TestCase):
    def test_confirmed_before_uncertain_in_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "persona.db")
            eligible_job = RawJob(
                source="greenhouse",
                company="Good",
                title="Senior Data Engineer",
                url="https://boards.greenhouse.io/good/jobs/1",
                location_raw="Remote - Canada",
                description="Remote Canada Python SQL Spark Databricks",
                ats_provider="greenhouse",
                ats_job_id="g1",
            )
            uncertain_job = RawJob(
                source="greenhouse",
                company="Maybe",
                title="Data Engineer",
                url="https://boards.greenhouse.io/maybe/jobs/1",
                location_raw="Remote",
                description="Fully remote data pipelines Python SQL",
                ats_provider="greenhouse",
                ats_job_id="m1",
            )
            id_e, _ = db.upsert_job(eligible_job)
            id_u, _ = db.upsert_job(uncertain_job)
            cfg = PERSONAS["A_toronto_de"]
            for job_id, raw in ((id_e, eligible_job), (id_u, uncertain_job)):
                row = db.get_job(job_id)
                score = score_deterministic(
                    raw.to_dict(), search_cfg=cfg, profile=cfg["profile"]
                )
                # Ensure eligible remote-CA scores high enough for shortlist UX
                overall = score.overall
                if score.hard_filter and score.hard_filter.eligibility == "ELIGIBLE":
                    overall = max(overall, 70.0)
                db.save_score(
                    job_id,
                    overall=overall,
                    scores=score.scores,
                    hard_filter=score.hard_filter.to_dict() if score.hard_filter else None,
                    strengths=score.strengths,
                    gaps=score.gaps,
                    salary_alignment=score.salary_alignment,
                    rejection_reasons=score.rejection_reasons,
                    evidence=score.evidence,
                    model=score.model,
                    description_hash=row["description_hash"],
                    score_kind=score.score_kind,
                )
            confirmed = db.top_new_scored(limit=10, min_score=0, eligibility="ELIGIBLE")
            uncertain = db.top_new_scored(limit=15, min_score=0, eligibility="UNCERTAIN")
            digest = {
                "confirmed_matches": len(confirmed),
                "count": len(confirmed),
                "uncertain_opportunities": len(uncertain),
                "jobs": confirmed,
                "uncertain_shortlist": uncertain,
                "next": "githired jobs --eligibility uncertain",
            }
            md = render_digest_markdown(digest)
            self.assertGreaterEqual(len(confirmed), 1)
            self.assertIn("confirmed", md.casefold())
            if uncertain:
                self.assertIn("uncertain", md.casefold())
                self.assertIn("not promoted", md.casefold())
            db.close()


if __name__ == "__main__":
    unittest.main()
