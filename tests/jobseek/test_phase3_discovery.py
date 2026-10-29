"""Phase 3: expanded Canadian registry + careers seed discovery."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from jobseek.companies.providers.builtin_seed import collect_builtin_candidates
from jobseek.companies.providers.careers_seed import collect_careers_seed_candidates
from jobseek.companies.registry import load_community_companies, validate_community_shape
from jobseek.paths import ROOT


class CommunityRegistryPhase3Tests(unittest.TestCase):
    def test_community_registry_shape_and_tokens(self):
        path = ROOT / "registry" / "community" / "companies.v1.yaml"
        self.assertTrue(path.is_file())
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        companies = data.get("companies") or []
        errors = validate_community_shape(companies)
        self.assertEqual(errors, [], errors)
        self.assertGreaterEqual(len(companies), 40)
        for row in companies:
            self.assertTrue(row.get("name"))
            self.assertTrue(row.get("ats"))
            self.assertTrue(row.get("board_token"), msg=row.get("name"))
            # Never ship invented-looking empty tokens
            self.assertNotEqual(str(row.get("board_token")).strip(), "")

    def test_community_includes_canadian_priority_employers(self):
        names = {c["name"].casefold() for c in load_community_companies()}
        for required in (
            "wealthsimple",
            "1password",
            "jobber",
            "geotab",
            "waabi",
            "neo financial",
            "benevity",
            "stackadapt",
        ):
            self.assertIn(required, names)

    def test_builtin_seed_enables_validated_community(self):
        rows = collect_builtin_candidates(include_community=True)
        community = [r for r in rows if r.discovery_source == "community"]
        self.assertTrue(community)
        enabled = [r for r in community if r.as_company_dict().get("enabled")]
        self.assertGreaterEqual(len(enabled), 20)


class CareersSeedTests(unittest.TestCase):
    def test_skips_domains_already_present(self):
        existing = [
            {
                "name": "Shopify",
                "domain": "shopify.com",
                "careers_url": "https://www.shopify.com/careers",
                "ats": "rss",
                "board_token": "https://www.shopify.com/careers/feed.xml",
            }
        ]
        seeds = collect_careers_seed_candidates(existing)
        names = {s.name.casefold() for s in seeds}
        self.assertNotIn("shopify", names)
        self.assertTrue(any(s.name == "Clio" for s in seeds))

    def test_seeds_have_no_invented_tokens(self):
        for s in collect_careers_seed_candidates([]):
            self.assertIsNone(s.board_token)
            self.assertEqual(s.ats, "unknown")


class BuiltinCompaniesExpandedTests(unittest.TestCase):
    def test_defaults_companies_expanded(self):
        path = ROOT / "jobseek" / "data" / "defaults" / "companies.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        companies = data.get("companies") or []
        enabled = [c for c in companies if c.get("enabled", True)]
        self.assertGreaterEqual(len(enabled), 50)
        names = {c["name"].casefold() for c in enabled}
        self.assertIn("wealthsimple", names)
        self.assertIn("databricks", names)
        self.assertIn("geotab", names)


if __name__ == "__main__":
    unittest.main()
