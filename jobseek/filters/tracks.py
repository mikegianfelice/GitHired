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
    # Order matters: more specific student/intern patterns first
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


@dataclass
class SeniorityGate:
    allowed: bool
    seniority: str | None = None
    reasons: list[str] = field(default_factory=list)


def seniority_gate(title: str, search_cfg: dict[str, Any]) -> SeniorityGate:
    """Hard-exclude student/intern tracks by default; unknown seniority passes."""
    seniority = detect_seniority(title)
    raw = search_cfg.get("seniority")
    # Backward compatible: list → include list
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
        # Known seniority outside include (e.g. junior when include is mid+) already handled via exclude
        # If somehow not in exclude nor include, soft-allow with note
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
