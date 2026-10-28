"""Deterministic hard filters: tracks, three-state Canada eligibility, seniority, salary."""

from __future__ import annotations

import re
from typing import Any

from jobseek.filters.tracks import detect_seniority, match_track, seniority_gate
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
    anywhere\s+in\s+canada
    """,
    re.I | re.X,
)

_WORLDWIDE = re.compile(
    r"""
    worldwide |
    work\s+from\s+anywhere |
    remote\s*\(anywhere\) |
    anywhere\s+in\s+the\s+world |
    globally\s+remote |
    remote[\s-]?first\b.*\banywhere\b
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

_NORTH_AMERICA = re.compile(r"\bnorth\s+america\b", re.I)

_REMOTE = re.compile(r"\bremote\b|\bwfh\b|work\s+from\s+home", re.I)
_HYBRID = re.compile(r"\bhybrid\b", re.I)
_ONSITE = re.compile(r"\b(?:on[\s-]?site|in[\s-]?office|office[\s-]?based)\b", re.I)

_EXCLUDE_CANADA = re.compile(
    r"""
    \bexcept\s+canada\b |
    \bexcluding\s+canada\b |
    \bnot\s+(?:available|open)\s+in\s+canada\b |
    \bcanada\s+not\s+eligible\b
    """,
    re.I | re.X,
)

_PROVINCE_ALIASES = {
    "ontario": "Ontario",
    "on": "Ontario",
    "quebec": "Quebec",
    "qc": "Quebec",
    "british columbia": "British Columbia",
    "bc": "British Columbia",
    "alberta": "Alberta",
    "ab": "Alberta",
    "manitoba": "Manitoba",
    "saskatchewan": "Saskatchewan",
    "nova scotia": "Nova Scotia",
    "new brunswick": "New Brunswick",
    "newfoundland": "Newfoundland",
    "prince edward island": "Prince Edward Island",
    "yukon": "Yukon",
    "northwest territories": "Northwest Territories",
    "nunavut": "Nunavut",
}


def _blob(job: dict[str, Any]) -> str:
    parts = [
        job.get("title") or "",
        job.get("location_raw") or "",
        job.get("description") or "",
        job.get("company") or "",
    ]
    return "\n".join(parts)


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
        return "FLAG", [f"salary {value} with unknown currency"]
    if floor is None:
        return "PASS", [f"no floor configured for {currency or 'unknown'}"]
    if float(value) < floor:
        return "FAIL", [f"salary {value} {currency} below floor {floor}"]
    return "PASS", [f"salary {value} {currency} meets floor {floor}"]


def _province_hit(text: str, provinces: list[str]) -> str | None:
    blob = text.casefold()
    for prov in provinces:
        key = prov.casefold().strip()
        if len(key) <= 2:
            if re.search(rf"\b{re.escape(key)}\b", blob):
                return prov
        elif key in blob:
            return prov
    for alias, canonical in _PROVINCE_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", blob):
            if not provinces or any(
                canonical.casefold() == p.casefold() or alias == p.casefold() for p in provinces
            ):
                return canonical
    return None


def _city_hit(text: str, cities: list[str]) -> str | None:
    blob = text.casefold()
    for city in cities:
        if city.casefold() in blob:
            return city
    return None


def classify_canada_eligibility(
    job: dict[str, Any], search_cfg: dict[str, Any]
) -> tuple[str, str, list[str], list[str]]:
    """Return (eligibility, location_verdict, reasons, evidence).

    eligibility: ELIGIBLE | UNCERTAIN | INELIGIBLE
    location_verdict: PASS | FLAG | FAIL (compat mapping)
    """
    loc_cfg = search_cfg.get("location") or {}
    reject_us_only = bool(loc_cfg.get("reject_us_only_remote", True))
    modes = {str(m).casefold() for m in (loc_cfg.get("modes") or ["remote_canada"])}
    provinces = [str(p) for p in (loc_cfg.get("provinces") or [])]
    cities = [str(c) for c in (loc_cfg.get("cities") or [])]

    text = _blob(job)
    location = job.get("location_raw") or ""
    evidence: list[str] = []
    reasons: list[str] = []

    if _EXCLUDE_CANADA.search(text):
        m = _EXCLUDE_CANADA.search(text)
        evidence.append(m.group(0) if m else "excluding canada")
        return "INELIGIBLE", "FAIL", ["posting excludes Canada"], evidence

    canada_hit = _CANADA_OK.search(text) or _CANADA_OK.search(location)
    worldwide_hit = _WORLDWIDE.search(text) or _WORLDWIDE.search(location)
    us_only_hit = _US_ONLY.search(text)
    remote_hit = _REMOTE.search(text) or _REMOTE.search(location)
    hybrid_hit = _HYBRID.search(text) or _HYBRID.search(location)
    onsite_hit = _ONSITE.search(text) or _ONSITE.search(location)
    us_geo = _US_GEO.search(location) or _US_GEO.search(text[:800])
    na_hit = _NORTH_AMERICA.search(text) or _NORTH_AMERICA.search(location)
    prov_hit = _province_hit(f"{location}\n{text[:2000]}", provinces or list(_PROVINCE_ALIASES.values()))
    city_hit = _city_hit(f"{location}\n{text[:2000]}", cities) if cities else None

    if us_only_hit and reject_us_only:
        evidence.append(us_only_hit.group(0))
        return (
            "INELIGIBLE",
            "FAIL",
            ["US-only remote / US work-authorization requirement"],
            evidence,
        )

    # Preferred Canada phrases
    for phrase in loc_cfg.get("preferred") or []:
        if phrase.casefold() in (location or "").casefold() or phrase.casefold() in text.casefold():
            evidence.append(phrase)
            return "ELIGIBLE", "PASS", [f"matched preferred location phrase: {phrase}"], evidence

    if canada_hit:
        evidence.append(canada_hit.group(0))
        reasons.append("explicit Canada / Canadian eligibility evidence")
        return "ELIGIBLE", "PASS", reasons, evidence

    if worldwide_hit and not us_only_hit:
        evidence.append(worldwide_hit.group(0))
        reasons.append("genuine worldwide / work-from-anywhere remote")
        return "ELIGIBLE", "PASS", reasons, evidence

    if city_hit and ("hybrid" in modes or "onsite" in modes or "remote_province" in modes):
        evidence.append(city_hit)
        if us_geo and not canada_hit:
            return (
                "UNCERTAIN",
                "FLAG",
                ["Canadian city mentioned alongside US geo — ambiguous"],
                evidence,
            )
        return "ELIGIBLE", "PASS", [f"matched Canadian city: {city_hit}"], evidence

    if prov_hit and ("remote_province" in modes or "hybrid" in modes or "onsite" in modes):
        evidence.append(prov_hit)
        if us_geo and not canada_hit:
            return (
                "UNCERTAIN",
                "FLAG",
                ["Canadian province mentioned alongside US geo — ambiguous"],
                evidence,
            )
        return "ELIGIBLE", "PASS", [f"matched Canadian province: {prov_hit}"], evidence

    # On-site outside Canada without Canada evidence
    if onsite_hit and us_geo and not canada_hit and not city_hit and not prov_hit:
        evidence.append(onsite_hit.group(0))
        if us_geo:
            evidence.append(us_geo.group(0))
        return (
            "INELIGIBLE",
            "FAIL",
            ["on-site / in-office outside Canada"],
            evidence,
        )

    if remote_hit and us_geo and not canada_hit and not worldwide_hit:
        evidence.append(remote_hit.group(0))
        evidence.append(us_geo.group(0))
        return (
            "UNCERTAIN",
            "FLAG",
            ["US-primary remote without explicit Canadian eligibility"],
            evidence,
        )

    if na_hit and not canada_hit and not worldwide_hit:
        evidence.append(na_hit.group(0))
        return (
            "UNCERTAIN",
            "FLAG",
            ["North America remote with unclear country restrictions"],
            evidence,
        )

    if remote_hit and not canada_hit and not us_geo and not worldwide_hit:
        return (
            "UNCERTAIN",
            "FLAG",
            ["remote role; Canada eligibility not evidenced (unknown)"],
            evidence,
        )

    if not remote_hit and not canada_hit and not worldwide_hit:
        return (
            "UNCERTAIN",
            "FLAG",
            ["location/Canada eligibility not evidenced (unknown)"],
            [],
        )

    return (
        "UNCERTAIN",
        "FLAG",
        ["could not classify location deterministically (unknown)"],
        evidence,
    )


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

    # Overall: INELIGIBLE or salary FAIL → FAIL; UNCERTAIN/FLAG → FLAG; else PASS
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
