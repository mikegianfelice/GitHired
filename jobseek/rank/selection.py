"""Fair, deterministic selection of jobs to score."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_CANADA = re.compile(r"\bcanada\b|\bcanadian\b|worldwide|work\s+from\s+anywhere", re.I)
_REMOTE = re.compile(r"\bremote\b", re.I)


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


def _eligibility_hint(job: dict[str, Any]) -> int:
    """Higher is better for selection priority (not the final hard-filter class)."""
    blob = f"{job.get('location_raw') or ''}\n{(job.get('description') or '')[:2000]}"
    if _CANADA.search(blob):
        return 2
    if _REMOTE.search(blob):
        return 1
    return 0


def select_jobs_fairly(
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    max_per_company: int | None = None,
) -> list[dict[str, Any]]:
    """Round-robin across companies, preferring Canada-hinted and recent jobs.

    Deterministic: same input order → same output. Does not mutate scores.
    """
    if limit <= 0 or not candidates:
        return []
    if max_per_company is None:
        # Allow at least 1; widen slightly for large limits
        max_per_company = max(1, (limit + 4) // 5)

    # Group by company (stable order of first appearance after priority sort)
    ranked = sorted(
        candidates,
        key=lambda j: (
            -_eligibility_hint(j),
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
    # Round-robin until limit
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

    # If still short (few companies), fill from remaining ignoring per-company cap
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
