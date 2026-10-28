"""Candidate profile completeness checks (no fabricated skills)."""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER = re.compile(
    r"\[YOUR_[A-Z0-9_]+\]|YOUR_NAME|TODO|TBD|placeholder|example\.com",
    re.I,
)


def profile_warnings(profile: dict[str, Any]) -> list[str]:
    """Return human-readable warnings when the profile is incomplete for skill ranking."""
    warnings: list[str] = []
    skills = profile.get("skills") or {}
    primary = skills.get("primary") or []
    secondary = skills.get("secondary") or []
    domain = skills.get("domain") or []

    def _empty(val: Any) -> bool:
        if val is None:
            return True
        if isinstance(val, (list, dict, str)) and len(val) == 0:
            return True
        return False

    if _empty(primary) and _empty(secondary) and _empty(domain):
        warnings.append(
            "profile skills are empty — skill overlap scoring is neutral; "
            "title/location ranking still works. Edit config/profile.yaml."
        )

    identity = profile.get("identity") or {}
    name = str(identity.get("name") or "")
    if not name or _PLACEHOLDER.search(name):
        warnings.append("profile identity.name looks like a placeholder")

    blob = str(profile)
    if _PLACEHOLDER.search(blob):
        warnings.append("profile contains placeholder tokens (e.g. [YOUR_NAME])")

    return warnings


def is_profile_complete_for_skills(profile: dict[str, Any]) -> bool:
    skills = profile.get("skills") or {}
    for key in ("primary", "secondary", "domain"):
        val = skills.get(key) or []
        if isinstance(val, list) and any(str(x).strip() and not _PLACEHOLDER.search(str(x)) for x in val):
            return True
        if isinstance(val, str) and val.strip() and not _PLACEHOLDER.search(val):
            return True
    return False
