"""Optional Freehire.me public API adapter (no API key, no Bun).

Disabled by default via ``sources.freehire: false``. Freehire is a best-effort
aggregator; affiliate/WhatJobs-only apply URLs are never treated as confirmed
actionable recommendations. Direct employer ATS URLs from the payload are kept
as-is — we never invent or guess employer URLs, and we do not follow untrusted
redirect chains.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

from jobseek.adapters.base import AdapterResult
from jobseek.filters.apply_url import select_actionable_apply_url
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob

DEFAULT_BASE_URL = "https://freehire.me"
AGENT_SEARCH_PATH = "/api/v1/agent/jobs/search"
DEFAULT_UA = "GitHired-jobseek/0.2 (freehire; +personal job search)"


def freehire_base_url() -> str:
    raw = (os.environ.get("FREEHIRE_API_URL") or "").strip()
    return (raw or DEFAULT_BASE_URL).rstrip("/")


def normalize_freehire_job(item: dict[str, Any]) -> tuple[RawJob | None, dict[str, Any]]:
    """Normalize one Freehire payload into a RawJob.

    Returns ``(job_or_none, meta)`` where meta includes URL classification so
    callers can count affiliate rejects / review-only rows.
    """
    meta: dict[str, Any] = {
        "url_kind": "missing",
        "actionable": False,
        "affiliate": False,
        "skipped": False,
        "reason": "",
    }
    if not isinstance(item, dict):
        meta["skipped"] = True
        meta["reason"] = "non-object payload"
        return None, meta

    title = str(item.get("title") or "").strip()
    company = str(item.get("company") or "").strip() or "Unknown"
    slug = str(item.get("public_slug") or item.get("slug") or "").strip() or None
    external_url = (item.get("url") or "").strip() or None
    provenance_url = f"{freehire_base_url()}/jobs/{slug}" if slug else None

    apply_url, verdict = select_actionable_apply_url(
        primary=external_url,
        fallbacks=[provenance_url] if provenance_url else None,
    )
    meta["url_kind"] = verdict.kind
    meta["actionable"] = verdict.actionable
    meta["affiliate"] = verdict.kind == "affiliate"
    meta["reason"] = verdict.reason
    meta["host"] = verdict.host

    if not title:
        meta["skipped"] = True
        meta["reason"] = "missing title"
        return None, meta

    location = (item.get("location") or "").strip() or None
    work_mode = (item.get("work_mode") or "").strip() or None
    if work_mode and location:
        if work_mode.casefold() not in location.casefold():
            location = f"{location}; {work_mode}"
    elif work_mode and not location:
        location = work_mode

    countries = item.get("countries") if isinstance(item.get("countries"), list) else []
    cities = item.get("cities") if isinstance(item.get("cities"), list) else []
    if countries and location and "canada" not in location.casefold() and "ca" in {
        str(c).casefold() for c in countries
    }:
        location = f"{location}; Canada"

    description = item.get("description")
    if isinstance(description, str):
        description = description.strip() or None
    else:
        description = None

    posted = item.get("posted_at") or item.get("created_at")
    posted_date = None
    if isinstance(posted, str) and len(posted) >= 10 and posted[0:4].isdigit():
        posted_date = posted[:10]

    enrichment = item.get("enrichment") if isinstance(item.get("enrichment"), dict) else {}
    salary_min = enrichment.get("salary_min")
    salary_max = enrichment.get("salary_max")
    salary_currency = enrichment.get("salary_currency")
    salary_raw = None
    if salary_min is not None or salary_max is not None:
        lo = salary_min if salary_min is not None else salary_max
        hi = salary_max if salary_max is not None else salary_min
        salary_raw = f"{salary_currency or ''} {lo}-{hi}".strip()

    # Provenance: keep Freehire listing URL as `url` when apply is affiliate so
    # the row remains findable; actionable apply_url only when direct.
    listing_url = provenance_url or external_url or ""
    if verdict.actionable and apply_url:
        job_url = apply_url
        job_apply = apply_url
        source = "freehire"
    elif verdict.kind == "affiliate":
        # Review-only: stored separately from confirmed recommendations.
        job_url = listing_url or external_url or ""
        job_apply = external_url
        source = "freehire_review"
    else:
        # Unverified / aggregator — review bucket; not confirmed-actionable.
        job_url = listing_url or external_url or ""
        job_apply = apply_url or external_url
        source = "freehire_review"

    if not job_url:
        meta["skipped"] = True
        meta["reason"] = "missing URL"
        return None, meta

    # ats_provider preserves upstream ATS name when Freehire exposes it
    upstream = str(item.get("source") or "").strip().lower() or None
    ats_provider = upstream if upstream and upstream not in ("freehire", "whatjobs") else "freehire"
    ats_job_id = str(item.get("external_id") or slug or "").strip() or None

    job = RawJob(
        company=company,
        title=title,
        url=job_url,
        apply_url=job_apply,
        source=source,
        ats_provider=ats_provider,
        ats_job_id=ats_job_id,
        location_raw=location,
        description=description,
        salary_raw=salary_raw,
        salary_min=float(salary_min) if isinstance(salary_min, (int, float)) else None,
        salary_max=float(salary_max) if isinstance(salary_max, (int, float)) else None,
        salary_currency=str(salary_currency).upper() if salary_currency else None,
        posted_date=posted_date,
        raw_payload={
            "freehire": item,
            "apply_url_verdict": {
                "kind": verdict.kind,
                "host": verdict.host,
                "actionable": verdict.actionable,
                "reason": verdict.reason,
            },
            "cities": cities,
            "countries": countries,
            "freehire_slug": slug,
        },
    )
    return job, meta


class FreehireAdapter:
    """Query Freehire public search API. Failures degrade to warnings."""

    name = "freehire"

    def __init__(
        self,
        client: RateLimitedClient | None = None,
        *,
        base_url: str | None = None,
        limit_per_query: int = 25,
        max_pages_per_query: int = 2,
        posted_within_days: int | None = 30,
    ) -> None:
        self.client = client or RateLimitedClient(
            min_interval_s=0.35,
            user_agent=DEFAULT_UA,
        )
        self.base_url = (base_url or freehire_base_url()).rstrip("/")
        self.limit_per_query = max(1, min(int(limit_per_query), 50))
        self.max_pages_per_query = max(1, min(int(max_pages_per_query), 4))
        self.posted_within_days = posted_within_days

    def search(
        self,
        queries: list[dict[str, Any]] | list[str],
    ) -> AdapterResult:
        result = AdapterResult(request_key="freehire")
        stats = {
            "fetched": 0,
            "unique": 0,
            "actionable": 0,
            "affiliate_rejected": 0,
            "review_only": 0,
            "skipped": 0,
            "queries": 0,
            "http_errors": 0,
        }
        seen: set[str] = set()

        for raw_q in queries:
            q = self._normalize_query(raw_q)
            if not q:
                continue
            stats["queries"] += 1
            for page in range(1, self.max_pages_per_query + 1):
                jobs_page, status, err = self._fetch_page(q, page=page)
                if status is not None:
                    result.raw_status = status
                if err:
                    stats["http_errors"] += 1
                    result.errors.append(err)
                    break
                if not jobs_page:
                    break
                for item in jobs_page:
                    stats["fetched"] += 1
                    job, meta = normalize_freehire_job(item if isinstance(item, dict) else {})
                    if job is None:
                        stats["skipped"] += 1
                        continue
                    dedupe_key = (job.apply_url or job.url or "").casefold()
                    if not dedupe_key or dedupe_key in seen:
                        stats["skipped"] += 1
                        continue
                    seen.add(dedupe_key)
                    stats["unique"] += 1
                    if meta.get("affiliate"):
                        stats["affiliate_rejected"] += 1
                    if job.source == "freehire_review":
                        stats["review_only"] += 1
                    if meta.get("actionable"):
                        stats["actionable"] += 1
                    result.jobs.append(job)
                if len(jobs_page) < self.limit_per_query:
                    break

        # Attach stats on request_key companion via errors channel is noisy;
        # callers read result via discover summary. Stash on a synthetic attr.
        result.request_key = f"freehire:q={stats['queries']}:n={stats['unique']}"
        self.last_stats = stats  # type: ignore[attr-defined]
        return result

    def _normalize_query(self, raw: dict[str, Any] | str) -> dict[str, Any] | None:
        if isinstance(raw, str):
            text = raw.strip()
            return {"q": text} if text else None
        if not isinstance(raw, dict):
            return None
        out = {k: v for k, v in raw.items() if v not in (None, "", [], {})}
        return out or None

    def _fetch_page(
        self, query: dict[str, Any], *, page: int
    ) -> tuple[list[Any], int | None, str | None]:
        params: dict[str, Any] = {
            "limit": self.limit_per_query,
            "offset": (page - 1) * self.limit_per_query,
            "description_format": "markdown",
            "countries": query.get("countries") or "ca",
        }
        if self.posted_within_days:
            params["posted_within_days"] = int(self.posted_within_days)
        for key in (
            "q",
            "regions",
            "cities",
            "seniority",
            "category",
            "skills",
            "work_mode",
            "company_slug",
        ):
            if key in query and query[key] not in (None, "", []):
                params[key] = query[key]
        # Allow callers to override countries
        if "countries" in query:
            params["countries"] = query["countries"]

        # Flatten list values into repeated query keys via urlencode doseq
        flat: list[tuple[str, str]] = []
        for key, val in params.items():
            if isinstance(val, list):
                for item in val:
                    flat.append((key, str(item)))
            else:
                flat.append((key, str(val)))
        url = f"{self.base_url}{AGENT_SEARCH_PATH}?{urlencode(flat)}"
        try:
            resp = self.client.get(url)
        except Exception as exc:  # noqa: BLE001
            return [], None, f"freehire unreachable: {exc}"
        if resp.status_code != 200:
            return [], resp.status_code, f"freehire HTTP {resp.status_code}"
        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            return [], resp.status_code, f"freehire invalid JSON: {exc}"
        if not isinstance(payload, dict):
            return [], resp.status_code, "freehire unexpected envelope"
        data = payload.get("data")
        if data is None:
            return [], resp.status_code, "freehire missing data"
        if not isinstance(data, list):
            return [], resp.status_code, "freehire data is not a list"
        return data, resp.status_code, None


def default_freehire_queries(search_cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Canada-focused Freehire queries from search.yaml or sensible defaults."""
    cfg = search_cfg or {}
    configured = cfg.get("freehire_queries")
    if isinstance(configured, list) and configured:
        out: list[dict[str, Any]] = []
        for item in configured:
            if isinstance(item, str) and item.strip():
                out.append({"q": item.strip(), "countries": "ca"})
            elif isinstance(item, dict):
                q = dict(item)
                q.setdefault("countries", "ca")
                out.append(q)
        return out
    # Defaults aligned with four-persona / engineering tracks
    return [
        {"q": "title:Data Engineer", "countries": "ca", "seniority": ["senior", "staff"]},
        {"q": "title:Software Engineer OR title:AI Engineer OR title:Machine Learning", "countries": "ca"},
        {"q": "title:Backend Engineer OR title:Software Developer", "countries": "ca", "seniority": ["junior", "middle"]},
        {"q": "title:DevOps OR title:SRE OR title:Platform Engineer", "countries": "ca", "seniority": ["senior", "staff"]},
        {"q": "remote", "countries": "ca", "work_mode": "remote", "category": ["backend", "devops", "ml_ai", "fullstack"]},
    ]


__all__ = [
    "FreehireAdapter",
    "default_freehire_queries",
    "normalize_freehire_job",
    "freehire_base_url",
]
