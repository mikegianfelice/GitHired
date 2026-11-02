"""Deterministic hard filters: tracks, three-state Canada eligibility, seniority, salary."""

from __future__ import annotations

from typing import Any

from jobseek.filters.apply_url import classify_application_url
from jobseek.filters.location import classify_canada_eligibility
from jobseek.filters.tracks import match_track, seniority_gate
from jobseek.models import HardFilterResult

# Re-export for callers/tests that imported from hard
__all__ = [
    "apply_hard_filters",
    "classify_canada_eligibility",
    "evaluate_location",
]


def _salary_policy(search_cfg: dict[str, Any]) -> str:
    """Return flexible | strict | none.

    ``reject_missing: true`` remains a legacy alias for ``strict``.
    """
    salary_cfg = search_cfg.get("salary") or {}
    raw = str(salary_cfg.get("policy") or "").strip().casefold()
    if raw in ("flexible", "strict", "none"):
        return raw
    if bool(salary_cfg.get("reject_missing")):
        return "strict"
    return "flexible"


def _salary_verdict(job: dict[str, Any], search_cfg: dict[str, Any]) -> tuple[str, list[str]]:
    """Salary floor gate with configurable policy.

    Policies:
      - flexible (default): missing/unverified pay PASSes with a clear warning;
        verified below-floor pay FAILs.
      - strict: missing/unverified pay FAILs; below-floor FAILs.
      - none: ignore salary minimum entirely.

    USD vs CAD: never silently equate currencies. When a CAD floor is configured and
    the job is USD (or vice versa), compare using ``salary.usd_to_cad`` (documented
    FX rate) and label the conversion explicitly.
    """
    from jobseek.filters.salary import salary_label_for_job

    salary_cfg = search_cfg.get("salary") or {}
    policy = _salary_policy(search_cfg)
    if policy == "none":
        return "PASS", ["salary policy=none — minimum ignored"]

    floors = dict(salary_cfg.get("floors") or {})
    # Cross-currency comparison uses an explicit FX rate (never 1:1).
    fx = salary_cfg.get("usd_to_cad")
    try:
        fx_f = float(fx) if fx is not None else 1.35
    except (TypeError, ValueError):
        fx_f = 1.35
    info = salary_label_for_job(job, floors=floors if floors else None)

    if info.confidence in ("undisclosed", "unverified") or info.salary_max is None:
        if policy == "strict":
            return (
                "FAIL",
                [
                    "salary policy=strict — missing/unverified compensation rejected",
                    info.label,
                ],
            )
        return (
            "PASS",
            [
                "salary policy=flexible — missing pay accepted with warning",
                info.label,
            ],
        )

    # Re-evaluate below-floor with optional FX when currencies differ from floors.
    currency = (info.currency or "").upper() or None
    high = info.salary_max if info.salary_max is not None else info.salary_min
    if high is not None and floors:
        cad_floor = floors.get("CAD") or floors.get("cad")
        usd_floor = floors.get("USD") or floors.get("usd")
        try:
            high_f = float(high)
            if currency == "USD" and cad_floor is not None and usd_floor is None:
                cad_equiv = high_f * fx_f
                if cad_equiv < float(cad_floor):
                    return (
                        "FAIL",
                        [
                            f"Salary below preference after FX: USD {int(high_f):,} "
                            f"≈ CAD {int(cad_equiv):,} at usd_to_cad={fx_f} "
                            f"(CAD floor {int(float(cad_floor)):,})",
                            "USD amounts are never treated as CAD 1:1",
                        ],
                    )
                return (
                    "PASS",
                    [
                        f"Verified salary: USD {int(high_f):,} "
                        f"(≈ CAD {int(cad_equiv):,} at usd_to_cad={fx_f})",
                    ],
                )
            if currency == "CAD" and usd_floor is not None and cad_floor is None:
                usd_equiv = high_f / fx_f if fx_f else high_f
                if usd_equiv < float(usd_floor):
                    return (
                        "FAIL",
                        [
                            f"Salary below preference after FX: CAD {int(high_f):,} "
                            f"≈ USD {int(usd_equiv):,} at usd_to_cad={fx_f} "
                            f"(USD floor {int(float(usd_floor)):,})",
                        ],
                    )
        except (TypeError, ValueError):
            pass

    if info.confidence == "below_floor":
        return "FAIL", [info.label, *info.reasons]

    return "PASS", [info.label, *info.reasons]


def evaluate_location(job: dict[str, Any], search_cfg: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    """Compat wrapper: (location_verdict, reasons, evidence)."""
    _elig, verdict, reasons, evidence = classify_canada_eligibility(job, search_cfg)
    return verdict, reasons, evidence


def apply_hard_filters(
    job: dict[str, Any],
    search_cfg: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> HardFilterResult:
    reasons: list[str] = []
    evidence: list[str] = []

    track = match_track(job.get("title") or "", search_cfg)
    if not track.matched:
        # Off-track titles are irrelevant — not "uncertain Canadian eligibility".
        return HardFilterResult(
            verdict="FAIL",
            reasons=track.reasons + ["relevance=NO_MATCH (title outside selected tracks)"],
            title_match=False,
            relevance="NO_MATCH",
            location_verdict="FLAG",
            salary_verdict="PASS",
            eligibility="IRRELEVANT",
        )

    reasons.extend(track.reasons)

    candidate_years = None
    if profile:
        exp = profile.get("experience") or {}
        raw_years = exp.get("years")
        if raw_years is not None:
            try:
                candidate_years = int(raw_years)
            except (TypeError, ValueError):
                candidate_years = None

    sen = seniority_gate(
        job.get("title") or "",
        search_cfg,
        description=str(job.get("description") or ""),
        candidate_years=candidate_years,
    )
    if not sen.allowed:
        return HardFilterResult(
            verdict="FAIL",
            reasons=reasons + sen.reasons + ["relevance=REVIEW (seniority gate)"],
            title_match=True,
            relevance="REVIEW",
            location_verdict="FLAG",
            salary_verdict="PASS",
            # Seniority fail is not a geography claim.
            eligibility="IRRELEVANT",
            evidence=evidence,
        )
    reasons.extend(sen.reasons)

    eligibility, loc_verdict, loc_reasons, loc_evidence = classify_canada_eligibility(
        job, search_cfg
    )
    reasons.extend(loc_reasons)
    evidence.extend(loc_evidence)

    # Enrich from structured fields / description before floor check (never invent).
    from jobseek.filters.salary import enrich_job_salary

    job = enrich_job_salary(job)
    sal_verdict, sal_reasons = _salary_verdict(job, search_cfg)
    reasons.extend(sal_reasons)

    # Affiliate / WhatJobs-style redirects and Freehire review-only rows must not
    # enter the confirmed shortlist. LinkedIn index hits are unchanged (separate source).
    apply_candidate = job.get("apply_url") or job.get("url")
    apply_verdict = classify_application_url(
        str(apply_candidate) if apply_candidate else None
    )
    source = str(job.get("source") or "")
    reject_apply = (
        apply_verdict.kind == "affiliate"
        or source == "freehire_review"
        or (source == "freehire" and not apply_verdict.actionable)
    )
    if reject_apply:
        reasons.append(
            f"application URL not confirmed-actionable: {apply_verdict.reason}"
        )
        if apply_verdict.host:
            evidence.append(apply_verdict.host)
        # Preserve geographic classification in reasons, but demote eligibility so
        # githired jobs (ELIGIBLE-only) never surfaces affiliate-only rows.
        if eligibility == "ELIGIBLE":
            eligibility = "UNCERTAIN"
        if loc_verdict == "PASS":
            loc_verdict = "FLAG"

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
        relevance="MATCH",
        location_verdict=loc_verdict,
        salary_verdict=sal_verdict,
        eligibility=eligibility,
        evidence=evidence,
    )
