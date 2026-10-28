"""Deterministic hard filters: tracks, Canada location modes, salary floors."""

from __future__ import annotations

import re
from typing import Any

from jobseek.filters.tracks import match_track
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
    "mb": "Manitoba",
    "saskatchewan": "Saskatchewan",
    "sk": "Saskatchewan",
    "nova scotia": "Nova Scotia",
    "ns": "Nova Scotia",
    "new brunswick": "New Brunswick",
    "nb": "New Brunswick",
    "newfoundland": "Newfoundland",
    "nl": "Newfoundland",
    "prince edward island": "Prince Edward Island",
    "pei": "Prince Edward Island",
    "yukon": "Yukon",
    "yt": "Yukon",
    "northwest territories": "Northwest Territories",
    "nt": "Northwest Territories",
    "nunavut": "Nunavut",
    "nu": "Nunavut",
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


def _configured_provinces(loc_cfg: dict[str, Any]) -> list[str]:
    return [str(p) for p in (loc_cfg.get("provinces") or [])]


def _configured_cities(loc_cfg: dict[str, Any]) -> list[str]:
    return [str(c) for c in (loc_cfg.get("cities") or [])]


def _province_hit(text: str, provinces: list[str]) -> str | None:
    blob = text.casefold()
    for prov in provinces:
        key = prov.casefold().strip()
        if len(key) <= 2:
            # Short codes need word boundaries
            if re.search(rf"\b{re.escape(key)}\b", blob):
                return prov
        elif key in blob:
            return prov
    for alias, canonical in _PROVINCE_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", blob):
            if not provinces or any(canonical.casefold() == p.casefold() or alias == p.casefold() for p in provinces):
                return canonical
    return None


def _city_hit(text: str, cities: list[str]) -> str | None:
    blob = text.casefold()
    for city in cities:
        if city.casefold() in blob:
            return city
    return None


def evaluate_location(job: dict[str, Any], search_cfg: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    """Return (verdict, reasons, evidence quotes). Never invent Canada eligibility."""
    loc_cfg = search_cfg.get("location") or {}
    unknown_policy = (loc_cfg.get("unknown_location_policy") or "flag").lower()
    allow_us = bool(loc_cfg.get("allow_us_employer_remote_with_canada_evidence", True))
    reject_us_only = bool(loc_cfg.get("reject_us_only_remote", True))
    modes = {str(m).casefold() for m in (loc_cfg.get("modes") or ["remote_canada"])}
    provinces = _configured_provinces(loc_cfg)
    cities = _configured_cities(loc_cfg)

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
    hybrid_hit = _HYBRID.search(text) or _HYBRID.search(location)
    onsite_hit = _ONSITE.search(text) or _ONSITE.search(location)
    us_geo = _US_GEO.search(location) or _US_GEO.search(text[:500])
    prov_hit = _province_hit(f"{location}\n{text[:2000]}", provinces) if provinces else _province_hit(
        f"{location}\n{text[:2000]}", list(_PROVINCE_ALIASES.values())
    )
    city_hit = _city_hit(f"{location}\n{text[:2000]}", cities) if cities else None

    if us_only_hit and reject_us_only:
        evidence.append(us_only_hit.group(0))
        return "FAIL", ["US-only remote / US work-authorization requirement"], evidence

    # Preferred Canada remote phrases
    for phrase in loc_cfg.get("preferred") or []:
        if phrase.casefold() in (location or "").casefold() or phrase.casefold() in text.casefold():
            evidence.append(phrase)
            return "PASS", [f"matched preferred location phrase: {phrase}"], evidence

    if canada_hit:
        evidence.append(canada_hit.group(0))
        if remote_hit and "remote_canada" in modes:
            reasons.append("Canada / worldwide eligibility evidence found (remote)")
            return "PASS", reasons, evidence
        if prov_hit and "remote_province" in modes:
            evidence.append(prov_hit)
            reasons.append(f"Canada evidence with province match: {prov_hit}")
            return "PASS", reasons, evidence
        if hybrid_hit and "hybrid" in modes and (city_hit or prov_hit or True):
            reasons.append("Canada evidence with hybrid role")
            if city_hit:
                evidence.append(city_hit)
            return "PASS", reasons, evidence
        if onsite_hit and "onsite" in modes and (city_hit or prov_hit):
            reasons.append("Canada on-site / in-office with local match")
            if city_hit:
                evidence.append(city_hit)
            elif prov_hit:
                evidence.append(prov_hit)
            return "PASS", reasons, evidence
        # Broad Canada evidence without conflicting US-only
        reasons.append("Canada / worldwide eligibility evidence found")
        return "PASS", reasons, evidence

    # Province / city without explicit Canada word (Canadian cities)
    if city_hit and ("hybrid" in modes or "onsite" in modes or "remote_province" in modes):
        evidence.append(city_hit)
        if us_geo and not canada_hit:
            return "FLAG", ["Canadian city mentioned alongside US geo — ambiguous"], evidence
        return "PASS", [f"matched Canadian city: {city_hit}"], evidence

    if prov_hit and ("remote_province" in modes or "hybrid" in modes or "onsite" in modes):
        evidence.append(prov_hit)
        if us_geo and not canada_hit:
            return "FLAG", ["Canadian province mentioned alongside US geo — ambiguous"], evidence
        return "PASS", [f"matched Canadian province: {prov_hit}"], evidence

    if remote_hit and us_geo and not canada_hit:
        if allow_us and not reject_us_only:
            return "FLAG", ["US remote without explicit Canada evidence"], evidence
        evidence.append(remote_hit.group(0))
        if us_geo:
            evidence.append(us_geo.group(0))
        return "FAIL", ["US remote without explicit Canada eligibility evidence"], evidence

    if remote_hit and not canada_hit and not us_geo:
        if unknown_policy == "reject":
            return "FAIL", ["remote role with no Canada eligibility evidence"], evidence
        if unknown_policy == "pass":
            return "PASS", ["remote; unknown geography allowed by config"], evidence
        return "FLAG", ["remote role; Canada eligibility not evidenced (unknown)"], evidence

    if not remote_hit and not canada_hit:
        if unknown_policy == "reject":
            return "FAIL", ["location/Canada eligibility not evidenced"], []
        if unknown_policy == "pass":
            return "PASS", ["unknown location allowed by config"], []
        return "FLAG", ["location/Canada eligibility not evidenced (unknown)"], []

    return "FLAG", ["could not classify location deterministically (unknown)"], evidence


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
        )

    reasons.extend(track.reasons)

    loc_verdict, loc_reasons, loc_evidence = evaluate_location(job, search_cfg)
    reasons.extend(loc_reasons)
    evidence.extend(loc_evidence)

    sal_verdict, sal_reasons = _salary_verdict(job, search_cfg)
    reasons.extend(sal_reasons)

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
