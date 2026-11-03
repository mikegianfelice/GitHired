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


DEFAULT_USD_TO_CAD = 1.35


def _resolve_fx_rate(salary_cfg: dict[str, Any]) -> tuple[float, list[str]]:
    """Return (usd_to_cad, notes). Invalid/non-positive rates fall back to default."""
    notes: list[str] = []
    raw = salary_cfg.get("usd_to_cad")
    if raw is None:
        return DEFAULT_USD_TO_CAD, notes
    try:
        fx_f = float(raw)
    except (TypeError, ValueError):
        notes.append(
            f"invalid usd_to_cad={raw!r}; using documented default {DEFAULT_USD_TO_CAD}"
        )
        return DEFAULT_USD_TO_CAD, notes
    if fx_f <= 0:
        notes.append(
            f"invalid usd_to_cad={fx_f}; using documented default {DEFAULT_USD_TO_CAD}"
        )
        return DEFAULT_USD_TO_CAD, notes
    return fx_f, notes


def _preferred_currency(salary_cfg: dict[str, Any], floors: dict[str, Any]) -> str | None:
    """Authoritative currency for floor comparison unless floors_independent."""
    raw = str(salary_cfg.get("preferred_currency") or "").strip().upper()
    if raw in ("CAD", "USD"):
        return raw
    if floors.get("CAD") is not None or floors.get("cad") is not None:
        return "CAD"
    if floors.get("USD") is not None or floors.get("usd") is not None:
        return "USD"
    return None


def _floor_for(floors: dict[str, Any], currency: str) -> float | None:
    key = currency.upper()
    val = floors.get(key)
    if val is None:
        val = floors.get(key.lower())
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _convert_to_preferred(
    amount: float, job_currency: str, preferred: str, fx: float
) -> float:
    """Convert annual amount into preferred currency using usd_to_cad."""
    jc = job_currency.upper()
    pc = preferred.upper()
    if jc == pc:
        return amount
    if jc == "USD" and pc == "CAD":
        return amount * fx
    if jc == "CAD" and pc == "USD":
        return amount / fx
    return amount


def _salary_verdict(job: dict[str, Any], search_cfg: dict[str, Any]) -> tuple[str, list[str]]:
    """Salary floor gate with configurable policy.

    Policies:
      - flexible (default): missing/unverified pay PASSes with a clear warning;
        verified below-floor pay FAILs.
      - strict: missing/unverified pay FAILs; below-floor FAILs.
      - none: ignore salary minimum entirely.

    Preferred currency is authoritative by default: job pay is converted via
    ``salary.usd_to_cad`` (documented default 1.35; never 1:1) before comparing
    to the preferred floor. Set ``floors_independent: true`` to keep advanced
    per-currency floors without cross-conversion.
    """
    from jobseek.filters.salary import salary_label_for_job

    salary_cfg = search_cfg.get("salary") or {}
    policy = _salary_policy(search_cfg)
    if policy == "none":
        return "PASS", ["salary policy=none — minimum ignored"]

    floors = dict(salary_cfg.get("floors") or {})
    fx_f, fx_notes = _resolve_fx_rate(salary_cfg)
    floors_independent = bool(salary_cfg.get("floors_independent"))
    preferred = _preferred_currency(salary_cfg, floors)

    # For label helpers: when preferred-currency mode is active, only expose the
    # preferred floor so native-currency dual floors cannot short-circuit FX.
    label_floors = floors
    if floors and preferred and not floors_independent:
        pref_floor = _floor_for(floors, preferred)
        label_floors = {preferred: pref_floor} if pref_floor is not None else {}

    info = salary_label_for_job(job, floors=label_floors if label_floors else None)

    if info.confidence in ("undisclosed", "unverified") or info.salary_max is None:
        if policy == "strict":
            return (
                "FAIL",
                [
                    "salary policy=strict — missing/unverified compensation rejected",
                    info.label,
                    *fx_notes,
                ],
            )
        return (
            "PASS",
            [
                "salary policy=flexible — missing pay accepted with warning",
                info.label,
                *fx_notes,
            ],
        )

    currency = (info.currency or "").upper() or None
    # Range semantics: compare the high end (candidate can negotiate within band).
    high = info.salary_max if info.salary_max is not None else info.salary_min
    if high is None or not floors or currency not in ("CAD", "USD"):
        if info.confidence == "below_floor":
            return "FAIL", [info.label, *info.reasons, *fx_notes]
        return "PASS", [info.label, *info.reasons, *fx_notes]

    try:
        high_f = float(high)
    except (TypeError, ValueError):
        return "PASS", [info.label, *info.reasons, *fx_notes]

    # Advanced: independent per-currency floors (no cross-conversion).
    if floors_independent:
        native_floor = _floor_for(floors, currency)
        if native_floor is None:
            return "PASS", [
                f"Verified salary: {currency} {int(high_f):,} "
                f"(no {currency} floor under floors_independent)",
                *fx_notes,
            ]
        if high_f < native_floor:
            return (
                "FAIL",
                [
                    f"Salary below preference: {currency} {int(high_f):,} "
                    f"(floor {int(native_floor):,}; floors_independent)",
                    *fx_notes,
                ],
            )
        return (
            "PASS",
            [
                f"Verified salary: {currency} {int(high_f):,} "
                f"(meets {currency} floor {int(native_floor):,}; floors_independent)",
                *fx_notes,
            ],
        )

    # Default: convert into preferred currency, compare against preferred floor only.
    if preferred is None:
        if info.confidence == "below_floor":
            return "FAIL", [info.label, *info.reasons, *fx_notes]
        return "PASS", [info.label, *info.reasons, *fx_notes]

    pref_floor = _floor_for(floors, preferred)
    if pref_floor is None:
        return "PASS", [info.label, *info.reasons, *fx_notes]

    converted = _convert_to_preferred(high_f, currency, preferred, fx_f)
    # Stable display rounding; comparison uses full float precision.
    converted_disp = int(round(converted))
    high_disp = int(round(high_f))
    floor_disp = int(round(pref_floor))

    if currency != preferred:
        note = (
            f"{currency} {high_disp:,} ≈ {preferred} {converted_disp:,} "
            f"at usd_to_cad={fx_f}"
        )
        never_1to1 = "USD amounts are never treated as CAD 1:1"
        if converted < pref_floor:
            return (
                "FAIL",
                [
                    f"Salary below preference after FX: {note} "
                    f"({preferred} floor {floor_disp:,})",
                    never_1to1,
                    *fx_notes,
                ],
            )
        return (
            "PASS",
            [
                f"Verified salary after FX: {note} "
                f"(meets {preferred} floor {floor_disp:,})",
                never_1to1,
                *fx_notes,
            ],
        )

    if high_f < pref_floor:
        return (
            "FAIL",
            [
                f"Salary below preference: {preferred} {high_disp:,} "
                f"(floor {floor_disp:,})",
                *fx_notes,
            ],
        )
    return (
        "PASS",
        [
            f"Verified salary: {preferred} {high_disp:,} "
            f"(meets floor {floor_disp:,})",
            *fx_notes,
        ],
    )


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
