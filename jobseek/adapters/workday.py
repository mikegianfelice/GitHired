"""Workday public CXS guest-board adapter.

Uses unauthenticated ``/wday/cxs/{tenant}/{site}/jobs`` list endpoints with
offset pagination, then hydrates each posting via
``/wday/cxs/{tenant}/{site}/job/{id}``. Keyword ``searchText`` is intentionally
unused — Phase 4 found it unreliable without a browser session.

Company config (verified boards only; never invent endpoints)::

    ats: workday
    board_token: "intactfc.wd3.myworkdayjobs.com/intactfc/intactfc"  # host/tenant/site
    # or explicit fields:
    workday_host: intactfc.wd3.myworkdayjobs.com
    workday_tenant: intactfc
    board_token: intactfc   # site id
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from jobseek.adapters.base import AdapterResult
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob

_PAGE_SIZE = 20
_DEFAULT_DETAIL_CONCURRENCY = 4
# After the first list page (which reveals ``total``), fetch remaining offsets
# with bounded concurrency. Workday CXS hard-caps limit at 20; large boards
# (RBC ~40 pages) are otherwise dominated by ~5s/page RTT. Deduplicate by
# externalPath and mark incomplete when coverage is clearly short.
_DEFAULT_LIST_PAGE_CONCURRENCY = 3
_DEFAULT_LIST_BUDGET_S = 180.0
_DEFAULT_DETAIL_BUDGET_S = 120.0
# Legacy alias: company_budget_s maps to detail budget when list budget unset.
_DEFAULT_COMPANY_BUDGET_S = _DEFAULT_DETAIL_BUDGET_S
_DEFAULT_DESCRIPTION_TTL_S = 7 * 24 * 3600  # 7 days
_LOCATION_COUNT = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)
_POSTED_AGO = re.compile(r"Posted\s+(\d+)\s+Days?\s+Ago", re.I)
log = logging.getLogger("jobseek.workday")


def _parse_ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        from datetime import datetime, timezone

        raw = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def description_cache_fresh(
    entry: dict[str, Any] | None,
    *,
    ttl_s: float,
    now: float | None = None,
) -> bool:
    """True when cached description is complete and within TTL."""
    if not entry or not entry.get("description_complete"):
        return False
    desc = entry.get("description") or ""
    if not str(desc).strip():
        return False
    fetched = _parse_ts(entry.get("description_fetched_at"))
    if fetched is None:
        return False
    clock = now if now is not None else time.time()
    return (clock - fetched) <= ttl_s


def list_location_needs_detail(locations_text: str | None) -> bool:
    """True when list-level location is missing or a multi-location stub."""
    text = (locations_text or "").strip()
    if not text:
        return True
    return bool(_LOCATION_COUNT.match(text))


def cached_location_usable(entry: dict[str, Any] | None) -> bool:
    """True when cache has a resolved location (not a multi-location stub)."""
    if not entry:
        return False
    loc = str(entry.get("location_raw") or "").strip()
    return bool(loc) and not list_location_needs_detail(loc)


def lookup_description_cache(
    cache: dict[str, dict[str, Any]],
    *,
    listing: dict[str, Any],
    path_id: str | None,
) -> dict[str, Any] | None:
    """Resolve a cache entry by req id and/or path id (multi-key index)."""
    keys: list[str] = []
    req = _job_req_id({}, listing)
    if req:
        keys.append(str(req))
    if path_id:
        keys.append(str(path_id))
    for key in keys:
        hit = cache.get(key)
        if hit:
            return hit
    return None


def list_location_contradicts_cache(
    listing: dict[str, Any],
    cached: dict[str, Any] | None,
) -> bool:
    """True when a specific list location clearly differs from cached resolved geo."""
    if not cached:
        return False
    list_loc = str(listing.get("locationsText") or "").strip()
    cached_loc = str(cached.get("location_raw") or "").strip()
    if not list_loc or not cached_loc:
        return False
    if list_location_needs_detail(list_loc):
        return False
    left = list_loc.casefold()
    right = cached_loc.casefold()
    return left not in right and right not in left


def detail_required_for_listing(listing: dict[str, Any]) -> bool:
    """Whether CXS detail hydration is required for location/description completeness.

    List payloads never include job descriptions. Multi-location stubs ("5 Locations")
    also lack usable geography. Always hydrate in those cases. When list location is
    already specific we still hydrate for description (ranking/geo evidence) — callers
    that only need URLs can pass ``fetch_details=False``.
    """
    # Description is never on the list endpoint — detail is required for completeness.
    _ = listing
    return True


def parse_workday_board(company: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return ``(host, tenant, site)`` from company config, or None if incomplete."""
    host = (company.get("workday_host") or "").strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
    tenant = (company.get("workday_tenant") or "").strip()
    site = (company.get("workday_site") or company.get("board_token") or company.get("site_slug") or "").strip()

    if host and tenant and site and "/" not in site and "myworkdayjobs.com" in host:
        return host, tenant, site

    token = (company.get("board_token") or company.get("site_slug") or "").strip().removeprefix("https://").removeprefix("http://")
    if not token:
        return None
    parts = [p for p in token.split("/") if p]
    if len(parts) == 3 and "myworkdayjobs.com" in parts[0].lower():
        return parts[0].lower(), parts[1], parts[2]
    if len(parts) == 2 and host and "myworkdayjobs.com" in host:
        # tenant/site with separate host
        return host, parts[0], parts[1]
    return None


def workday_apply_url(host: str, site: str, external_path: str) -> str | None:
    """Build the official guest apply URL from a verified list ``externalPath``."""
    path = (external_path or "").strip()
    if not path.startswith("/"):
        return None
    host = host.strip().lower().removeprefix("https://").removeprefix("http://")
    site = site.strip().strip("/")
    if not host or not site or "myworkdayjobs.com" not in host:
        return None
    # externalPath already URL-encoded by Workday; do not re-quote path segments blindly
    return f"https://{host}/{site}{path}"


def _cxs_jobs_url(host: str, tenant: str, site: str) -> str:
    return f"https://{host}/wday/cxs/{tenant}/{site}/jobs"


def _cxs_job_url(host: str, tenant: str, site: str, job_path_id: str) -> str:
    # job_path_id is the final path segment of externalPath (already encoded)
    return f"https://{host}/wday/cxs/{tenant}/{site}/job/{job_path_id}"


def _job_path_id(external_path: str) -> str | None:
    path = (external_path or "").strip().rstrip("/")
    if not path:
        return None
    return path.split("/")[-1] or None


def _combine_locations(
    primary: str | None,
    additional: list[str] | None,
    remote_type: str | None,
    list_locations_text: str | None = None,
) -> str | None:
    parts: list[str] = []
    if primary and str(primary).strip():
        parts.append(str(primary).strip())
    for loc in additional or []:
        text = str(loc).strip()
        if text and text not in parts:
            parts.append(text)
    # List endpoint sometimes only says "N Locations" — keep as weak signal if no detail
    if not parts and list_locations_text and not _LOCATION_COUNT.match(list_locations_text):
        parts.append(list_locations_text.strip())
    elif not parts and list_locations_text:
        parts.append(list_locations_text.strip())
    if remote_type and str(remote_type).strip():
        rt = str(remote_type).strip()
        if rt.casefold() not in " ".join(parts).casefold():
            parts.append(rt)
    return "; ".join(parts) if parts else None


def _posted_date(info: dict[str, Any], list_posted: str | None) -> str | None:
    for key in ("startDate", "posted", "postedOn"):
        val = info.get(key)
        if isinstance(val, str) and re.match(r"^\d{4}-\d{2}-\d{2}", val):
            return val[:10]
    # list postedOn is relative ("Posted 22 Days Ago") — leave unset
    if list_posted and re.match(r"^\d{4}-\d{2}-\d{2}", list_posted):
        return list_posted[:10]
    return None


def _job_req_id(info: dict[str, Any], listing: dict[str, Any]) -> str | None:
    for key in ("jobReqId", "jobPostingId", "id"):
        val = info.get(key)
        if val:
            return str(val).strip()
    bullets = listing.get("bulletFields")
    if isinstance(bullets, list) and bullets:
        return str(bullets[0]).strip() or None
    return _job_path_id(str(listing.get("externalPath") or ""))


def normalize_workday_job(
    *,
    company_name: str,
    host: str,
    site: str,
    listing: dict[str, Any],
    detail: dict[str, Any] | None,
) -> RawJob | None:
    """Normalize list (+ optional detail) payloads into a RawJob.

    Returns None when an official apply URL cannot be constructed/verified.
    """
    title = (listing.get("title") or "").strip()
    external_path = (listing.get("externalPath") or "").strip()
    if not title or not external_path:
        return None

    info = (detail or {}).get("jobPostingInfo") if isinstance(detail, dict) else None
    if not isinstance(info, dict):
        info = {}

    apply_url = (info.get("externalUrl") or "").strip() or None
    constructed = workday_apply_url(host, site, external_path)
    if apply_url and "myworkdayjobs.com" not in apply_url.casefold():
        # Unexpected host — prefer constructed official guest URL when available
        apply_url = constructed
    if not apply_url:
        apply_url = constructed
    if not apply_url:
        return None

    if info.get("title"):
        title = str(info["title"]).strip() or title

    location_raw = _combine_locations(
        info.get("location"),
        info.get("additionalLocations") if isinstance(info.get("additionalLocations"), list) else None,
        info.get("remoteType"),
        list_locations_text=listing.get("locationsText"),
    )
    description = info.get("jobDescription")
    if isinstance(description, str):
        description = description.strip() or None
    else:
        description = None

    job_id = _job_req_id(info, listing)
    posted = _posted_date(info, listing.get("postedOn") if isinstance(listing.get("postedOn"), str) else None)

    payload = {"listing": listing, "detail": detail} if detail is not None else {"listing": listing}

    complete = bool(description)
    from datetime import datetime, timezone

    fetched_at = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if complete else None
    )

    # Salary: prefer rare structured CXS fields; else parse explicit description text.
    # List-only discovery typically has no description — extraction runs when enrich hydrates.
    from jobseek.filters.salary import (
        apply_salary_info_to_raw,
        extract_salary_from_text,
        from_structured,
        strip_html,
    )

    salary_raw = smin = smax = scur = None
    structured_min = info.get("salaryMin") or info.get("minimumSalary") or info.get("payMin")
    structured_max = info.get("salaryMax") or info.get("maximumSalary") or info.get("payMax")
    structured_cur = info.get("currency") or info.get("salaryCurrency") or info.get("payCurrency")
    if structured_min is not None or structured_max is not None:
        try:
            info_sal = from_structured(
                amin=float(structured_min) if structured_min is not None else None,
                amax=float(structured_max) if structured_max is not None else None,
                currency=str(structured_cur) if structured_cur else None,
                interval="year",
                raw=None,
                source="structured_ats",
            )
            salary_raw, smin, smax, scur = apply_salary_info_to_raw(info=info_sal)
        except (TypeError, ValueError):
            pass
    if smin is None and description:
        info_sal = extract_salary_from_text(strip_html(description))
        salary_raw, smin, smax, scur = apply_salary_info_to_raw(info=info_sal)

    return RawJob(
        company=company_name,
        title=title,
        url=apply_url,
        apply_url=apply_url,
        source="workday",
        ats_provider="workday",
        ats_job_id=job_id,
        location_raw=location_raw,
        description=description,
        salary_raw=salary_raw,
        salary_min=smin,
        salary_max=smax,
        salary_currency=scur,
        posted_date=posted,
        raw_payload=payload,
        description_complete=complete,
        description_fetched_at=fetched_at,
    )


class WorkdayAdapter:
    name = "workday"

    def __init__(
        self,
        client: RateLimitedClient | None = None,
        *,
        page_size: int = _PAGE_SIZE,
        fetch_details: bool = True,
        max_jobs: int | None = None,
        detail_concurrency: int = _DEFAULT_DETAIL_CONCURRENCY,
        list_page_concurrency: int = _DEFAULT_LIST_PAGE_CONCURRENCY,
        company_budget_s: float | None = _DEFAULT_COMPANY_BUDGET_S,
        list_budget_s: float | None = _DEFAULT_LIST_BUDGET_S,
        detail_budget_s: float | None = None,
        description_ttl_s: float = _DEFAULT_DESCRIPTION_TTL_S,
        force_refresh: bool = False,
        complete: bool = False,
        description_cache: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        # Shared keep-alive client; slightly tighter spacing is safe with the
        # global throttle lock and bounded detail concurrency below.
        self.client = client or RateLimitedClient(min_interval_s=0.25)
        self.page_size = max(1, min(page_size, 20))  # Workday CXS hard-caps at 20
        self.fetch_details = fetch_details
        self.max_jobs = max_jobs
        self.detail_concurrency = max(1, min(int(detail_concurrency), 8))
        self.list_page_concurrency = max(1, min(int(list_page_concurrency), 4))
        self.description_ttl_s = float(description_ttl_s)
        self.force_refresh = bool(force_refresh)
        self._description_cache = dict(description_cache or {})
        # complete=True disables wall clocks (full list + hydration).
        if complete:
            self.list_budget_s: float | None = None
            self.detail_budget_s: float | None = None
            self.company_budget_s = None
        else:
            self.list_budget_s = (
                None
                if list_budget_s is None or float(list_budget_s) <= 0
                else float(list_budget_s)
            )
            # Prefer explicit detail_budget_s; fall back to legacy company_budget_s.
            raw_detail = (
                detail_budget_s if detail_budget_s is not None else company_budget_s
            )
            if raw_detail is None or float(raw_detail) <= 0:
                self.detail_budget_s = None
            else:
                self.detail_budget_s = float(raw_detail)
            self.company_budget_s = self.detail_budget_s

    def set_description_cache(self, cache: dict[str, dict[str, Any]] | None) -> None:
        """Deprecated for concurrent use — prefer ``fetch_company(..., description_cache=)``."""
        self._description_cache = dict(cache or {})

    def clone(
        self,
        *,
        client: RateLimitedClient | None = None,
        description_cache: dict[str, dict[str, Any]] | None = None,
    ) -> "WorkdayAdapter":
        """Return an isolated adapter sharing config; optional private client/cache."""
        return WorkdayAdapter(
            client or self.client,
            page_size=self.page_size,
            fetch_details=self.fetch_details,
            max_jobs=self.max_jobs,
            detail_concurrency=self.detail_concurrency,
            list_page_concurrency=self.list_page_concurrency,
            company_budget_s=self.company_budget_s,
            list_budget_s=self.list_budget_s,
            detail_budget_s=self.detail_budget_s,
            description_ttl_s=self.description_ttl_s,
            force_refresh=self.force_refresh,
            complete=self.list_budget_s is None and self.detail_budget_s is None,
            description_cache=description_cache,
        )

    def fetch_company(
        self,
        company: dict,
        *,
        description_cache: dict[str, dict[str, Any]] | None = None,
    ) -> AdapterResult:
        """Fetch one company board.

        ``description_cache`` is request-scoped and never written back to shared
        adapter state — safe under concurrent company workers.
        """
        # Request-local cache: do not mutate self._description_cache (shared-instance bug).
        local_cache = (
            dict(description_cache)
            if description_cache is not None
            else dict(self._description_cache)
        )
        parsed = parse_workday_board(company)
        if not parsed:
            return AdapterResult(
                errors=[f"workday: missing host/tenant/site for {company.get('name')}"],
                listing_complete=False,
                hydration_complete=False,
            )
        host, tenant, site = parsed
        list_url = _cxs_jobs_url(host, tenant, site)
        request_key = f"workday:{host}/{tenant}/{site}"
        result = AdapterResult(request_key=request_key)
        company_name = str(company.get("name") or site)
        t0 = time.monotonic()

        try:
            log.info(
                "workday start company=%s host=%s site=%s list_budget_s=%s "
                "detail_budget_s=%s ttl_s=%.0f force_refresh=%s cache_entries=%s",
                company_name,
                host,
                site,
                self.list_budget_s if self.list_budget_s is not None else "complete",
                self.detail_budget_s if self.detail_budget_s is not None else "complete",
                self.description_ttl_s,
                self.force_refresh,
                len(local_cache),
            )
            listings, list_status, list_errors, list_meta = self._paginate_listings(
                list_url, started_at=t0
            )
            result.raw_status = list_status
            result.errors.extend(list_errors)
            result.list_pages = int(list_meta.get("pages") or 0)
            result.listing_complete = bool(list_meta.get("complete", False))
            result.timing["list_s"] = float(list_meta.get("elapsed_s") or 0.0)
            if list_status != 200:
                result.hydration_complete = False
                return result

            if self.max_jobs is not None:
                listings = listings[: self.max_jobs]

            log.info(
                "workday listed company=%s jobs=%s pages=%s complete=%s elapsed_s=%.1f",
                company_name,
                len(listings),
                result.list_pages,
                result.listing_complete,
                time.monotonic() - t0,
            )

            details_by_path, hydrate_meta = self._hydrate_details(
                host,
                tenant,
                site,
                listings,
                company_name=company_name,
                started_at=time.monotonic(),
                description_cache=local_cache,
            )
            result.details_cached = int(hydrate_meta.get("cached") or 0)
            result.details_fetched = int(hydrate_meta.get("fetched") or 0)
            result.details_requested = int(hydrate_meta.get("requested") or 0)
            result.hydration_complete = bool(hydrate_meta.get("complete", False))
            result.timing["detail_s"] = float(hydrate_meta.get("elapsed_s") or 0.0)
            result.timing["http_requests"] = int(
                hydrate_meta.get("http_requests") or 0
            ) + int(list_meta.get("http_requests") or 0)
            budget_hit = bool(hydrate_meta.get("budget_hit"))
            detail_failures = int(hydrate_meta.get("failures") or 0)
            detail_ok = result.details_fetched

            for listing in listings:
                if not isinstance(listing, dict):
                    continue
                detail: dict[str, Any] | None = None
                cached_desc: dict[str, Any] | None = None
                path_id = _job_path_id(str(listing.get("externalPath") or ""))
                if path_id and path_id in details_by_path:
                    detail, _derr = details_by_path[path_id]
                else:
                    cached_desc = lookup_description_cache(
                        local_cache, listing=listing, path_id=path_id
                    )
                job = normalize_workday_job(
                    company_name=company_name,
                    host=host,
                    site=site,
                    listing=listing,
                    detail=detail,
                )
                if job is None:
                    result.errors.append(
                        f"workday {company_name}: skipped posting without verifiable apply URL "
                        f"({listing.get('externalPath')!r})"
                    )
                    continue
                # Apply SQLite-cached complete description when detail was skipped.
                if (
                    not job.description_complete
                    and cached_desc
                    and cached_desc.get("description_complete")
                    and cached_desc.get("description")
                ):
                    job.description = str(cached_desc["description"])
                    job.description_complete = True
                    job.description_fetched_at = cached_desc.get("description_fetched_at")
                    list_loc = str(listing.get("locationsText") or "")
                    if cached_location_usable(cached_desc) and (
                        list_location_needs_detail(list_loc)
                        or not str(job.location_raw or "").strip()
                    ):
                        job.location_raw = (
                            str(cached_desc.get("location_raw") or job.location_raw)
                        )
                result.jobs.append(job)

            if detail_failures:
                result.errors.append(
                    f"workday {company_name}: {detail_failures} detail fetch(es) failed; "
                    "preserved prior descriptions where cached"
                )
            if budget_hit:
                result.errors.append(
                    f"workday {company_name}: detail budget "
                    f"({self.detail_budget_s:.0f}s) reached after {detail_ok} fetch(es) "
                    f"({result.details_cached} reused from cache); "
                    "remaining postings kept — re-run with mode=deep or "
                    "sources.workday_complete: true for full hydration"
                )
            if not result.listing_complete:
                result.errors.append(
                    f"workday {company_name}: listing pagination incomplete "
                    f"({len(listings)} jobs kept); will not mark missing jobs removed"
                )
            log.info(
                "workday done company=%s jobs=%s details_fetched=%s cached=%s "
                "failures=%s list_complete=%s hydrate_complete=%s elapsed_s=%.1f",
                company_name,
                len(result.jobs),
                result.details_fetched,
                result.details_cached,
                detail_failures,
                result.listing_complete,
                result.hydration_complete,
                time.monotonic() - t0,
            )
            result.timing["total_s"] = time.monotonic() - t0
            return result
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"workday {company_name}: {exc}")
            result.listing_complete = False
            result.hydration_complete = False
            log.warning(
                "workday exception company=%s elapsed_s=%.1f err=%s",
                company_name,
                time.monotonic() - t0,
                exc,
            )
            return result

    def _hydrate_details(
        self,
        host: str,
        tenant: str,
        site: str,
        listings: list[dict[str, Any]],
        *,
        company_name: str = "",
        started_at: float | None = None,
        description_cache: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[dict[str, tuple[dict[str, Any] | None, str | None]], dict[str, Any]]:
        """Fetch job details with cache reuse, bounded concurrency, and detail budget.

        Priority: missing geo (no usable cache) → never-seen → incomplete →
        TTL-stale. Fresh cache with resolved location is reused even when the
        list row is a multi-location stub (avoids daily re-downloads).
        """
        cache = (
            description_cache
            if description_cache is not None
            else self._description_cache
        )
        out: dict[str, tuple[dict[str, Any] | None, str | None]] = {}
        meta: dict[str, Any] = {
            "cached": 0,
            "fetched": 0,
            "requested": 0,
            "failures": 0,
            "budget_hit": False,
            "complete": True,
            "elapsed_s": 0.0,
            "http_requests": 0,
            "geo_reuse": 0,
            "geo_refresh": 0,
            "skipped_incomplete": 0,
        }
        if not self.fetch_details:
            meta["complete"] = True
            return out, meta

        new_ids: list[str] = []
        incomplete_ids: list[str] = []
        stale_ids: list[str] = []
        geo_first: list[str] = []
        seen: set[str] = set()
        now = time.time()

        for listing in listings:
            if not isinstance(listing, dict):
                continue
            path_id = _job_path_id(str(listing.get("externalPath") or ""))
            if not path_id or path_id in seen:
                continue
            seen.add(path_id)
            cached = lookup_description_cache(
                cache, listing=listing, path_id=path_id
            )
            needs_geo = list_location_needs_detail(
                str(listing.get("locationsText") or "")
            )
            fresh = (
                not self.force_refresh
                and description_cache_fresh(
                    cached, ttl_s=self.description_ttl_s, now=now
                )
            )
            if fresh:
                if list_location_contradicts_cache(listing, cached):
                    meta["geo_refresh"] += 1
                    geo_first.append(path_id)
                    continue
                if needs_geo and cached_location_usable(cached):
                    meta["cached"] += 1
                    meta["geo_reuse"] += 1
                    continue
                if needs_geo:
                    geo_first.append(path_id)
                    continue
                meta["cached"] += 1
                continue
            if cached is None:
                (geo_first if needs_geo else new_ids).append(path_id)
            elif not cached.get("description_complete"):
                # Known-incomplete rows come from prior detail-budget stops.
                # Re-downloading them every warm run burns the budget again and
                # dominates wall-clock. Catch up via force_refresh / mode=deep.
                if self.force_refresh:
                    incomplete_ids.append(path_id)
                else:
                    meta["cached"] += 1
                    meta["skipped_incomplete"] = int(meta.get("skipped_incomplete") or 0) + 1
            else:
                stale_ids.append(path_id)

        path_ids = geo_first + new_ids + incomplete_ids + stale_ids
        meta["requested"] = len(path_ids)
        if not path_ids:
            meta["elapsed_s"] = time.monotonic() - (started_at or time.monotonic())
            return out, meta

        t0 = started_at if started_at is not None else time.monotonic()
        budget = self.detail_budget_s

        def _over_budget() -> bool:
            return budget is not None and (time.monotonic() - t0) >= budget

        def _record(path_id: str, pair: tuple[dict[str, Any] | None, str | None]) -> None:
            out[path_id] = pair
            meta["http_requests"] += 1
            detail, err = pair
            if err:
                meta["failures"] += 1
            elif detail:
                meta["fetched"] += 1

        workers = min(self.detail_concurrency, len(path_ids))
        if workers == 1:
            for i, path_id in enumerate(path_ids):
                if _over_budget():
                    meta["budget_hit"] = True
                    meta["complete"] = False
                    log.info(
                        "workday detail budget stop company=%s after=%s/%s",
                        company_name,
                        i,
                        len(path_ids),
                    )
                    break
                _record(path_id, self._fetch_detail(host, tenant, site, path_id))
        else:
            wave = max(workers * 2, workers)
            idx = 0
            while idx < len(path_ids):
                if _over_budget():
                    meta["budget_hit"] = True
                    meta["complete"] = False
                    log.info(
                        "workday detail budget stop company=%s after=%s/%s",
                        company_name,
                        len(out),
                        len(path_ids),
                    )
                    break
                chunk = path_ids[idx : idx + wave]
                idx += len(chunk)
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {
                        pool.submit(self._fetch_detail, host, tenant, site, path_id): path_id
                        for path_id in chunk
                    }
                    for fut in as_completed(futures):
                        path_id = futures[fut]
                        try:
                            _record(path_id, fut.result())
                        except Exception as exc:  # noqa: BLE001
                            _record(path_id, (None, str(exc)))
                if (idx // wave) % 5 == 0 or idx >= len(path_ids):
                    log.info(
                        "workday details progress company=%s done=%s/%s "
                        "cached=%s geo_reuse=%s elapsed_s=%.1f",
                        company_name,
                        len(out),
                        len(path_ids),
                        meta["cached"],
                        meta["geo_reuse"],
                        time.monotonic() - t0,
                    )

        if meta["budget_hit"] or meta["failures"]:
            meta["complete"] = meta["complete"] and not meta["budget_hit"]
        meta["elapsed_s"] = time.monotonic() - t0
        return out, meta

    def _fetch_list_page(
        self, list_url: str, offset: int
    ) -> tuple[int, int | None, list[dict[str, Any]], int | None, str | None]:
        """Return ``(offset, status, postings, total, error)`` for one CXS page."""
        payload = {
            "appliedFacets": {},
            "limit": self.page_size,
            "offset": offset,
            "searchText": "",
        }
        try:
            resp = self.client.post(list_url, json_body=payload)
        except Exception as exc:  # noqa: BLE001
            return offset, None, [], None, str(exc)
        if resp.status_code != 200:
            return offset, resp.status_code, [], None, f"HTTP {resp.status_code}"
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return offset, resp.status_code, [], None, f"invalid JSON ({exc})"
        if not isinstance(data, dict):
            return offset, resp.status_code, [], None, "unexpected payload type"
        raw_total = data.get("total")
        total = int(raw_total) if isinstance(raw_total, int) and raw_total >= 0 else None
        batch = data.get("jobPostings") or []
        postings = [item for item in batch if isinstance(item, dict)] if isinstance(batch, list) else []
        return offset, resp.status_code, postings, total, None

    def _paginate_listings(
        self, list_url: str, *, started_at: float | None = None
    ) -> tuple[list[dict[str, Any]], int | None, list[str], dict[str, Any]]:
        """Paginate CXS job list.

        Page 0 is always sequential (discovers ``total``). Remaining offsets are
        fetched with bounded concurrency when ``total`` is known — large boards
        otherwise spend minutes on serial ~5s RTTs. Results are deduplicated by
        ``externalPath``. Coverage shortfalls mark ``complete=False`` so missing
        jobs are not falsely removed.
        """
        errors: list[str] = []
        listings: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        last_status: int | None = None
        pages = 0
        http_requests = 0
        t0 = started_at if started_at is not None else time.monotonic()
        complete = False
        total: int | None = None

        def _over_budget() -> bool:
            return (
                self.list_budget_s is not None
                and (time.monotonic() - t0) >= self.list_budget_s
            )

        def _absorb(batch: list[dict[str, Any]]) -> None:
            for item in batch:
                path = str(item.get("externalPath") or "")
                key = path or str(item.get("bulletFields") or item.get("title") or id(item))
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                listings.append(item)

        # --- page 0 ---
        if _over_budget():
            errors.append(
                f"workday list pagination budget ({self.list_budget_s:.0f}s) "
                "reached before first page"
            )
            meta = {
                "pages": 0,
                "complete": False,
                "elapsed_s": time.monotonic() - t0,
                "total_reported": None,
                "http_requests": 0,
            }
            return listings, None, errors, meta

        offset0, status0, batch0, total0, err0 = self._fetch_list_page(list_url, 0)
        http_requests += 1
        pages += 1
        last_status = status0
        if err0:
            errors.append(f"workday list at offset {offset0}: {err0}")
            meta = {
                "pages": pages,
                "complete": False,
                "elapsed_s": time.monotonic() - t0,
                "total_reported": total0,
                "http_requests": http_requests,
            }
            return listings, last_status, errors, meta
        total = total0
        _absorb(batch0)
        if not batch0:
            complete = True
        elif total is not None and len(listings) >= total:
            complete = True
        elif len(batch0) < self.page_size:
            complete = True

        # --- remaining pages ---
        if not complete and total is not None and total > self.page_size:
            # Cap offsets to safety limit
            max_jobs = min(total, 5000)
            offsets = list(range(self.page_size, max_jobs, self.page_size))
            if total > 5000:
                errors.append("workday list capped at 5000-job safety limit")
            workers = min(self.list_page_concurrency, len(offsets))
            if workers <= 1 or _over_budget():
                for offset in offsets:
                    if _over_budget():
                        errors.append(
                            f"workday list pagination budget ({self.list_budget_s:.0f}s) "
                            f"reached at offset {offset}; keeping {len(listings)} listings"
                        )
                        complete = False
                        break
                    _off, st, batch, _tot, err = self._fetch_list_page(list_url, offset)
                    http_requests += 1
                    pages += 1
                    last_status = st if st is not None else last_status
                    if err:
                        errors.append(f"workday list at offset {offset}: {err}")
                        complete = False
                        break
                    if not batch:
                        complete = True
                        break
                    _absorb(batch)
                    if len(batch) < self.page_size:
                        complete = True
                        break
                else:
                    complete = len(listings) >= int(total * 0.95)
            else:
                # Bounded parallel offset fetch; assemble in offset order for stability.
                by_offset: dict[int, list[dict[str, Any]]] = {}
                failed = False
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futs = {
                        pool.submit(self._fetch_list_page, list_url, off): off
                        for off in offsets
                    }
                    for fut in as_completed(futs):
                        if _over_budget():
                            failed = True
                            for pending in futs:
                                pending.cancel()
                            errors.append(
                                f"workday list pagination budget ({self.list_budget_s:.0f}s) "
                                f"reached; keeping {len(listings)} listings"
                            )
                            break
                        off, st, batch, _tot, err = fut.result()
                        http_requests += 1
                        pages += 1
                        last_status = st if st is not None else last_status
                        if err:
                            failed = True
                            errors.append(f"workday list at offset {off}: {err}")
                            continue
                        by_offset[off] = batch
                for off in sorted(by_offset):
                    _absorb(by_offset[off])
                # Coverage gate: parallel pages can race with board churn.
                if failed:
                    complete = False
                elif total > 5000:
                    complete = False
                elif len(listings) >= int(total * 0.95):
                    complete = True
                else:
                    complete = False
                    errors.append(
                        f"workday list coverage shortfall "
                        f"({len(listings)} unique vs total={total}); "
                        "will not mark missing jobs removed"
                    )
                log.info(
                    "workday list parallel pages=%s unique=%s total=%s "
                    "workers=%s complete=%s elapsed_s=%.1f",
                    pages,
                    len(listings),
                    total,
                    workers,
                    complete,
                    time.monotonic() - t0,
                )
        elif not complete:
            # Unknown total — fall back to sequential walk.
            offset = len(listings)
            while True:
                if _over_budget():
                    errors.append(
                        f"workday list pagination budget ({self.list_budget_s:.0f}s) "
                        f"reached at offset {offset}; keeping {len(listings)} listings"
                    )
                    complete = False
                    break
                if offset >= 5000:
                    errors.append("workday list stopped at 5000-job safety cap")
                    complete = False
                    break
                _off, st, batch, tot, err = self._fetch_list_page(list_url, offset)
                http_requests += 1
                pages += 1
                last_status = st if st is not None else last_status
                if tot is not None:
                    total = tot
                if err:
                    errors.append(f"workday list at offset {offset}: {err}")
                    complete = False
                    break
                if not batch:
                    complete = True
                    break
                before = len(listings)
                _absorb(batch)
                offset += len(batch)
                if len(batch) < self.page_size or (total is not None and len(listings) >= total):
                    complete = True
                    break
                if len(listings) == before:
                    complete = True
                    break

        meta = {
            "pages": pages,
            "complete": complete,
            "elapsed_s": time.monotonic() - t0,
            "total_reported": total,
            "http_requests": http_requests,
            "unique_jobs": len(listings),
        }
        return listings, last_status, errors, meta

    def _fetch_detail(
        self, host: str, tenant: str, site: str, path_id: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        url = _cxs_job_url(host, tenant, site, path_id)
        try:
            resp = self.client.get(url)
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return None, f"invalid JSON ({exc})"
        if not isinstance(data, dict):
            return None, "unexpected detail payload"
        return data, None
