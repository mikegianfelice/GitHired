"""Field-aware engineering track and seniority matching.

Title phrases must match as contiguous role titles (with optional seniority
prefixes). Token-bag matching is intentionally not used — that previously
classified "UX Platform" + "Engineer" as Platform Engineer and "Data Center"
+ "Engineer" as Data Engineer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Adjacent families: selecting A may soft-match B at reduced score (not hard-filter).
ADJACENT_TRACKS: dict[str, list[str]] = {
    "data_engineering": ["analytics_engineering", "platform_engineering"],
    "analytics_engineering": ["data_engineering"],
    "platform_engineering": ["cloud_engineering", "devops_sre", "data_engineering"],
    "cloud_engineering": ["platform_engineering", "devops_sre"],
    "devops_sre": ["platform_engineering", "cloud_engineering"],
    "ai_engineering": ["ml_engineering", "software_engineering"],
    "ml_engineering": ["ai_engineering", "data_engineering"],
    "software_engineering": ["ai_engineering", "platform_engineering"],
    "forward_deployed": ["software_engineering", "ai_engineering"],
}

DEFAULT_TRACK_ALIASES: dict[str, list[str]] = {
    "software_engineering": [
        "Software Engineer",
        "Software Developer",
        "Full Stack Engineer",
        "Full-Stack Engineer",
        "Backend Engineer",
        "Frontend Engineer",
        "Front-End Engineer",
        "Fullstack Engineer",
    ],
    "ai_engineering": [
        "AI Engineer",
        "Applied AI Engineer",
        "Generative AI Engineer",
        "LLM Engineer",
        "AI Solutions Architect",
        "Solutions Architect AI",
        "AI Platform Engineer",
    ],
    "ml_engineering": [
        "Machine Learning Engineer",
        "ML Engineer",
        "MLOps Engineer",
        "Deep Learning Engineer",
    ],
    "data_engineering": [
        "Data Engineer",
        "Senior Data Engineer",
        "Staff Data Engineer",
        "Lead Data Engineer",
        "Principal Data Engineer",
        "Cloud Data Engineer",
        "Data Platform Engineer",
        "Data Engineering",
        "ETL Engineer",
        "ELT Engineer",
    ],
    "analytics_engineering": [
        "Analytics Engineer",
        "Senior Analytics Engineer",
        "Staff Analytics Engineer",
        "Analytics Engineering",
    ],
    "platform_engineering": [
        "Platform Engineer",
        "Software Platform Engineer",
        "Developer Platform Engineer",
        "Infrastructure Engineer",
        "Developer Experience Engineer",
        "DevEx Engineer",
    ],
    "cloud_engineering": [
        "Cloud Engineer",
        "Cloud Architect",
        "AWS Engineer",
        "Azure Engineer",
        "GCP Engineer",
        "Cloud Infrastructure Engineer",
    ],
    "devops_sre": [
        "DevOps Engineer",
        "Site Reliability Engineer",
        "SRE",
        "Reliability Engineer",
        "SRE Engineer",
    ],
    "forward_deployed": [
        "Forward Deployed Engineer",
        "Forward Deployed Software Engineer",
        "Deployment Engineer",
    ],
}

# Titles that must NOT match a track even if a substring overlaps.
_TRACK_EXCLUSIONS: dict[str, list[re.Pattern[str]]] = {
    "data_engineering": [
        re.compile(r"\bdata\s+cent(?:er|re)\b", re.I),
        re.compile(r"\bdata\s+scientist\b", re.I),
        re.compile(r"\bdata\s+science\b", re.I),
        re.compile(r"\bdata\s+analyst\b", re.I),
        re.compile(r"\bdata\s+annotation\b", re.I),
        re.compile(r"\bdata\s+entry\b", re.I),
        re.compile(r"\bdatabase\s+(?:administrator|admin|dba)\b", re.I),
        # Backend/database excellence without data-engineer phrasing
        re.compile(r"\bdatabase\s+excellence\b", re.I),
        re.compile(r"\bbackend\s+engineer,?\s*database\b", re.I),
    ],
    "analytics_engineering": [
        re.compile(r"\bdata\s+analyst\b", re.I),
        re.compile(r"\banalytics?\s+manager\b", re.I),
        re.compile(r"\bproduct\s+analytics\b", re.I),
    ],
    "platform_engineering": [
        re.compile(r"\b(?:ux|ui|mobile|ios|android|growth|external|client)\s+platform\b", re.I),
        re.compile(r"\bplatform\s+(?:product|pm|designer|design)\b", re.I),
        re.compile(r"\bconversation\s+platform\b", re.I),
        re.compile(r"\bendpoint\s+platform\b", re.I),
    ],
    "ai_engineering": [
        re.compile(r"\bai\s+(?:researcher|research|ethic|policy|product\s+manager)\b", re.I),
    ],
    "devops_sre": [
        # Keep SRE as its own family; no special exclusions beyond title precision
    ],
    "software_engineering": [
        re.compile(r"\b(?:sales|account|customer\s+success)\s+engineer\b", re.I),
    ],
}

# Optional seniority tokens allowed before a role phrase.
_SENIORITY_PREFIX = (
    r"(?:intern(?:ship)?|co-?op|student|junior|jr\.?|mid[\s-]?level|intermediate|"
    r"senior|sr\.?|staff|principal|lead|head\s+of|director|manager|chief)s?"
)

SENIORITY_PATTERNS: dict[str, re.Pattern[str]] = {
    "intern": re.compile(r"\b(?:intern(?:ship)?s?)\b", re.I),
    "coop": re.compile(r"\bco-?op\b", re.I),
    "student": re.compile(r"\b(?:student|university\s+hire)\b", re.I),
    "new_grad": re.compile(r"\b(?:new\s+grad(?:uate)?|graduate\s+program)\b", re.I),
    "junior": re.compile(r"\b(?:junior|jr\.?|entry[\s-]?level)\b", re.I),
    "mid": re.compile(r"\b(?:mid[\s-]?level|intermediate)\b", re.I),
    "senior": re.compile(r"\b(?:senior|sr\.?)\b", re.I),
    "staff": re.compile(r"\bstaff\b", re.I),
    "principal": re.compile(r"\b(?:principal|distinguished|fellow)\b", re.I),
    "lead": re.compile(r"\b(?:lead|manager|director|head\s+of)\b", re.I),
}

DEFAULT_SENIORITY_INCLUDE = ["mid", "senior", "staff", "principal", "lead"]
DEFAULT_SENIORITY_EXCLUDE = ["intern", "coop", "student", "new_grad", "junior"]

TRACK_LABELS: dict[str, str] = {
    "software_engineering": "Software Engineering",
    "ai_engineering": "AI Engineering",
    "ml_engineering": "Machine Learning Engineering",
    "data_engineering": "Data Engineering",
    "analytics_engineering": "Analytics Engineering",
    "platform_engineering": "Platform Engineering",
    "cloud_engineering": "Cloud Engineering",
    "devops_sre": "DevOps / SRE",
    "forward_deployed": "Forward Deployed Engineering",
}


@dataclass
class SeniorityGate:
    allowed: bool
    seniority: str | None = None
    reasons: list[str] = field(default_factory=list)


def seniority_gate(title: str, search_cfg: dict[str, Any]) -> SeniorityGate:
    """Hard-exclude student/intern tracks by default; unknown seniority passes."""
    seniority = detect_seniority(title)
    raw = search_cfg.get("seniority")
    if isinstance(raw, list):
        include = [str(s).casefold() for s in raw] or list(DEFAULT_SENIORITY_INCLUDE)
        exclude = list(DEFAULT_SENIORITY_EXCLUDE)
    elif isinstance(raw, dict):
        include = [str(s).casefold() for s in (raw.get("include") or DEFAULT_SENIORITY_INCLUDE)]
        exclude = [str(s).casefold() for s in (raw.get("exclude") or DEFAULT_SENIORITY_EXCLUDE)]
    else:
        include = list(DEFAULT_SENIORITY_INCLUDE)
        exclude = list(DEFAULT_SENIORITY_EXCLUDE)

    if seniority is None:
        return SeniorityGate(
            allowed=True,
            seniority=None,
            reasons=["seniority unknown — not rejected solely for missing keywords"],
        )
    if seniority.casefold() in exclude:
        return SeniorityGate(
            allowed=False,
            seniority=seniority,
            reasons=[f"seniority {seniority} excluded by config (student/entry tracks off by default)"],
        )
    if include and seniority.casefold() not in include:
        return SeniorityGate(
            allowed=True,
            seniority=seniority,
            reasons=[f"seniority {seniority} outside preferred include {include} — allowed as unknown-adjacent"],
        )
    return SeniorityGate(
        allowed=True,
        seniority=seniority,
        reasons=[f"seniority {seniority} within configured bands"],
    )


@dataclass
class TrackMatch:
    matched: bool
    tracks: list[str] = field(default_factory=list)
    matched_alias: str | None = None
    seniority: str | None = None
    seniority_ok: bool = True
    reasons: list[str] = field(default_factory=list)
    match_strength: str = "none"  # exact | adjacent | none
    primary_family: str | None = None


def _phrase_to_pattern(phrase: str) -> re.Pattern[str]:
    """Build a contiguous title matcher (word-bounded, not a token bag).

    Matches the role phrase anywhere in the title so
    ``Staff Software Engineer, Risk Data Engineering`` matches ``Data Engineering``.
    Seniority words may appear before the phrase but are not required.
    """
    tokens = [re.escape(t) for t in re.split(r"\s+", phrase.strip()) if t]
    if not tokens:
        return re.compile(r"(?!)")  # never matches
    body = r"[\s\-_/]+".join(tokens)
    # Word-boundary contiguous match; optional seniority immediately before.
    pattern = (
        rf"(?i)(?:(?<![a-z0-9])(?:{_SENIORITY_PREFIX})[\s,/\-]*)*"
        rf"(?<![a-z0-9]){body}(?![a-z0-9])"
    )
    return re.compile(pattern)


def _excluded(title: str, track: str) -> bool:
    for pattern in _TRACK_EXCLUSIONS.get(track) or []:
        if pattern.search(title or ""):
            return True
    return False


def _phrase_match(title: str, phrase: str) -> bool:
    """Contiguous role-phrase match (not token bag)."""
    if not title or not phrase:
        return False
    return bool(_phrase_to_pattern(phrase).search(title))


def detect_seniority(title: str) -> str | None:
    for level, pattern in SENIORITY_PATTERNS.items():
        if pattern.search(title or ""):
            return level
    return None


def title_candidates(search_cfg: dict[str, Any]) -> list[tuple[str | None, str]]:
    """Return (track_id_or_None, title_phrase) pairs for selected tracks."""
    out: list[tuple[str | None, str]] = []
    selected = list(search_cfg.get("tracks") or [])
    aliases = search_cfg.get("track_aliases") or {}
    if not isinstance(aliases, dict):
        aliases = {}
    for track in selected:
        phrases = aliases.get(track) or DEFAULT_TRACK_ALIASES.get(track) or []
        for phrase in phrases:
            out.append((str(track), str(phrase)))
    for phrase in search_cfg.get("custom_title_overrides") or []:
        out.append((None, str(phrase)))
    for phrase in list(search_cfg.get("target_titles") or []) + list(
        search_cfg.get("title_aliases") or []
    ):
        out.append((None, str(phrase)))
    if not out:
        for track, phrases in DEFAULT_TRACK_ALIASES.items():
            for phrase in phrases:
                out.append((track, phrase))
    # Longer phrases first so "Senior Data Engineer" wins over "Data Engineer"
    out.sort(key=lambda pair: -len(pair[1]))
    return out


def classify_title_family(title: str) -> tuple[str | None, str | None]:
    """Best-effort family for any title (ignores user track selection)."""
    best: tuple[str | None, str | None] = (None, None)
    best_len = -1
    for track, phrases in DEFAULT_TRACK_ALIASES.items():
        if _excluded(title, track):
            continue
        for phrase in phrases:
            if _phrase_match(title, phrase) and len(phrase) > best_len:
                best = (track, phrase)
                best_len = len(phrase)
    return best


def match_track(title: str, search_cfg: dict[str, Any]) -> TrackMatch:
    result = TrackMatch(matched=False)
    hits: list[str] = []
    matched_alias = None
    match_strength = "none"

    for track, phrase in title_candidates(search_cfg):
        if track and _excluded(title, track):
            continue
        if _phrase_match(title, phrase):
            result.matched = True
            match_strength = "exact"
            if matched_alias is None or len(phrase) > len(matched_alias):
                matched_alias = phrase
            if track and track not in hits:
                hits.append(track)

    # Adjacent soft match: only if no exact hit, for scoring — hard filter still fails.
    if not result.matched:
        selected = [str(t) for t in (search_cfg.get("tracks") or [])]
        family, alias = classify_title_family(title)
        if family and selected:
            for sel in selected:
                adjacent = ADJACENT_TRACKS.get(sel) or []
                if family == sel:
                    continue
                if family in adjacent:
                    result.primary_family = family
                    result.matched_alias = alias
                    result.match_strength = "adjacent"
                    result.reasons.append(
                        f"adjacent family {family} (not in selected tracks {selected})"
                    )
                    break
        result.seniority = detect_seniority(title)
        if not result.matched:
            result.reasons.append("title does not match configured engineering tracks")
            return result

    result.tracks = hits
    result.matched_alias = matched_alias
    result.match_strength = match_strength
    result.primary_family = hits[0] if hits else result.primary_family
    if result.matched:
        result.reasons.append(
            f"title matched track alias: {matched_alias}"
            + (f" ({', '.join(hits)})" if hits else "")
        )

    seniority = detect_seniority(title)
    result.seniority = seniority
    preferred = [str(s).casefold() for s in (search_cfg.get("seniority") or [])]
    if preferred and seniority and seniority.casefold() not in preferred:
        result.seniority_ok = False
        result.reasons.append(f"seniority {seniority} outside preferred bands {preferred}")
    elif seniority:
        result.reasons.append(f"detected seniority: {seniority}")
    return result


def title_matches_selected_tracks(title: str, search_cfg: dict[str, Any]) -> bool:
    """True when the title is an exact match for a user-selected track."""
    return match_track(title, search_cfg).matched
