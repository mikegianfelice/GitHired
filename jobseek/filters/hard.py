"""Deterministic hard filters: title, Canada-remote location, salary floors."""

from __future__ import annotations

import re
from typing import Any

from jobseek.models import HardFilterResult

_CANADA_OK = re.compile(
    r"""
    \bcanada\b |
    \bcanadian\b |
    remote\s+(?:in\s+|from\s+)?canada |
    canada\s*\(remote\) |
    remote\s*[-–—]\s*canada |
    work\s+from\s+canada |
    locations?\s+include[sd]?\s+canada |
    worldwide |
    work\s+from\s+anywhere |
    remote\s*\(anywhere\) |
    anywhere\s+in\s+the\s+world |
    north\s+america
    """,
    re.I | re.X,
)

_US_ONLY = re.compile(
    r"""
    \b(?:must|only)\s+be\s+(?:located\s+in\s+|based\s+in\s+)?(?:the\s+)?(?:united\s+states|u\.?s\.?a?\.?)\b |
    \bus[\s-]?only\b |
    \bunited\s+states\s+only\b |
    \bmust\s+reside\s+in\s+(?:the\s+)?(?:united\s+states|u\.?s\.?)\b |
    \bus\s+work\s+authorization\s+required\b |
    \bmust\s+be\s+eligible\s+to\s+work\s+in\s+(?:the\s+)?(?:united\s+states|u\.?s\.?)\b |
    \bno\s+visa\s+sponsorship\b.*\bunited\s+states\b |
    remote\s+within\s+(?:the\s+)?(?:united\s+states|u\.?s\.?)\s+only
    """,
    re.I | re.X,
)

_US_GEO = re.compile(
    r"\b(?:united\s+states|u\.?s\.?a?\.?|usa)\b",
    re.I,
)

_REMOTE = re.compile(r"\bremote\b|\bwfh\b|work\s+from\s+home", re.I)

_EXCLUDE_CANADA = re.compile(
    r"""
    \bexcept\s+canada\b |
    \bexcluding\s+canada\b |
    \bnot\s+(?:available|open)\s+in\s+canada\b |
    \bcanada\s+not\s+eligible\b
    """,
    re.I | re.X,
)


def _blob(job: dict[str, Any]) -> str:
    parts = [
        job.get("title") or "",
        job.get("location_raw") or "",
        job.get("description") or "",
        job.get("company") or "",
    ]
    return "\n".join(parts)


def _title_match(title: str, search_cfg: dict[str, Any]) -> bool:
    title_l = (title or "").casefold()
    candidates = list(search_cfg.get("target_titles") or []) + list(
        search_cfg.get("title_aliases") or []
    )
    for cand in candidates:
        tokens = [t for t in re.split(r"\s+", str(cand).casefold()) if t]
        if tokens and all(tok in title_l for tok in tokens):
            return True
        # also allow substring of full phrase
        if str(cand).casefold() in title_l:
            return True
    return False


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
    # Infer currency from raw if needed
    raw = (job.get("salary_raw") or "").upper()
    if not currency:
        if "CAD" in raw or "C$" in raw:
            currency = "CAD"
        elif "USD" in raw or "$" in raw:
            currency = "USD"
    floor = None
    if currency and currency in floors:
        floor = float(floors[currency])
    elif "CAD" in floors and currency is None:
        # ambiguous — FLAG rather than invent
        return "FLAG", [f"salary {value} with unknown currency"]
    if floor is None:
        return "PASS", [f"no floor configured for {currency or 'unknown'}"]
    if float(value) < floor:
        return "FAIL", [f"salary {value} {currency} below floor {floor}"]
    return "PASS", [f"salary {value} {currency} meets floor {floor}"]


def evaluate_location(job: dict[str, Any], search_cfg: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    """Return (verdict, reasons, evidence quotes). Never invent Canada eligibility."""
    loc_cfg = search_cfg.get("location") or {}
    unknown_policy = (loc_cfg.get("unknown_location_policy") or "flag").lower()
    allow_us = bool(loc_cfg.get("allow_us_employer_remote_with_canada_evidence", True))
    reject_us_only = bool(loc_cfg.get("reject_us_only_remote", True))

    text = _blob(job)
    location = job.get("location_raw") or ""
    evidence: list[str] = []
    reasons: list[str] = []

    if _EXCLUDE_CANADA.search(text):
        m = _EXCLUDE_CANADA.search(text)
        evidence.append(m.group(0) if m else "excluding canada")
        return "FAIL", ["posting excludes Canada"], evidence

    canada_hit = _CANADA_OK.search(text) or _CANADA_OK.search(location)
    us_only_hit = _US_ONLY.search(text)
    remote_hit = _REMOTE.search(text) or _REMOTE.search(location)
    us_geo = _US_GEO.search(location) or _US_GEO.search(text[:500])

    if canada_hit:
        evidence.append(canada_hit.group(0))
        reasons.append("Canada / worldwide eligibility evidence found")
        return "PASS", reasons, evidence

    if us_only_hit and reject_us_only:
        evidence.append(us_only_hit.group(0))
        return "FAIL", ["US-only remote / US work-authorization requirement"], evidence

    # Preferred Canada remote phrases in location alone
    for phrase in loc_cfg.get("preferred") or []:
        if phrase.casefold() in (location or "").casefold() or phrase.casefold() in text.casefold():
            evidence.append(phrase)
            return "PASS", [f"matched preferred location phrase: {phrase}"], evidence

    if remote_hit and us_geo and not canada_hit:
        if allow_us and not reject_us_only:
            return "FLAG", ["US remote without explicit Canada evidence"], evidence
        evidence.append(remote_hit.group(0))
        if us_geo:
            evidence.append(us_geo.group(0))
        return "FAIL", ["US remote without explicit Canada eligibility evidence"], evidence

    if remote_hit and not canada_hit and not us_geo:
        # Remote but silent on country
        if unknown_policy == "reject":
            return "FAIL", ["remote role with no Canada eligibility evidence"], evidence
        if unknown_policy == "pass":
            return "PASS", ["remote; unknown geography allowed by config"], evidence
        return "FLAG", ["remote role; Canada eligibility not evidenced"], evidence

    if not remote_hit and not canada_hit:
        if unknown_policy == "reject":
            return "FAIL", ["location/Canada eligibility not evidenced"], []
        if unknown_policy == "pass":
            return "PASS", ["unknown location allowed by config"], []
        return "FLAG", ["location/Canada eligibility not evidenced"], []

    return "FLAG", ["could not classify location deterministically"], evidence


def apply_hard_filters(job: dict[str, Any], search_cfg: dict[str, Any]) -> HardFilterResult:
    reasons: list[str] = []
    evidence: list[str] = []

    title_ok = _title_match(job.get("title") or "", search_cfg)
    if not title_ok:
        return HardFilterResult(
            verdict="FAIL",
            reasons=["title does not match configured target roles"],
            title_match=False,
            location_verdict="FLAG",
            salary_verdict="PASS",
        )

    loc_verdict, loc_reasons, loc_evidence = evaluate_location(job, search_cfg)
    reasons.extend(loc_reasons)
    evidence.extend(loc_evidence)

    sal_verdict, sal_reasons = _salary_verdict(job, search_cfg)
    reasons.extend(sal_reasons)

    # Overall: any FAIL → FAIL; else any FLAG → FLAG; else PASS
    verdicts = {loc_verdict, sal_verdict}
    if "FAIL" in verdicts:
        overall = "FAIL"
    elif "FLAG" in verdicts:
        overall = "FLAG"
    else:
        overall = "PASS"

    return HardFilterResult(
        verdict=overall,
        reasons=reasons,
        title_match=True,
        location_verdict=loc_verdict,
        salary_verdict=sal_verdict,
        evidence=evidence,
    )
