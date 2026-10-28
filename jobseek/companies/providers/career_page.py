"""Inspect careers pages for ATS board tokens."""

from __future__ import annotations

from typing import Any

from jobseek.adapters.detector import detect_careers_page
from jobseek.companies.domain_util import canonical_domain
from jobseek.companies.providers.base import CompanyCandidate
from jobseek.http_client import RateLimitedClient


def collect_career_page_candidates(
    companies: list[dict[str, Any]],
    client: RateLimitedClient,
    *,
    max_pages: int = 40,
) -> tuple[list[CompanyCandidate], list[str]]:
    out: list[CompanyCandidate] = []
    warnings: list[str] = []
    checked = 0
    for company in companies:
        if checked >= max_pages:
            break
        careers = (company.get("careers_url") or "").strip()
        if not careers:
            continue
        ats = (company.get("ats") or "unknown").lower()
        token = company.get("board_token") or company.get("site_slug")
        # Skip when already fully identified for a fetchable ATS
        if ats not in ("unknown", "", "rss") and token:
            continue
        if ats == "rss" and token and str(token).startswith("http"):
            continue
        checked += 1
        try:
            detection = detect_careers_page(careers, client)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"career_page {company.get('name')}: {exc}")
            continue
        if not detection:
            continue
        if detection.confidence == "low" or not detection.board_token:
            warnings.append(
                f"career_page {company.get('name')}: detection {detection.ats} "
                f"confidence={detection.confidence} token={detection.board_token!r} (not auto-enabling)"
            )
            continue
        out.append(
            CompanyCandidate(
                name=str(company.get("name") or detection.board_token),
                domain=canonical_domain(careers),
                careers_url=careers,
                ats=detection.ats,
                board_token=detection.board_token,
                discovery_source="detect",
                evidence={
                    "confidence": detection.confidence,
                    "evidence_url": detection.evidence_url,
                },
            )
        )
    return out, warnings
