"""Regression: 50-board expansion merged into companies.yaml without dups."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPANIES = ROOT / "config" / "companies.yaml"

# Snapshot of names from the 2026-11-03 expansion file (not invented).
EXPANSION_NAMES = {
    "Tailscale",
    "Northbeam",
    "AlphaSense",
    "Grafana Labs",
    "Cockroach Labs",
    "Fivetran",
    "PlanetScale",
    "Tenstorrent",
    "Vercel",
    "Vanta",
    "Ashby",
    "FutureFit AI",
    "Blackpoint Cyber",
    "Wrapbook",
    "Nango",
    "Camunda",
    "Reflow",
    "Kraken",
    "Owner.com",
    "Redis",
    "Relay",
    "Float",
    "Baseten",
    "Modal",
    "Merge",
    "Apply Digital",
    "Arc'teryx",
    "Air-tek",
    "Fullscript",
    "Lazer",
    "Acquird",
    "Render",
    "Sierra",
    "Perplexity",
    "Harvey",
    "Oyster",
    "7shifts",
    "ClickHouse",
    "Docker",
    "Temporal",
    "Sentry",
    "PostHog",
    "Supabase",
    "Linear",
    "Blockstream",
    "Astronomer",
    "Writer",
    "Replit",
    "HackerOne",
    "Maple",
}


def _norm(name: str) -> str:
    return "".join(c for c in name.casefold() if c.isalnum())


class Companies50ExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = yaml.safe_load(COMPANIES.read_text())
        cls.companies = data["companies"]

    def test_all_expansion_names_present(self):
        names = {c["name"] for c in self.companies}
        missing = EXPANSION_NAMES - names
        self.assertFalse(missing, f"missing expansion companies: {sorted(missing)}")

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

    def test_disabled_boards_without_canada_evidence_stay_disabled(self):
        # Live validation left these disabled (no structured Canadian locations).
        must_disable = {
            "Vercel",
            "Cockroach Labs",
            "PlanetScale",
            "PostHog",
            "Supabase",
            "Nango",
            "Perplexity",
            "Modal",
        }
        by_name = {c["name"]: c for c in self.companies}
        for name in must_disable:
            self.assertFalse(
                by_name[name].get("enabled"),
                f"{name} should remain disabled without Canadian location evidence",
            )

    def test_canada_evidenced_boards_enabled(self):
        must_enable = {"Tailscale", "Tenstorrent", "Fullscript", "Grafana Labs", "7shifts"}
        by_name = {c["name"]: c for c in self.companies}
        for name in must_enable:
            self.assertTrue(by_name[name].get("enabled"), f"{name} should be enabled")

    def test_single_companies_root(self):
        text = COMPANIES.read_text()
        self.assertEqual(text.count("\ncompanies:\n") + (1 if text.startswith("companies:\n") else 0), 1)


if __name__ == "__main__":
    unittest.main()
