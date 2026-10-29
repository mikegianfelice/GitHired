"""Seed Canadian careers URLs for ATS auto-detection when search indexes fail.

These rows intentionally omit board tokens. ``career_page`` detection must
recover a real token from the live careers page before a board is enabled —
tokens are never invented here.
"""

from __future__ import annotations

from typing import Any

from jobseek.companies.domain_util import canonical_domain
from jobseek.companies.providers.base import CompanyCandidate

# Careers pages for Canadian / Canada-hiring employers where public ATS may
# appear in HTML. Keep this list conservative; detection validates ownership.
_CANADIAN_CAREERS_SEEDS: list[dict[str, str]] = [
    {"name": "Clio", "careers_url": "https://www.clio.com/about/careers/", "domain": "clio.com"},
    {"name": "Ada", "careers_url": "https://www.ada.cx/careers", "domain": "ada.cx"},
    {"name": "Coveo", "careers_url": "https://www.coveo.com/en/company/careers", "domain": "coveo.com"},
    {"name": "SSENSE", "careers_url": "https://www.ssense.com/en-ca/careers", "domain": "ssense.com"},
    {"name": "Kinaxis", "careers_url": "https://www.kinaxis.com/en/company/careers", "domain": "kinaxis.com"},
    {"name": "OpenText", "careers_url": "https://careers.opentext.com/", "domain": "opentext.com"},
    {"name": "Dayforce", "careers_url": "https://www.dayforce.com/careers", "domain": "dayforce.com"},
    {"name": "Dialogue", "careers_url": "https://www.dialogue.co/en/careers", "domain": "dialogue.co"},
    {"name": "Busbud", "careers_url": "https://www.busbud.com/en/careers", "domain": "busbud.com"},
    {"name": "Transit", "careers_url": "https://transitapp.com/jobs", "domain": "transitapp.com"},
    {"name": "Ratehub", "careers_url": "https://www.ratehub.ca/careers", "domain": "ratehub.ca"},
    {"name": "EQ Bank", "careers_url": "https://www.eqbank.ca/careers", "domain": "eqbank.ca"},
    {"name": "Snaptravel", "careers_url": "https://www.snaptravel.com/careers", "domain": "snaptravel.com"},
    {"name": "HashiCorp", "careers_url": "https://www.hashicorp.com/careers", "domain": "hashicorp.com"},
    {"name": "HubSpot", "careers_url": "https://www.hubspot.com/careers", "domain": "hubspot.com"},
    {"name": "Atlassian", "careers_url": "https://www.atlassian.com/company/careers", "domain": "atlassian.com"},
    {"name": "Unity", "careers_url": "https://careers.unity.com/", "domain": "unity.com"},
    {"name": "DoorDash", "careers_url": "https://careers.doordash.com/", "domain": "doordash.com"},
    {"name": "Shopify", "careers_url": "https://www.shopify.com/careers", "domain": "shopify.com"},
]


def collect_careers_seed_candidates(
    existing: list[dict[str, Any]] | None = None,
) -> list[CompanyCandidate]:
    """Return careers-URL seeds not already covered by a board token."""
    have_domains: set[str] = set()
    have_names: set[str] = set()
    for row in existing or []:
        dom = (row.get("domain") or canonical_domain(str(row.get("careers_url") or "")) or "").casefold()
        if dom:
            have_domains.add(dom)
        name = str(row.get("name") or "").casefold()
        if name:
            have_names.add(name)
        # Already have a fetchable token — no need to re-seed careers URL.
        if row.get("board_token") and (row.get("ats") or "").lower() not in ("unknown", ""):
            if dom:
                have_domains.add(dom)

    out: list[CompanyCandidate] = []
    for row in _CANADIAN_CAREERS_SEEDS:
        domain = (row.get("domain") or canonical_domain(row["careers_url"]) or "").casefold()
        name = row["name"].casefold()
        if domain in have_domains or name in have_names:
            continue
        out.append(
            CompanyCandidate(
                name=row["name"],
                domain=row.get("domain"),
                careers_url=row["careers_url"],
                ats="unknown",
                board_token=None,
                discovery_source="careers_seed",
                evidence={"seed": "canadian_careers_v1"},
            )
        )
    return out
