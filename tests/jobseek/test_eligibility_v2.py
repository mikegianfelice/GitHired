"""Regression tests for Canada eligibility (UAT P0 fixes)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from jobseek.filters.hard import apply_hard_filters, classify_canada_eligibility
from jobseek.filters.location import find_province_in_location, normalize_province_list
from jobseek.setup_wizard import dump_search_yaml, validate_search_config

SEARCH = {
    "tracks": ["data_engineering", "platform_engineering", "devops_sre"],
    "location": {
        "modes": ["remote_canada", "remote_province", "hybrid", "onsite"],
        "preferred": ["Canada remote", "Remote Canada"],
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
        "cities": [
            "Toronto",
            "Ottawa",
            "Vancouver",
            "Montreal",
            "Waterloo",
            "Calgary",
        ],
        "provinces": ["Ontario", "ON", "British Columbia", "BC", "Quebec", "QC", "Alberta", "AB"],
    },
    "salary": {"reject_missing": False, "floors": {"CAD": 130000, "USD": 90000}},
}


class ProvinceCodeTests(unittest.TestCase):
    def test_english_on_not_ontario(self):
        loc = "London, UK"
        desc = (
            "As an Infrastructure Engineer on the Apps Platform you will work on "
            "on-premises deployments and on-call rotations."
        )
        elig, verdict, reasons, _ = classify_canada_eligibility(
            {
                "title": "Senior Infrastructure Software Engineer, Apps Platform",
                "location_raw": loc,
                "description": desc,
                "url": "https://job-boards.greenhouse.io/scaleai/jobs/4729979005",
            },
            SEARCH,
        )
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")
        self.assertFalse(any("province" in r.casefold() and "on" == r.casefold() for r in reasons))
        self.assertIsNone(find_province_in_location(desc))

    def test_toronto_on_in_location_field(self):
        self.assertEqual(find_province_in_location("Toronto, ON"), "Ontario")
        self.assertEqual(find_province_in_location("Hybrid - Ottawa, ON, Canada"), "Ontario")
        elig, verdict, _, evidence = classify_canada_eligibility(
            {
                "title": "Senior Data Engineer",
                "location_raw": "Toronto, ON",
                "description": "Build pipelines.",
            },
            SEARCH,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")
        self.assertTrue(any("Ontario" in e or "Toronto" in e for e in evidence))

    def test_yaml_on_boolean_footgun_normalized(self):
        # Simulate PyYAML parsing unquoted ON → True
        self.assertEqual(normalize_province_list([True, "QC"]), ["ON", "QC"])
        raw = "location:\n  provinces:\n    - ON\n    - QC\n"
        # When dumped via wizard, ON stays a string
        data = {"location": {"provinces": ["ON", "QC"], "modes": ["remote_canada"]}}
        text = dump_search_yaml(data)
        parsed = yaml.safe_load(text)
        self.assertEqual(parsed["location"]["provinces"], ["ON", "QC"])
        self.assertNotIsInstance(parsed["location"]["provinces"][0], bool)


class UatFalsePositiveTests(unittest.TestCase):
    def test_scale_ai_london_4729979005(self):
        job = {
            "title": "Senior Infrastructure Software Engineer, Apps Platform",
            "location_raw": "London, UK",
            "description": (
                "Senior Infrastructure Software Engineer, Apps Platform, London. "
                "As an Infrastructure Engineer on the Apps Platform Infrastructure team, "
                "you'll help build deployments across on-premises environments."
            ),
            "url": "https://job-boards.greenhouse.io/scaleai/jobs/4729979005",
        }
        elig, _, _, _ = classify_canada_eligibility(job, SEARCH)
        self.assertEqual(elig, "INELIGIBLE")

    def test_mongodb_gurugram_not_eligible_via_offices_worldwide(self):
        job = {
            "title": "Lead, Platform Engineering",
            "location_raw": "Gurugram",
            "description": (
                "With offices worldwide we are hiring platform leaders. "
                "Take on direct reports and organize work on a distributed team."
            ),
        }
        elig, verdict, reasons, _ = classify_canada_eligibility(job, SEARCH)
        self.assertEqual(elig, "INELIGIBLE")
        self.assertEqual(verdict, "FAIL")
        # offices worldwide alone must never become ELIGIBLE
        job_remoteish = {
            "title": "Platform Engineer",
            "location_raw": "Remote",
            "description": "Our company has offices worldwide and a global presence.",
        }
        elig2, _, reasons2, _ = classify_canada_eligibility(job_remoteish, SEARCH)
        self.assertNotEqual(elig2, "ELIGIBLE")
        self.assertTrue(any("worldwide" in r.casefold() for r in reasons2))

    def test_genuine_worldwide_remote_still_eligible(self):
        job = {
            "title": "Data Engineer",
            "location_raw": "Remote",
            "description": "Work from anywhere. Worldwide remote OK.",
        }
        elig, verdict, _, _ = classify_canada_eligibility(job, SEARCH)
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")

    def test_us_location_not_eligible_via_wfa_copy(self):
        job = {
            "title": "Data Platform Engineer",
            "location_raw": "San Francisco, CA • New York, NY • United States",
            "description": "Hire from anywhere in the world. Build data platforms.",
        }
        elig, verdict, _, _ = classify_canada_eligibility(job, SEARCH)
        self.assertNotEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "FLAG")

    def test_us_only_stripe_style(self):
        job = {
            "title": "Staff Data Engineer",
            "location_raw": "San Francisco, Seattle",
            "description": "Must be located in the United States only. Build data pipelines.",
        }
        result = apply_hard_filters(job, SEARCH)
        self.assertEqual(result.eligibility, "INELIGIBLE")
        self.assertEqual(result.verdict, "FAIL")

    def test_stripe_toronto_data_engineering(self):
        job = {
            "title": "Staff Software Engineer, Risk Data Engineering",
            "location_raw": "Toronto",
            "description": (
                "Product and Risk Data Engineering. Airflow, Spark, Kafka. "
                "Office locations: Toronto, Seattle, South San Francisco HQ."
            ),
        }
        # Title must match data engineering track
        result = apply_hard_filters(job, SEARCH)
        self.assertTrue(result.title_match)
        self.assertEqual(result.eligibility, "ELIGIBLE")
        self.assertIn(result.verdict, ("PASS", "FLAG"))

    def test_cohere_toronto_data_engineer(self):
        job = {
            "title": "Senior Staff Data Engineer",
            "location_raw": "Toronto (Remote)",
            "description": (
                "Other locations: San Francisco, Canada, United States. "
                "Airflow, dbt, BigQuery. Headquartered in Toronto."
            ),
        }
        result = apply_hard_filters(job, SEARCH)
        self.assertTrue(result.title_match)
        self.assertEqual(result.eligibility, "ELIGIBLE")


class CanadianCityCases(unittest.TestCase):
    def test_major_cities(self):
        for city in ("Toronto", "Ottawa", "Vancouver", "Montreal", "Waterloo", "Calgary"):
            elig, verdict, _, evidence = classify_canada_eligibility(
                {
                    "title": "Data Engineer",
                    "location_raw": f"Hybrid - {city}",
                    "description": "Hybrid role.",
                },
                SEARCH,
            )
            self.assertEqual(elig, "ELIGIBLE", city)
            self.assertEqual(verdict, "PASS", city)
            self.assertTrue(evidence, city)

    def test_remote_canada(self):
        elig, verdict, _, _ = classify_canada_eligibility(
            {
                "title": "Data Engineer",
                "location_raw": "Remote - Canada",
                "description": "Fully remote within Canada.",
            },
            SEARCH,
        )
        self.assertEqual(elig, "ELIGIBLE")
        self.assertEqual(verdict, "PASS")


class DoctorValidationTests(unittest.TestCase):
    def test_invalid_salary_detected(self):
        issues = validate_search_config(
            {
                "tracks": ["data_engineering"],
                "location": {"modes": ["remote_canada"], "provinces": ["Ontario"]},
                "salary": {"floors": {"CAD": "not-a-number"}},
            }
        )
        self.assertTrue(any("floors.CAD" in i for i in issues))

    def test_boolean_province_detected(self):
        issues = validate_search_config(
            {
                "tracks": ["data_engineering"],
                "location": {"modes": ["remote_canada"], "provinces": [True]},
                "salary": {"floors": {"CAD": 120000}},
            }
        )
        self.assertTrue(any("boolean" in i.casefold() for i in issues))


class SetupYamlRoundTrip(unittest.TestCase):
    def test_write_on_stays_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "search.yaml"
            path.write_text(
                dump_search_yaml(
                    {
                        "tracks": ["data_engineering"],
                        "location": {"provinces": ["ON"], "cities": ["Toronto"], "modes": ["remote_canada"]},
                        "salary": {"floors": {"CAD": 130000}},
                    }
                ),
                encoding="utf-8",
            )
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["location"]["provinces"], ["ON"])
            self.assertIsInstance(loaded["location"]["provinces"][0], str)


if __name__ == "__main__":
    unittest.main()
