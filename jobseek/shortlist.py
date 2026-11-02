"""Confirmed-match definition shared by jobs, digest, refresh, and TTF10.

Geographic eligibility alone is never enough. A confirmed match must pass the
full hard-filter gate (track, seniority, Canada geo, salary floor, apply URL).
"""

from __future__ import annotations

import json
from typing import Any


def parse_hard_filter(row: dict[str, Any] | None) -> dict[str, Any]:
    """Extract hard_filter dict from a scored job row."""
    if not row:
        return {}
    hf = row.get("hard_filter_json")
    if isinstance(hf, dict):
        return hf
    if isinstance(hf, str) and hf.strip():
        try:
            parsed = json.loads(hf)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def is_confirmed_match(
    row: dict[str, Any],
    *,
    min_score: float | None = None,
    require_complete: bool = True,
) -> bool:
    """True when a job belongs on the default confirmed shortlist.

    Requires:
    - description complete (unless require_complete=False)
    - hard-filter verdict == PASS
    - geographic eligibility == ELIGIBLE
    - relevance is not NO_MATCH (PASS already implies this for current scorers)
    - overall score >= min_score when provided
    """
    if require_complete and not int(row.get("description_complete") or 0):
        return False
    if str(row.get("score_kind") or "").lower() == "provisional":
        return False
    overall = row.get("overall")
    if min_score is not None:
        try:
            if overall is None or float(overall) < float(min_score):
                return False
        except (TypeError, ValueError):
            return False
    hf = parse_hard_filter(row)
    verdict = str(hf.get("verdict") or "").upper()
    eligibility = str(hf.get("eligibility") or "UNCERTAIN").upper()
    relevance = str(hf.get("relevance") or "").upper()
    if verdict != "PASS":
        return False
    if eligibility != "ELIGIBLE":
        return False
    if relevance == "NO_MATCH" or hf.get("title_match") is False:
        return False
    return True


def hard_filter_verdict(row: dict[str, Any]) -> str:
    return str(parse_hard_filter(row).get("verdict") or "").upper()
