"""Deterministic hard filters: tracks, three-state Canada eligibility, seniority, salary."""

from __future__ import annotations

from typing import Any

from jobseek.filters.location import classify_canada_eligibility
from jobseek.filters.tracks import match_track, seniority_gate
from jobseek.models import HardFilterResult

# Re-export for callers/tests that imported from hard
__all__ = [
    "apply_hard_filters",
    "classify_canada_eligibility",
    "evaluate_location",
]


def _salary_verdict(job: dict[str, Any], search_cfg: dict[str, Any]) -> tuple[str, list[str]]:
    salary_cfg = search_cfg.get("salary") or {}
    floors = salary_cfg.get("floors") or {}
    reject_missing = bool(salary_cfg.get("reject_missing"))
    currency = (job.get("salary_currency") or "").upper() or None
    amin = job.get("salary_min")
    amax = job.get("salary_max")
    value = amax or amin
    if value is None:
        if reject_missing:
            return "FAIL", ["salary missing and reject_missing=true"]
        return "PASS", ["salary missing — not auto-rejected"]
    # Validate floor types
    raw = (job.get("salary_raw") or "").upper()
    if not currency:
        if "CAD" in raw or "C$" in raw:
            currency = "CAD"
        elif "USD" in raw or "$" in raw:
            currency = "USD"
    floor = None
    if currency and currency in floors:
        try:
            floor = float(floors[currency])
        except (TypeError, ValueError):
            return "FLAG", [f"salary floor for {currency} is not a number"]
    elif "CAD" in floors and currency is None:
        return "FLAG", [f"salary {value} with unknown currency"]
    if floor is None:
        return "PASS", [f"no floor configured for {currency or 'unknown'}"]
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "FLAG", [f"salary value {value!r} is not numeric"]
    if numeric < floor:
        return "FAIL", [f"salary {value} {currency} below floor {floor}"]
    return "PASS", [f"salary {value} {currency} meets floor {floor}"]


def evaluate_location(job: dict[str, Any], search_cfg: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    """Compat wrapper: (location_verdict, reasons, evidence)."""
    _elig, verdict, reasons, evidence = classify_canada_eligibility(job, search_cfg)
    return verdict, reasons, evidence


def apply_hard_filters(job: dict[str, Any], search_cfg: dict[str, Any]) -> HardFilterResult:
    reasons: list[str] = []
    evidence: list[str] = []

    track = match_track(job.get("title") or "", search_cfg)
    if not track.matched:
        return HardFilterResult(
            verdict="FAIL",
            reasons=track.reasons,
            title_match=False,
            location_verdict="FLAG",
            salary_verdict="PASS",
            eligibility="UNCERTAIN",
        )

    reasons.extend(track.reasons)

    sen = seniority_gate(job.get("title") or "", search_cfg)
    if not sen.allowed:
        return HardFilterResult(
            verdict="FAIL",
            reasons=reasons + sen.reasons,
            title_match=True,
            location_verdict="FLAG",
            salary_verdict="PASS",
            eligibility="UNCERTAIN",
            evidence=evidence,
        )
    reasons.extend(sen.reasons)

    eligibility, loc_verdict, loc_reasons, loc_evidence = classify_canada_eligibility(
        job, search_cfg
    )
    reasons.extend(loc_reasons)
    evidence.extend(loc_evidence)

    sal_verdict, sal_reasons = _salary_verdict(job, search_cfg)
    reasons.extend(sal_reasons)

    if eligibility == "INELIGIBLE" or sal_verdict == "FAIL":
        overall = "FAIL"
    elif eligibility == "UNCERTAIN" or sal_verdict == "FLAG" or loc_verdict == "FLAG":
        overall = "FLAG"
    else:
        overall = "PASS"

    return HardFilterResult(
        verdict=overall,
        reasons=reasons,
        title_match=True,
        location_verdict=loc_verdict,
        salary_verdict=sal_verdict,
        eligibility=eligibility,
        evidence=evidence,
    )
