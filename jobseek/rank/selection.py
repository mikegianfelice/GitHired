"""Fair, deterministic selection of jobs to score."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


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


def _location_priority(job: dict[str, Any]) -> int:
    """Cheap pre-filter priority from structured location only (not description 'on')."""
    loc = (job.get("location_raw") or "").casefold()
    if not loc:
        return 0
    if "canada" in loc or "canadian" in loc:
        return 3
    for city in (
        "toronto",
        "vancouver",
        "montreal",
        "ottawa",
        "calgary",
        "edmonton",
        "waterloo",
        "kitchener",
        "halifax",
        "mississauga",
    ):
        if city in loc:
            return 3
    if "namer" in loc or "north america" in loc:
        return 2
    if "remote" in loc:
        return 1
    return 0


def select_jobs_fairly(
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    max_per_company: int | None = None,
    title_priority: Callable[[dict[str, Any]], int] | None = None,
) -> list[dict[str, Any]]:
    """Round-robin across companies, preferring track-relevant and Canada-hinted jobs.

    Deterministic: same input order → same output. Does not mutate scores.
    """
    if limit <= 0 or not candidates:
        return []
    if max_per_company is None:
        max_per_company = max(1, (limit + 4) // 5)

    def _title_pri(job: dict[str, Any]) -> int:
        if title_priority is None:
            return 0
        return int(title_priority(job) or 0)

    ranked = sorted(
        candidates,
        key=lambda j: (
            -_title_pri(j),
            -_location_priority(j),
            -_parse_ts(j.get("posted_date") or j.get("first_seen") or j.get("last_seen")),
            str(j.get("company") or "").casefold(),
            int(j.get("id") or 0),
        ),
    )

    by_company: dict[str, list[dict[str, Any]]] = {}
    company_order: list[str] = []
    for job in ranked:
        company = str(job.get("company") or "Unknown")
        if company not in by_company:
            by_company[company] = []
            company_order.append(company)
        by_company[company].append(job)

    selected: list[dict[str, Any]] = []
    counts = {c: 0 for c in company_order}
    progressed = True
    while len(selected) < limit and progressed:
        progressed = False
        for company in company_order:
            if len(selected) >= limit:
                break
            if counts[company] >= max_per_company:
                continue
            bucket = by_company[company]
            if counts[company] >= len(bucket):
                continue
            selected.append(bucket[counts[company]])
            counts[company] += 1
            progressed = True

    if len(selected) < limit:
        selected_ids = {int(j["id"]) for j in selected if j.get("id") is not None}
        for job in ranked:
            if len(selected) >= limit:
                break
            jid = job.get("id")
            if jid is not None and int(jid) in selected_ids:
                continue
            selected.append(job)
            if jid is not None:
                selected_ids.add(int(jid))

    return selected[:limit]
