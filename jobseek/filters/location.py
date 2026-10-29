"""Field-aware Canada eligibility classification.

Structured ``location_raw`` is primary evidence. Description text may only
confirm hiring eligibility via explicit phrases — never via incidental office
mentions or English words that collide with province abbreviations (e.g. ``on``).
"""

from __future__ import annotations

import re
from typing import Any

# Full province names (case-insensitive) — safe in location fields.
_PROVINCE_NAMES: dict[str, str] = {
    "ontario": "Ontario",
    "quebec": "Quebec",
    "british columbia": "British Columbia",
    "alberta": "Alberta",
    "manitoba": "Manitoba",
    "saskatchewan": "Saskatchewan",
    "nova scotia": "Nova Scotia",
    "new brunswick": "New Brunswick",
    "newfoundland": "Newfoundland and Labrador",
    "newfoundland and labrador": "Newfoundland and Labrador",
    "prince edward island": "Prince Edward Island",
    "yukon": "Yukon",
    "northwest territories": "Northwest Territories",
    "nunavut": "Nunavut",
}

# Two-letter codes — ONLY matched with geographic context / uppercase in location.
_PROVINCE_CODES: dict[str, str] = {
    "ON": "Ontario",
    "QC": "Quebec",
    "BC": "British Columbia",
    "AB": "Alberta",
    "MB": "Manitoba",
    "SK": "Saskatchewan",
    "NS": "Nova Scotia",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "PE": "Prince Edward Island",
    "YT": "Yukon",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
}

_CANADIAN_CITIES = (
    "toronto",
    "vancouver",
    "montreal",
    "montréal",
    "ottawa",
    "calgary",
    "edmonton",
    "winnipeg",
    "halifax",
    "victoria",
    "waterloo",
    "kitchener",
    "mississauga",
    "brampton",
    "hamilton",
    "london, on",  # disambiguate from London, UK via province context elsewhere
    "quebec city",
    "saskatoon",
    "regina",
    "gatineau",
    "laval",
    "surrey",
    "burnaby",
    "richmond",
    "markham",
    "vaughan",
    "oakville",
    "burlington",
    "oshawa",
    "windsor",
    "st. john's",
    "st johns",
    "charlottetown",
    "whitehorse",
    "yellowknife",
    "iqaluit",
)

# Hiring-eligibility phrases acceptable in description (not office tourism).
_CANADA_HIRE = re.compile(
    r"""
    \bremote\s+(?:in\s+|from\s+)?canada\b |
    \bcanada\s*\(\s*remote\s*\) |
    \bremote\s*[-–—]\s*canada\b |
    \bcanada\s*[-–—]\s*remote\b |
    \bwork\s+from\s+canada\b |
    \bworking\s+from\s+canada\b |
    \blocations?\s+include[sd]?\s+canada\b |
    \banywhere\s+in\s+canada\b |
    \bhire\s+(?:in|from)\s+canada\b |
    \beligible\s+to\s+work\s+in\s+canada\b |
    \bopen\s+to\s+(?:candidates?\s+in\s+)?canada\b |
    \bcanadians?\s+(?:welcome|encouraged|eligible)\b |
    \bcanada\s+remote\b |
    \bremote\s+canada\b
    """,
    re.I | re.X,
)

# Bare "Canada" / "Canadian" in the structured location field only.
_CANADA_WORD = re.compile(r"\bcanada\b|\bcanadian\b", re.I)

# Genuine worldwide remote — NOT "offices worldwide".
_WORLDWIDE_REMOTE = re.compile(
    r"""
    \bwork\s+from\s+anywhere\b |
    \bremote\s*\(\s*anywhere\s*\) |
    \banywhere\s+in\s+the\s+world\b |
    \bglobally\s+remote\b |
    \bhire\s+from\s+anywhere\b |
    \bcandidates?\s+from\s+anywhere\b |
    \bremote[\s-]?first\b.{0,60}\banywhere\b |
    \bfully\s+remote\b.{0,40}\b(?:worldwide|anywhere)\b |
    \bworldwide\s+remote\b |
    \bremote\s+worldwide\b |
    \bwork\s+remotely\s+from\s+anywhere\b
    """,
    re.I | re.X,
)

_OFFICES_WORLDWIDE = re.compile(
    r"\b(?:offices?|locations?|headquarters|hq|presence)\b.{0,40}\bworldwide\b|"
    r"\bworldwide\b.{0,40}\b(?:offices?|locations?|presence)\b",
    re.I,
)

_US_ONLY = re.compile(
    r"""
    \b(?:must|only)\s+be\s+(?:located\s+in\s+|based\s+in\s+)?(?:the\s+)?(?:united\s+states|u\.?s\.?a?\.?)\b |
    \bus[\s-]?only\b |
    \bunited\s+states\s+only\b |
    \bmust\s+reside\s+in\s+(?:the\s+)?(?:united\s+states|u\.?s\.?)\b |
    \bus\s+work\s+authorization\s+required\b |
    \bmust\s+be\s+eligible\s+to\s+work\s+in\s+(?:the\s+)?(?:united\s+states|u\.?s\.?)\b |
    \bremote\s+within\s+(?:the\s+)?(?:united\s+states|u\.?s\.?)\s+only\b |
    \bonly\s+(?:open\s+to|hiring)\s+(?:candidates\s+in\s+)?(?:the\s+)?(?:united\s+states|u\.?s\.?)\b
    """,
    re.I | re.X,
)

_US_GEO = re.compile(
    r"\b(?:united\s+states|u\.?s\.?a?\.?|usa)\b",
    re.I,
)

_EXCLUDE_CANADA = re.compile(
    r"""
    \bexcept\s+canada\b |
    \bexcluding\s+canada\b |
    \bnot\s+(?:available|open)\s+in\s+canada\b |
    \bcanada\s+not\s+eligible\b
    """,
    re.I | re.X,
)

_REMOTE = re.compile(r"\bremote\b|\bwfh\b|work\s+from\s+home", re.I)
_HYBRID = re.compile(r"\bhybrid\b", re.I)
_ONSITE = re.compile(r"\b(?:on[\s-]?site|in[\s-]?office|office[\s-]?based)\b", re.I)
_NORTH_AMERICA = re.compile(r"\bnorth\s+america\b|\bnamer\b", re.I)

# Clear non-Canada geographic anchors in the location field.
_OVERSEAS_LOCATION = re.compile(
    r"""
    \b(?:
        united\s+kingdom | u\.?k\.? |
        england | scotland | wales | ireland | dublin |
        london (?!\s*,?\s*on\b) |
        india | bengaluru | bangalore | hyderabad | chennai | pune | mumbai | delhi | gurugram | gurgaon |
        germany | berlin | munich | amsterdam | netherlands |
        france | paris | spain | madrid | portugal | lisbon | greece | athens |
        australia | sydney | melbourne | japan | tokyo | singapore |
        brazil | sao\s+paulo | mexico\s+city |
        poland | warsaw | israel | tel\s+aviv |
        philippines | manila | kenya | nairobi
    )\b
    """,
    re.I | re.X,
)

# US city / state patterns commonly appearing alone in location_raw.
_US_LOCATION_HINT = re.compile(
    r"""
    \b(?:
        san\s+francisco | new\s+york | nyc | seattle | austin | boston | chicago |
        los\s+angeles | denver | atlanta | miami | portland | philadelphia |
        washington,?\s*d\.?c\.? | bay\s+area | silicon\s+valley |
        california | texas | washington\s+state | massachusetts | colorado |
        \bCA\b | \bNY\b | \bWA\b | \bTX\b | \bMA\b
    )\b
    """,
    re.I | re.X,
)

# Province code in geographic context inside a location string (case-sensitive for letters).
_PROVINCE_CODE_IN_LOCATION = re.compile(
    r"(?:"
    r"(?:^|[\s,;/(|\-–—])(?P<code>"
    + "|".join(_PROVINCE_CODES.keys())
    + r")(?=$|[\s,;/)|\-–—])"
    r"|"
    r"(?P<code2>"
    + "|".join(_PROVINCE_CODES.keys())
    + r")\s*,\s*canada"
    r")",
    re.X,
)


def normalize_province_list(raw: list[Any] | None) -> list[str]:
    """Normalize configured provinces; recover YAML ``ON`` → ``True`` footgun."""
    out: list[str] = []
    for item in raw or []:
        if item is True:
            # PyYAML 1.1: unquoted ON → True
            out.append("ON")
            continue
        if item is False:
            out.append("OFF")  # unlikely; keep explicit
            continue
        if item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _configured_province_match(canonical: str, provinces: list[str]) -> bool:
    if not provinces:
        return True
    canon_cf = canonical.casefold()
    for p in provinces:
        pc = p.casefold().strip()
        if pc == canon_cf:
            return True
        if pc in _PROVINCE_CODES and _PROVINCE_CODES[pc.upper() if len(pc) == 2 else pc].casefold() == canon_cf:
            return True
        # Allow configuring "ON" while canonical is Ontario
        code = next((c for c, name in _PROVINCE_CODES.items() if name.casefold() == canon_cf), None)
        if code and pc == code.casefold():
            return True
        name = _PROVINCE_NAMES.get(pc)
        if name and name.casefold() == canon_cf:
            return True
    return False


def find_province_in_location(location: str, provinces: list[str] | None = None) -> str | None:
    """Find a Canadian province in a structured location field only."""
    if not location or not str(location).strip():
        return None
    loc = str(location)
    provinces = normalize_province_list(list(provinces) if provinces is not None else [])

    loc_cf = loc.casefold()
    # Longest full names first
    for name_key, canonical in sorted(_PROVINCE_NAMES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(name_key)}\b", loc_cf):
            if _configured_province_match(canonical, provinces):
                return canonical

    for match in _PROVINCE_CODE_IN_LOCATION.finditer(loc):
        code = (match.group("code") or match.group("code2") or "").upper()
        canonical = _PROVINCE_CODES.get(code)
        if canonical and _configured_province_match(canonical, provinces):
            return canonical
    return None


def find_city_in_location(location: str, cities: list[str] | None = None) -> str | None:
    """Match Canadian cities primarily in the location field."""
    if not location:
        return None
    loc_cf = location.casefold()
    preferred = [c.casefold() for c in (cities or []) if c]
    # Prefer configured cities, then known Canadian cities
    candidates = preferred + [c for c in _CANADIAN_CITIES if c not in preferred]
    # Special-case London: only with ON/Ontario/Canada context
    for city in candidates:
        if city in ("london",):
            continue
        if city == "london, on":
            if re.search(r"\blondon\b", loc_cf) and (
                find_province_in_location(location) == "Ontario"
                or _CANADA_WORD.search(location)
            ):
                return "London"
            continue
        if re.search(rf"\b{re.escape(city)}\b", loc_cf):
            # Return original casing from config when possible
            for raw in cities or []:
                if raw.casefold() == city:
                    return raw
            return city.title()
    # London, ON specifically
    if re.search(r"\blondon\b", loc_cf) and (
        find_province_in_location(location) == "Ontario" or re.search(r"\bcanada\b", loc_cf)
    ):
        return "London"
    return None


def _location_has_overseas(location: str) -> re.Match[str] | None:
    if not location:
        return None
    # Avoid treating "London, ON" as UK
    if find_province_in_location(location) or find_city_in_location(location):
        # Still overseas if UK/India appears as a separate token alongside Canada?
        # Multi-location: handled by caller.
        pass
    return _OVERSEAS_LOCATION.search(location)


def _split_location_parts(location: str) -> list[str]:
    if not location:
        return []
    parts = re.split(r"[|/;]|(?:\s+[•·]\s+)|(?:\s+-\s+(?=[A-Z]))", location)
    return [p.strip() for p in parts if p and p.strip()]


def _part_is_canadian(part: str, provinces: list[str], cities: list[str]) -> bool:
    if _CANADA_WORD.search(part):
        return True
    if find_province_in_location(part, provinces):
        return True
    if find_city_in_location(part, cities):
        return True
    if _NORTH_AMERICA.search(part) and re.search(r"\b(?:canada|canadian|namer)\b", part, re.I):
        return True
    if re.search(r"\bnamer\b", part, re.I):
        return True  # North America remote often includes Canada — UNCERTAIN at call site
    return False


def _part_is_clearly_foreign(part: str) -> bool:
    if find_province_in_location(part) or find_city_in_location(part) or _CANADA_WORD.search(part):
        return False
    if _OVERSEAS_LOCATION.search(part):
        return True
    if _US_GEO.search(part) or _US_LOCATION_HINT.search(part):
        return True
    return False


def classify_canada_eligibility(
    job: dict[str, Any], search_cfg: dict[str, Any]
) -> tuple[str, str, list[str], list[str]]:
    """Return (eligibility, location_verdict, reasons, evidence).

    eligibility: ELIGIBLE | UNCERTAIN | INELIGIBLE
    location_verdict: PASS | FLAG | FAIL
    """
    loc_cfg = search_cfg.get("location") or {}
    reject_us_only = bool(loc_cfg.get("reject_us_only_remote", True))
    modes = {str(m).casefold() for m in (loc_cfg.get("modes") or ["remote_canada"])}
    provinces = normalize_province_list(loc_cfg.get("provinces") or [])
    cities = [str(c) for c in (loc_cfg.get("cities") or []) if c and not isinstance(c, bool)]

    location = str(job.get("location_raw") or "").strip()
    description = str(job.get("description") or "")
    # Prefer structured location; title rarely carries geo but keep out of province scans.
    evidence: list[str] = []
    reasons: list[str] = []

    blob_for_exclusions = f"{location}\n{description}"

    if _EXCLUDE_CANADA.search(blob_for_exclusions):
        m = _EXCLUDE_CANADA.search(blob_for_exclusions)
        evidence.append(m.group(0) if m else "excluding canada")
        return "INELIGIBLE", "FAIL", ["posting excludes Canada"], evidence

    us_only_hit = _US_ONLY.search(blob_for_exclusions)
    if us_only_hit and reject_us_only:
        evidence.append(us_only_hit.group(0))
        return (
            "INELIGIBLE",
            "FAIL",
            ["US-only remote / US work-authorization requirement"],
            evidence,
        )

    # Preferred Canada phrases — location field first, then hire phrases in description.
    for phrase in loc_cfg.get("preferred") or []:
        p = str(phrase).casefold()
        if p and p in location.casefold():
            evidence.append(str(phrase))
            return "ELIGIBLE", "PASS", [f"matched preferred location phrase: {phrase}"], evidence

    loc_canada = bool(_CANADA_WORD.search(location))
    loc_province = find_province_in_location(location, provinces or None)
    loc_city = find_city_in_location(location, cities or None)
    loc_remote = bool(_REMOTE.search(location))
    loc_hybrid = bool(_HYBRID.search(location))
    loc_onsite = bool(_ONSITE.search(location))
    loc_na = bool(_NORTH_AMERICA.search(location))
    loc_overseas = _location_has_overseas(location)
    loc_us = bool(_US_GEO.search(location) or _US_LOCATION_HINT.search(location))

    desc_hire = _CANADA_HIRE.search(description)
    desc_wfa = _WORLDWIDE_REMOTE.search(description) or _WORLDWIDE_REMOTE.search(location)
    offices_ww = _OFFICES_WORLDWIDE.search(description)
    desc_remote = bool(_REMOTE.search(description))
    desc_onsite = bool(_ONSITE.search(description))

    parts = _split_location_parts(location)
    canadian_parts = [p for p in parts if _part_is_canadian(p, provinces, cities)]
    foreign_parts = [p for p in parts if _part_is_clearly_foreign(p)]

    # --- Structured location decisions ---

    # Clear overseas on-site (London UK, Gurugram, etc.) without Canada option.
    # Remote-US without explicit "US only" stays UNCERTAIN later — not invented ELIGIBLE.
    overseas_onsite = bool(
        location
        and foreign_parts
        and not canadian_parts
        and not loc_canada
        and not loc_province
        and not loc_city
        and _OVERSEAS_LOCATION.search(location)
        and not loc_remote
    )
    if overseas_onsite and not desc_hire and not desc_wfa:
        evidence.append(foreign_parts[0])
        return (
            "INELIGIBLE",
            "FAIL",
            ["on-site / office location outside Canada"],
            evidence,
        )
    # Remote + explicit overseas city/country (e.g. "London, UK" or "Remote, London")
    # without Canada hire evidence → INELIGIBLE (not a Canada role).
    if (
        location
        and foreign_parts
        and not canadian_parts
        and not loc_canada
        and not loc_province
        and not loc_city
        and _OVERSEAS_LOCATION.search(location)
        and (loc_remote or desc_remote)
        and not desc_hire
        and not desc_wfa
    ):
        evidence.append(foreign_parts[0])
        return (
            "INELIGIBLE",
            "FAIL",
            ["overseas / non-Canada location without Canadian hiring evidence"],
            evidence,
        )

    # Multi-location: Canada + foreign → eligible if Canada is an explicit option
    if canadian_parts and foreign_parts:
        evidence.append(canadian_parts[0])
        reasons.append("multi-location posting includes explicit Canadian location")
        return "ELIGIBLE", "PASS", reasons, evidence

    if loc_canada:
        evidence.append(_CANADA_WORD.search(location).group(0))  # type: ignore[union-attr]
        reasons.append("structured location names Canada")
        return "ELIGIBLE", "PASS", reasons, evidence

    if loc_city and ("hybrid" in modes or "onsite" in modes or "remote_province" in modes or "remote_canada" in modes):
        evidence.append(loc_city)
        if loc_us and not loc_canada:
            # e.g. "Toronto; San Francisco" without country clarity on which applies
            if foreign_parts and canadian_parts:
                return "ELIGIBLE", "PASS", [f"matched Canadian city: {loc_city}"], evidence
            if loc_overseas or (foreign_parts and not canadian_parts):
                return (
                    "UNCERTAIN",
                    "FLAG",
                    ["Canadian city mentioned alongside non-Canada geo — ambiguous"],
                    evidence,
                )
        return "ELIGIBLE", "PASS", [f"matched Canadian city: {loc_city}"], evidence

    if loc_province and (
        "remote_province" in modes or "hybrid" in modes or "onsite" in modes or "remote_canada" in modes
    ):
        evidence.append(loc_province)
        if loc_us and not loc_canada:
            return (
                "UNCERTAIN",
                "FLAG",
                ["Canadian province mentioned alongside US geo — ambiguous"],
                evidence,
            )
        return "ELIGIBLE", "PASS", [f"matched Canadian province: {loc_province}"], evidence

    if loc_na and not loc_us:
        evidence.append(_NORTH_AMERICA.search(location).group(0))  # type: ignore[union-attr]
        reasons.append("North America / NAMER location — country not explicit")
        return "UNCERTAIN", "FLAG", reasons, evidence

    # Description-only Canada hire phrases (never office mentions alone).
    if desc_hire:
        evidence.append(desc_hire.group(0))
        # If location is clearly overseas on-site, description hire phrase is contradictory → UNCERTAIN
        if foreign_parts and not canadian_parts and not loc_remote:
            return (
                "UNCERTAIN",
                "FLAG",
                ["Canada hire phrase in description conflicts with overseas location field"],
                evidence,
            )
        reasons.append("explicit Canada hiring eligibility in posting text")
        return "ELIGIBLE", "PASS", reasons, evidence

    # Genuine worldwide remote (not offices worldwide).
    # Structured US/overseas location fields win over marketing WFA copy.
    if desc_wfa and not us_only_hit:
        if (loc_us or (foreign_parts and not canadian_parts)) and not loc_canada:
            evidence.append(desc_wfa.group(0))
            evidence.append(location or (foreign_parts[0] if foreign_parts else "non-Canada location"))
            return (
                "UNCERTAIN",
                "FLAG",
                [
                    "work-from-anywhere language present but structured location "
                    "is US/overseas without Canada"
                ],
                evidence,
            )
        evidence.append(desc_wfa.group(0))
        reasons.append("genuine worldwide / work-from-anywhere remote")
        return "ELIGIBLE", "PASS", reasons, evidence

    # Offices worldwide alone is NOT eligibility.
    if offices_ww and not desc_wfa:
        evidence.append(offices_ww.group(0))
        return (
            "UNCERTAIN",
            "FLAG",
            ["offices/locations worldwide is not remote-work eligibility"],
            evidence,
        )

    # US-primary location without Canada evidence
    if (loc_us or (foreign_parts and not canadian_parts)) and not loc_canada:
        if loc_onsite or (desc_onsite and not loc_remote and not desc_remote):
            evidence.append(location or (foreign_parts[0] if foreign_parts else "US/overseas"))
            return (
                "INELIGIBLE",
                "FAIL",
                ["on-site / in-office outside Canada"],
                evidence,
            )
        if loc_remote or desc_remote or loc_us:
            evidence.append(location or "US remote")
            return (
                "UNCERTAIN",
                "FLAG",
                ["US-primary remote without explicit Canadian eligibility"],
                evidence,
            )

    if loc_remote or desc_remote:
        return (
            "UNCERTAIN",
            "FLAG",
            ["remote role; Canada eligibility not evidenced (unknown)"],
            evidence,
        )

    if loc_hybrid and not loc_city and not loc_province and not loc_canada:
        return (
            "UNCERTAIN",
            "FLAG",
            ["hybrid role without Canadian city/province in location"],
            evidence,
        )

    return (
        "UNCERTAIN",
        "FLAG",
        ["location/Canada eligibility not evidenced (unknown)"],
        evidence,
    )
