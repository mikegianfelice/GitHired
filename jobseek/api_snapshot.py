"""API/MCP dataset snapshot — same Canada eligibility as the public shortlist.

Unlike ``site/jobs.json``, this snapshot may include a truncated description
excerpt for ``GET /api/v1/jobs/{id}``. It still never exports profiles, emails,
phones, credentials, or private ranking fingerprints.

Salary fields are **employer-advertised annual base only** — never estimates.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jobseek.public_shortlist.export import (
    DEFAULT_LIMIT,
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_USD_TO_CAD,
    PUBLIC_SEARCH,
    PublicJob,
    _extract_technologies,
    select_public_jobs,
)

API_SCHEMA_VERSION = 1
# Keep Worker bundles under Cloudflare free-tier compressed size limits.
MAX_DESCRIPTION_EXCERPT = 900
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(text: str) -> str:
    plain = _TAG.sub(" ", html.unescape(text or ""))
    return _WS.sub(" ", plain).strip()


def description_excerpt(text: str | None, *, limit: int = MAX_DESCRIPTION_EXCERPT) -> str | None:
    plain = strip_html(text or "")
    if not plain:
        return None
    if len(plain) <= limit:
        return plain
    return plain[: limit - 1].rstrip() + "…"


def _index_raw_jobs(jobs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map public stable id → raw job row for enrichment fields."""
    from jobseek.public_shortlist.export import _stable_id
    from jobseek.filters.apply_url import select_actionable_apply_url

    out: dict[str, dict[str, Any]] = {}
    for job in jobs:
        title = str(job.get("title") or "").strip()
        company = str(job.get("company") or "").strip()
        apply_url, verdict = select_actionable_apply_url(
            primary=job.get("apply_url") or job.get("url"),
            fallbacks=[job.get("url")],
        )
        if not title or not company or not apply_url or not verdict.actionable:
            continue
        clean = apply_url.split("?")[0] if "utm_" in apply_url.casefold() else apply_url
        out[_stable_id(company, title, clean)] = job
    return out


def build_api_job(public: PublicJob, raw: dict[str, Any] | None) -> dict[str, Any]:
    """Merge public card fields with API-only enrichment."""
    raw = raw or {}
    full_plain = strip_html(str(raw.get("description") or ""))
    desc = description_excerpt(str(raw.get("description") or "") or None)
    # Prefer full-description extraction (public shortlist already does this);
    # fall back to public tags, then excerpt-only re-extract.
    tech = list(public.technologies)
    if full_plain:
        tech = _extract_technologies(public.title, public.location, full_plain) or tech
    elif desc:
        tech = _extract_technologies(public.title, public.location, desc) or tech
    return {
        "id": public.id,
        "title": public.title,
        "company": public.company,
        "location": public.location,
        "province": public.province,
        "work_arrangement": public.work_arrangement,
        "remote_scope": public.remote_scope,
        "seniority": public.seniority,
        "track": public.track,
        "salary_min": public.salary_min,
        "salary_max": public.salary_max,
        "salary_currency": public.salary_currency,
        "salary_available": public.salary_available,
        "salary_max_cad": public.salary_max_cad,
        "salary_period": "annual" if public.salary_available else None,
        "salary_kind": "advertised_base" if public.salary_available else "undisclosed",
        "apply_url": public.apply_url,
        "verified": public.verified,
        "first_seen": public.first_seen,
        "last_verified": public.last_verified,
        "discovered_today": public.discovered_today,
        "technologies": tech,
        "source": public.source,
        "description_excerpt": desc,
        "description_complete": bool(int(raw.get("description_complete") or 0)) if raw else public.verified,
    }


def build_api_snapshot(
    raw_jobs: list[dict[str, Any]],
    *,
    limit: int = DEFAULT_LIMIT,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    generated_at: datetime | None = None,
    repo_url: str = "https://github.com/mikegianfelice/GitHired",
) -> dict[str, Any]:
    """Build the versioned API/MCP dataset from DB-shaped job rows."""
    generated_at = generated_at or datetime.now(timezone.utc)
    selected = select_public_jobs(
        raw_jobs,
        limit=limit,
        max_age_days=max_age_days,
        now=generated_at,
        search_cfg=PUBLIC_SEARCH,
        require_complete=True,
    )
    by_id = _index_raw_jobs(raw_jobs)
    api_jobs = [build_api_job(j, by_id.get(j.id)) for j in selected]

    companies: dict[str, int] = {}
    remote = 0
    with_salary = 0
    for j in api_jobs:
        companies[j["company"]] = companies.get(j["company"], 0) + 1
        if j["work_arrangement"] == "remote":
            remote += 1
        if j["salary_available"]:
            with_salary += 1

    payload = {
        "schema_version": API_SCHEMA_VERSION,
        "dataset_id": hashlib.sha256(
            json.dumps(
                [j["id"] for j in api_jobs],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16],
        "generated_at": generated_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "githired-api-snapshot",
        "limit": int(limit),
        "count": len(api_jobs),
        "usd_to_cad": DEFAULT_USD_TO_CAD,
        "repo_url": repo_url,
        "website_url": "https://githired.ca",
        "api_base_url": "https://api.githired.ca",
        "salary_policy": {
            "filter_on": "advertised_annual_base_only",
            "estimates": False,
            "currencies": ["CAD", "USD"],
            "usd_to_cad": DEFAULT_USD_TO_CAD,
            "note": (
                "Salary filters use employer-advertised annual base pay only. "
                "Missing or non-annual compensation is treated as undisclosed — never inferred."
            ),
        },
        "eligibility": {
            "geography": "Canada-eligible only (hard-filter ELIGIBLE)",
            "ineligible_excluded": True,
            "uncertain_excluded": True,
            "remote_scope": "canada | province | local | unspecified — never overclaim nationwide",
        },
        "stats": {
            "total_jobs": len(api_jobs),
            "total_companies": len(companies),
            "remote_jobs": remote,
            "jobs_with_advertised_salary": with_salary,
        },
        "companies": [
            {"name": name, "active_jobs": count}
            for name, count in sorted(companies.items(), key=lambda kv: (-kv[1], kv[0].casefold()))
        ],
        "disclaimer": (
            "Canada-eligible engineering listings from employer ATS boards. "
            "Not a complete labour-market census. Salaries are advertised annual base only. "
            "Descriptions are truncated excerpts for API detail views."
        ),
        "jobs": api_jobs,
    }
    return payload


def write_api_snapshot(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return {
        "ok": True,
        "path": str(path),
        "count": payload.get("count"),
        "dataset_id": payload.get("dataset_id"),
        "generated_at": payload.get("generated_at"),
        "bytes": len(text.encode("utf-8")),
    }
