"""Refresh README Top Paying section from SQLite (or a prior snapshot on failure)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jobseek.db.store import Database
from jobseek.showcase.readme import render_section, replace_section, update_readme_file
from jobseek.showcase.svg_dashboard import SVG_REL_PATH
from jobseek.showcase.top_paying import (
    DEFAULT_FX_USD_CAD,
    DEFAULT_LIMIT,
    DEFAULT_MAX_AGE_DAYS,
    ShowcaseJob,
    select_top_paying_jobs,
    snapshot_payload,
)

log = logging.getLogger(__name__)


def load_jobs_from_db(db: Database) -> list[dict[str, Any]]:
    rows = db._conn.execute(
        """
        SELECT *
        FROM jobs
        WHERE removed_at IS NULL
          AND (salary_min IS NOT NULL OR salary_max IS NOT NULL)
        """
    ).fetchall()
    return [dict(r) for r in rows]


def jobs_from_snapshot(payload: dict[str, Any]) -> list[ShowcaseJob]:
    out: list[ShowcaseJob] = []
    for item in payload.get("jobs") or []:
        out.append(
            ShowcaseJob(
                title=str(item["title"]),
                company=str(item["company"]),
                salary_min=float(item["salary_min"]),
                salary_max=float(item["salary_max"]),
                salary_currency=str(item["salary_currency"]),
                location_raw=str(item.get("location_raw") or ""),
                eligibility_label=str(
                    item.get("eligibility_label") or item.get("location_raw") or ""
                ),
                apply_url=str(item["apply_url"]),
                verified_at=str(item["verified_at"]),
                source=str(item.get("source") or ""),
                rank_cad=float(item["rank_cad"]),
                career_page_verified=bool(item.get("career_page_verified", False)),
                discovered_today=bool(item.get("discovered_today", False)),
                first_seen=str(item.get("first_seen") or item.get("verified_at") or ""),
                location_tag=str(item.get("location_tag") or item.get("location_raw") or ""),
                work_mode_tag=str(item.get("work_mode_tag") or ""),
            )
        )
    return out


def load_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read snapshot %s: %s", path, exc)
        return None
    if not isinstance(data, dict) or "jobs" not in data:
        return None
    return data


def write_snapshot(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def refresh_readme(
    *,
    readme_path: Path,
    snapshot_path: Path,
    db: Database | None = None,
    jobs_rows: list[dict[str, Any]] | None = None,
    limit: int = DEFAULT_LIMIT,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    fx_usd_cad: float = DEFAULT_FX_USD_CAD,
    now: datetime | None = None,
    allow_empty_overwrite: bool = False,
) -> dict[str, Any]:
    """Select jobs, update snapshot + README section.

    Failure / empty-handling policy:
    - On selection exception: keep last valid snapshot + README; return ``ok=False``.
    - On empty selection with a prior non-empty snapshot: preserve prior data and
      stamp (do not overwrite with empty / do not claim a fresh empty refresh)
      unless ``allow_empty_overwrite`` is True.
    - Per-job “Discovered Today” only when ``first_seen`` is today; otherwise
      the verified calendar date is shown. Failure paths never rewrite freshness.
    """
    now = now or datetime.now(timezone.utc)
    prior = load_snapshot(snapshot_path)
    result: dict[str, Any] = {
        "ok": True,
        "wrote_readme": False,
        "wrote_snapshot": False,
        "preserved_prior": False,
        "count": 0,
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "error": None,
    }

    try:
        if jobs_rows is None:
            if db is None:
                raise ValueError("db or jobs_rows required")
            jobs_rows = load_jobs_from_db(db)
        selected = select_top_paying_jobs(
            jobs_rows,
            limit=limit,
            max_age_days=max_age_days,
            fx_usd_cad=fx_usd_cad,
            now=now,
        )
    except Exception as exc:  # noqa: BLE001 — preserve last good public data
        log.exception("Showcase selection failed; preserving prior snapshot")
        result["ok"] = False
        result["error"] = str(exc)
        result["preserved_prior"] = prior is not None and bool(prior.get("jobs"))
        if prior:
            result["count"] = int(prior.get("count") or len(prior.get("jobs") or []))
            result["generated_at"] = str(prior.get("generated_at") or result["generated_at"])
        return result

    if (
        not selected
        and prior
        and prior.get("jobs")
        and not allow_empty_overwrite
    ):
        result["preserved_prior"] = True
        result["count"] = int(prior.get("count") or len(prior["jobs"]))
        result["generated_at"] = str(prior.get("generated_at") or result["generated_at"])
        result["ok"] = True
        return result

    payload = snapshot_payload(selected, generated_at=now, fx_usd_cad=fx_usd_cad)
    write_snapshot(snapshot_path, payload)
    result["wrote_snapshot"] = True
    result["count"] = len(selected)

    if readme_path.is_file():
        svg_path = readme_path.parent / SVG_REL_PATH
        changed = update_readme_file(
            readme_path,
            selected,
            generated_at=now,
            svg_path=svg_path,
            today=now,
        )
        result["wrote_readme"] = changed
    else:
        result["wrote_readme"] = False

    return result


def render_from_snapshot(snapshot_path: Path) -> str:
    payload = load_snapshot(snapshot_path)
    if not payload:
        return render_section([])
    jobs = jobs_from_snapshot(payload)
    generated = None
    raw = payload.get("generated_at")
    if raw:
        try:
            generated = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            generated = None
    return render_section(jobs, generated_at=generated, today=generated)


def apply_snapshot_to_readme(readme_path: Path, snapshot_path: Path) -> bool:
    payload = load_snapshot(snapshot_path)
    jobs = jobs_from_snapshot(payload) if payload else []
    generated = None
    if payload and payload.get("generated_at"):
        try:
            generated = datetime.fromisoformat(
                str(payload["generated_at"]).replace("Z", "+00:00")
            )
        except ValueError:
            generated = None
    # When re-applying a preserved snapshot, do NOT flip cards to "Discovered Today"
    # based on the wall clock — keep the stored discovered_today flags.
    svg_path = readme_path.parent / SVG_REL_PATH
    return update_readme_file(
        readme_path,
        jobs,
        generated_at=generated,
        svg_path=svg_path,
        today=generated,
    )
