"""Engineering track and seniority matching."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TRACK_ALIASES: dict[str, list[str]] = {
    "software_engineering": [
        "Software Engineer",
        "Software Developer",
        "Full Stack Engineer",
        "Backend Engineer",
        "Frontend Engineer",
        "Full-Stack Engineer",
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
        "Analytics Engineer",
    ],
    "platform_engineering": [
        "Platform Engineer",
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
    ],
    "devops_sre": [
        "DevOps Engineer",
        "Site Reliability Engineer",
        "SRE",
        "Reliability Engineer",
    ],
    "forward_deployed": [
        "Forward Deployed Engineer",
        "Forward Deployed Software Engineer",
        "Deployment Engineer",
        "Solutions Engineer Technical",
    ],
}

SENIORITY_PATTERNS: dict[str, re.Pattern[str]] = {
    "intern": re.compile(r"\b(?:intern|internship|co-?op)\b", re.I),
    "junior": re.compile(r"\b(?:junior|jr\.?|entry[\s-]?level|new\s+grad)\b", re.I),
    "mid": re.compile(r"\b(?:mid[\s-]?level|intermediate)\b", re.I),
    "senior": re.compile(r"\b(?:senior|sr\.?)\b", re.I),
    "staff": re.compile(r"\bstaff\b", re.I),
    "principal": re.compile(r"\b(?:principal|distinguished|fellow)\b", re.I),
    "lead": re.compile(r"\b(?:lead|manager|director|head\s+of)\b", re.I),
}


@dataclass
class TrackMatch:
    matched: bool
    tracks: list[str] = field(default_factory=list)
    matched_alias: str | None = None
    seniority: str | None = None
    seniority_ok: bool = True
    reasons: list[str] = field(default_factory=list)


def _phrase_match(title: str, phrase: str) -> bool:
    title_l = (title or "").casefold()
    cand = str(phrase).casefold()
    if cand in title_l:
        return True
    tokens = [t for t in re.split(r"\s+", cand) if t]
    return bool(tokens) and all(tok in title_l for tok in tokens)


def detect_seniority(title: str) -> str | None:
    for level, pattern in SENIORITY_PATTERNS.items():
        if pattern.search(title or ""):
            return level
    return None


def title_candidates(search_cfg: dict[str, Any]) -> list[tuple[str | None, str]]:
    """Return (track_id_or_None, title_phrase) pairs."""
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
    # Legacy flat lists
    for phrase in list(search_cfg.get("target_titles") or []) + list(
        search_cfg.get("title_aliases") or []
    ):
        out.append((None, str(phrase)))
    # If nothing configured, use all default tracks
    if not out:
        for track, phrases in DEFAULT_TRACK_ALIASES.items():
            for phrase in phrases:
                out.append((track, phrase))
    return out


def match_track(title: str, search_cfg: dict[str, Any]) -> TrackMatch:
    result = TrackMatch(matched=False)
    hits: list[str] = []
    matched_alias = None
    for track, phrase in title_candidates(search_cfg):
        if _phrase_match(title, phrase):
            result.matched = True
            matched_alias = phrase
            if track and track not in hits:
                hits.append(track)
    result.tracks = hits
    result.matched_alias = matched_alias
    if result.matched:
        result.reasons.append(
            f"title matched track alias: {matched_alias}"
            + (f" ({', '.join(hits)})" if hits else "")
        )
    else:
        result.reasons.append("title does not match configured engineering tracks")

    seniority = detect_seniority(title)
    result.seniority = seniority
    preferred = [str(s).casefold() for s in (search_cfg.get("seniority") or [])]
    if preferred and seniority and seniority.casefold() not in preferred:
        # Soft flag — still matched track; seniority used for scoring
        result.seniority_ok = False
        result.reasons.append(
            f"seniority {seniority} outside preferred bands {preferred}"
        )
    elif seniority:
        result.reasons.append(f"detected seniority: {seniority}")
    return result
