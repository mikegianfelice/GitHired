"""Regression: 2026-11-15 employer expansion merged without dups."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPANIES = ROOT / "config" / "companies.yaml"

# Employers enabled after live Canada+tech validation (not the full 73 CSV).
EXPANSION_NAMES = {
    "Aduna Global",
    "AltaML",
    "Badge",
    "Boson AI",
    "Canadian Tire",
    "Canals",
    "Desjardins",
    "Fellow",
    "Fig Financial",
    "H2 Analytics",
    "Hive.co",
    "Jane App",
    "Kong",
    "Leadership Connect",
    "NerdWallet",
    "Novara",
    "Parallel Domain",
    "RAVL",
    "ShyftLabs",
    "SOVRA",
    "Super.com",
    "Superhuman",
    "Terminal",
    "Wagmo",
    "Warner Music Group",
    "Xsolla",
}


def _norm(name: str) -> str:
    return "".join(c for c in name.casefold() if c.isalnum())


class CompaniesExpansion20261115Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = yaml.safe_load(COMPANIES.read_text())
        cls.companies = data["companies"]

    def test_all_expansion_names_present_and_enabled(self):
        by_name = {c["name"]: c for c in self.companies}
        missing = EXPANSION_NAMES - set(by_name)
        self.assertFalse(missing, f"missing expansion companies: {sorted(missing)}")
        for name in EXPANSION_NAMES:
            self.assertTrue(by_name[name].get("enabled"), f"{name} should be enabled")

    def test_no_duplicate_names_or_ats_tokens(self):
        names = [_norm(c["name"]) for c in self.companies]
        self.assertEqual(len(names), len(set(names)))
        ats_keys = [
            (str(c.get("ats") or "").casefold(), str(c.get("board_token") or "").casefold().strip())
            for c in self.companies
            if c.get("board_token")
        ]
        self.assertEqual(len(ats_keys), len(set(ats_keys)))

    def test_alphabetically_sorted(self):
        names = [c["name"] for c in self.companies]
        self.assertEqual(names, sorted(names, key=lambda n: n.casefold()))

    def test_workday_boards_have_host_tenant_site(self):
        for name in ("Desjardins", "Canadian Tire"):
            c = next(x for x in self.companies if x["name"] == name)
            self.assertEqual(c.get("ats"), "workday")
            self.assertTrue(c.get("workday_host"))
            self.assertTrue(c.get("workday_tenant"))
            self.assertTrue(c.get("workday_site"))
            self.assertIn(c["workday_site"], c["board_token"])


if __name__ == "__main__":
    unittest.main()
