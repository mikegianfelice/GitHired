"""Persist discovery timestamps across full dataset rebuilds.

CI discover runs start from an empty SQLite DB, so ``jobs.first_seen`` would
reset to the rebuild day even when the public stable id (company|title|url)
is unchanged. Merge earliest ``first_seen`` from a prior API snapshot (or
sidecar history) so MCP/REST timestamps stay continuous.

Semantics
---------
- ``first_seen``: first GitHired discovery of this stable posting id.
- ``last_verified``: last successful export/verification (not rewritten from prior).
- ``posted_date``: employer-published date when available (separate field).
- ``discovered_today``: derived from preserved ``first_seen`` vs export UTC date.
- Removed then reposted with a **new** apply URL → new stable id → new first_seen.
- Same stable id after a gap (reappear) → keep original first_seen.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def load_prior_first_seen(path: Path | None) -> dict[str, str]:
    """Map stable job id → earliest first_seen (YYYY-MM-DD) from a prior snapshot."""
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for job in payload.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        jid = str(job.get("id") or "").strip()
        day = _parse_day(job.get("first_seen"))
        if not jid or day is None:
            continue
        prev = out.get(jid)
        if prev is None or day.isoformat() < prev:
            out[jid] = day.isoformat()
    return out


def preserve_discovery_timestamps(
    api_jobs: list[dict[str, Any]],
    *,
    prior_first_seen: dict[str, str] | None = None,
    prior_snapshot_path: Path | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Rewrite first_seen / discovered_today using the earliest known discovery day.

    Does not modify ``last_verified``. Mutates and returns ``api_jobs``.
    """
    prior = dict(prior_first_seen or {})
    if prior_snapshot_path is not None:
        for jid, day in load_prior_first_seen(prior_snapshot_path).items():
            cur = prior.get(jid)
            if cur is None or day < cur:
                prior[jid] = day

    today = today or datetime.now(timezone.utc).date()
    for job in api_jobs:
        jid = str(job.get("id") or "").strip()
        current = _parse_day(job.get("first_seen"))
        prior_day = _parse_day(prior.get(jid)) if jid else None
        if prior_day and (current is None or prior_day < current):
            job["first_seen"] = prior_day.isoformat()
            current = prior_day
        if current is not None:
            job["discovered_today"] = current == today
        else:
            job["discovered_today"] = False
    return api_jobs
