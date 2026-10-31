"""Deterministic scoring fingerprint — invalidates stale scores on config change."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from jobseek.rank.scorer import SCORER_VERSION


def scoring_fingerprint(
    search_cfg: dict[str, Any],
    profile: dict[str, Any] | None = None,
    *,
    scorer_version: str = SCORER_VERSION,
) -> str:
    """Hash of knobs that must force a rescore when they change.

    Includes scorer version, tracks/seniority/location/salary gates, and profile
    skills/experience used by the deterministic scorer. Description changes are
    tracked separately via ``description_hash`` on job_scores.
    """
    profile = profile or {}
    skills = profile.get("skills") or {}
    exp = profile.get("experience") or {}
    payload = {
        "scorer": scorer_version,
        "tracks": search_cfg.get("tracks"),
        "seniority": search_cfg.get("seniority"),
        "location": search_cfg.get("location"),
        "salary": search_cfg.get("salary"),
        "skills": skills,
        "experience_years": exp.get("years"),
        "strong_domains": exp.get("strong_domains"),
        "adjacent_domains": exp.get("adjacent_domains"),
    }
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
