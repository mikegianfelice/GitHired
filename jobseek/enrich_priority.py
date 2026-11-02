"""Deterministic enrichment priority from listing metadata (no LLM, no HTTP)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from jobseek.filters.tracks import (
    detect_seniority,
    match_track,
    title_matches_selected_tracks,
)

_BANKING_NOISE = re.compile(
    r"\b("
    r"teller|customer\s+service|personal\s+banker|branch\s+advisor|"
    r"mortgage\s+specialist|financial\s+advisor|wealth\s+advisor|"
    r"call\s+centre|call\s+center|cashier|sales\s+associate|"
    r"receptionist|administrative\s+assistant|bank\s+ambassador"
    r")\b",
    re.I,
)


def priority_fingerprint(search_cfg: dict[str, Any], profile: dict[str, Any] | None = None) -> str:
    """Hash of knobs that must force enrich_priority recalculation."""
    profile = profile or {}
    skills = profile.get("skills") or {}
    payload = {
        "tracks": search_cfg.get("tracks"),
        "seniority": search_cfg.get("seniority"),
        "location": search_cfg.get("location"),
        "salary": search_cfg.get("salary"),
        "skills_primary": skills.get("primary"),
        "experience_years": (profile.get("experience") or {}).get("years"),
    }
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _parse_ts(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        raw = str(value).replace("Z", "+00:00")
        if "T" not in raw and len(raw) == 10:
            dt = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return 0.0


def _location_boost(location_raw: str | None, search_cfg: dict[str, Any]) -> int:
    """Listing-only geo hint. Missing location is neutral (still enrich if title matches)."""
    loc = (location_raw or "").strip()
    if not loc:
        return 5  # insufficient info — keep relevant titles in the race
    loc_cf = loc.casefold()
    # Multi-location stubs still worth enriching for geo resolution.
    if re.match(r"^\d+\s+locations?$", loc_cf):
        return 25
    score = 0
    if "canada" in loc_cf or "canadian" in loc_cf:
        score += 40
    loc_cfg = search_cfg.get("location") or {}
    for city in loc_cfg.get("cities") or []:
        if str(city).casefold() in loc_cf:
            score += 35
            break
    for prov in loc_cfg.get("provinces") or []:
        token = str(prov).casefold()
        if len(token) >= 2 and token in loc_cf:
            score += 20
            break
    modes = {str(m).casefold() for m in (loc_cfg.get("modes") or [])}
    if "remote" in loc_cf and (
        "remote_canada" in modes or "remote_province" in modes or not modes
    ):
        score += 30
    if "hybrid" in loc_cf and ("hybrid" in modes or not modes):
        score += 20
    # Clear non-Canada signals → low (but title can still salvage slightly).
    if any(
        x in loc_cf
        for x in ("united states", "usa only", "us only", "u.s. only", "india", "philippines")
    ) and "canada" not in loc_cf:
        score = min(score, 5)
    return score


def _seniority_boost(title: str, search_cfg: dict[str, Any]) -> int:
    sen = detect_seniority(title)
    preferred = {
        str(x).casefold()
        for x in ((search_cfg.get("seniority") or {}).get("include") or [])
    }
    excluded = {
        str(x).casefold()
        for x in ((search_cfg.get("seniority") or {}).get("exclude") or [])
    }
    if sen and sen.casefold() in excluded:
        return -80
    if not preferred:
        return 10
    if not sen:
        return 15  # unknown seniority allowed by default policy
    if sen.casefold() in preferred:
        return 25
    return -40


def _salary_boost(job: dict[str, Any], search_cfg: dict[str, Any]) -> int:
    """Missing salary is neutral — never treat as below floor."""
    floors = ((search_cfg.get("salary") or {}).get("floors") or {})
    floor_cad = floors.get("CAD") or floors.get("cad")
    raw = (job.get("salary_raw") or "").strip()
    smin = job.get("salary_min")
    smax = job.get("salary_max")
    if not raw and smin is None and smax is None:
        return 0
    try:
        from jobseek.filters.salary import salary_label_for_job

        info = salary_label_for_job(job, floors=floors if floors else None)
        if info.confidence == "below_floor":
            return -60
        if info.confidence == "verified":
            return 20
    except Exception:  # noqa: BLE001
        pass
    if floor_cad and smax is not None:
        try:
            if float(smax) < float(floor_cad) * 0.85:
                return -50
            return 15
        except (TypeError, ValueError):
            return 0
    return 5


def _freshness_boost(job: dict[str, Any]) -> int:
    ts = _parse_ts(job.get("posted_date") or job.get("first_seen") or job.get("last_seen"))
    if ts <= 0:
        return 0
    age_days = max(0.0, (datetime.now(timezone.utc).timestamp() - ts) / 86400.0)
    if age_days <= 3:
        return 20
    if age_days <= 14:
        return 10
    if age_days <= 45:
        return 0
    return -15


def compute_enrich_priority(
    job: dict[str, Any],
    search_cfg: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> int:
    """Return integer priority (higher = enrich sooner). Deterministic."""
    title = str(job.get("title") or "")
    track = match_track(title, search_cfg)
    if _BANKING_NOISE.search(title) and not track.matched:
        return 1  # clearly incompatible customer-facing roles

    if not track.matched:
        # Eventually processed (anti-starvation) but far behind relevant titles.
        base = 8 + _freshness_boost(job) // 5
        return max(1, min(base, 20))

    score = 500  # track match floor
    if track.match_strength == "exact":
        score += 80
    elif track.match_strength == "adjacent":
        score += 30
    score += _location_boost(job.get("location_raw"), search_cfg)
    score += _seniority_boost(title, search_cfg)
    score += _salary_boost(job, search_cfg)
    score += _freshness_boost(job)
    # Soft skill keyword hints from listing title only (never invent).
    skills = ((profile or {}).get("skills") or {}).get("primary") or []
    title_cf = title.casefold()
    for sk in skills[:8]:
        token = str(sk).casefold().strip()
        if len(token) >= 3 and token in title_cf:
            score += 8
    return max(1, int(score))


def fair_select_for_enrichment(
    ranked_rows: list[dict[str, Any]],
    *,
    limit: int,
    max_per_company: int | None = None,
    min_priority: int = 0,
) -> list[dict[str, Any]]:
    """Round-robin across employers so one bank cannot monopolize a batch.

    Rows below ``min_priority`` are excluded — never pad a batch with clearly
    irrelevant jobs just to hit ``limit``.
    """
    if limit <= 0 or not ranked_rows:
        return []
    eligible = [
        r for r in ranked_rows if int(r.get("enrich_priority") or 0) >= int(min_priority)
    ]
    if not eligible:
        return []
    if max_per_company is None:
        # Aim for diversity: at least ~5 companies in a 50-job batch when possible.
        max_per_company = max(3, (limit + 4) // 5)

    by_co: dict[str, list[dict[str, Any]]] = {}
    for row in eligible:
        co = str(row.get("company") or "").strip() or "?"
        by_co.setdefault(co, []).append(row)

    # Within company already priority-sorted by caller.
    companies = sorted(by_co.keys(), key=lambda c: (-(by_co[c][0].get("enrich_priority") or 0), c.casefold()))
    cursors = {c: 0 for c in companies}
    taken = {c: 0 for c in companies}
    out: list[dict[str, Any]] = []
    while len(out) < limit:
        progressed = False
        for co in companies:
            if len(out) >= limit:
                break
            if taken[co] >= max_per_company:
                continue
            idx = cursors[co]
            rows = by_co[co]
            if idx >= len(rows):
                continue
            out.append(rows[idx])
            cursors[co] = idx + 1
            taken[co] += 1
            progressed = True
        if not progressed:
            # Soften cap to drain remaining high-priority roles (anti-starvation within batch).
            if max_per_company < limit:
                max_per_company = limit
                continue
            break
    return out
