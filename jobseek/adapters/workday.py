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
# Soft per-company wall clocks (monotonic). Listing and detail are separate so
# slow pagination (e.g. RBC ~164s) cannot consume the entire hydration budget.
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
        self.page_size = max(1, min(page_size, 20))  # Workday CXS commonly caps at 20
        self.fetch_details = fetch_details
        self.max_jobs = max_jobs
        self.detail_concurrency = max(1, min(int(detail_concurrency), 8))
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
        self._description_cache = dict(cache or {})

    def fetch_company(self, company: dict) -> AdapterResult:
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
                "detail_budget_s=%s ttl_s=%.0f force_refresh=%s",
                company_name,
                host,
                site,
                self.list_budget_s if self.list_budget_s is not None else "complete",
                self.detail_budget_s if self.detail_budget_s is not None else "complete",
                self.description_ttl_s,
                self.force_refresh,
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
            )
            result.details_cached = int(hydrate_meta.get("cached") or 0)
            result.details_fetched = int(hydrate_meta.get("fetched") or 0)
            result.details_requested = int(hydrate_meta.get("requested") or 0)
            result.hydration_complete = bool(hydrate_meta.get("complete", False))
            result.timing["detail_s"] = float(hydrate_meta.get("elapsed_s") or 0.0)
            budget_hit = bool(hydrate_meta.get("budget_hit"))
            detail_failures = int(hydrate_meta.get("failures") or 0)
            detail_ok = result.details_fetched

            for listing in listings:
                if not isinstance(listing, dict):
                    continue
                detail: dict[str, Any] | None = None
                cached_desc: dict[str, Any] | None = None
                path_id = _job_path_id(str(listing.get("externalPath") or ""))
                job_key = _job_req_id({}, listing) or path_id
                if path_id and path_id in details_by_path:
                    detail, _derr = details_by_path[path_id]
                elif job_key and job_key in self._description_cache:
                    cached_desc = self._description_cache[job_key]
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
                    if (
                        cached_desc.get("location_raw")
                        and list_location_needs_detail(str(listing.get("locationsText") or ""))
                    ):
                        job.location_raw = cached_desc.get("location_raw") or job.location_raw
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
    ) -> tuple[dict[str, tuple[dict[str, Any] | None, str | None]], dict[str, Any]]:
        """Fetch job details with cache reuse, bounded concurrency, and detail budget.

        Priority: never-seen → incomplete cache → stale TTL → skip fresh cache.
        """
        out: dict[str, tuple[dict[str, Any] | None, str | None]] = {}
        meta: dict[str, Any] = {
            "cached": 0,
            "fetched": 0,
            "requested": 0,
            "failures": 0,
            "budget_hit": False,
            "complete": True,
            "elapsed_s": 0.0,
        }
        if not self.fetch_details:
            meta["complete"] = True
            return out, meta

        # Map path_id → job cache key (req id when known from list bullets).
        path_to_key: dict[str, str] = {}
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
            job_key = _job_req_id({}, listing) or path_id
            path_to_key[path_id] = job_key
            cached = self._description_cache.get(job_key)
            needs_geo = list_location_needs_detail(str(listing.get("locationsText") or ""))
            fresh = (
                not self.force_refresh
                and description_cache_fresh(
                    cached, ttl_s=self.description_ttl_s, now=now
                )
            )
            if fresh and not needs_geo:
                meta["cached"] += 1
                continue
            if fresh and needs_geo:
                # Location stub still needs detail even with cached description.
                geo_first.append(path_id)
                continue
            if cached is None:
                (geo_first if needs_geo else new_ids).append(path_id)
            elif not cached.get("description_complete"):
                incomplete_ids.append(path_id)
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
                        "cached=%s elapsed_s=%.1f",
                        company_name,
                        len(out),
                        len(path_ids),
                        meta["cached"],
                        time.monotonic() - t0,
                    )

        if meta["budget_hit"] or meta["failures"]:
            meta["complete"] = meta["complete"] and not meta["budget_hit"]
        meta["elapsed_s"] = time.monotonic() - t0
        return out, meta

    def _paginate_listings(
        self, list_url: str, *, started_at: float | None = None
    ) -> tuple[list[dict[str, Any]], int | None, list[str], dict[str, Any]]:
        errors: list[str] = []
        listings: list[dict[str, Any]] = []
        offset = 0
        total: int | None = None
        last_status: int | None = None
        pages = 0
        t0 = started_at if started_at is not None else time.monotonic()
        complete = False

        while True:
            if self.list_budget_s is not None and (time.monotonic() - t0) >= self.list_budget_s:
                errors.append(
                    f"workday list pagination budget ({self.list_budget_s:.0f}s) "
                    f"reached at offset {offset}; keeping {len(listings)} listings"
                )
                complete = False
                break
            payload = {
                "appliedFacets": {},
                "limit": self.page_size,
                "offset": offset,
                "searchText": "",
            }
            resp = self.client.post(list_url, json_body=payload)
            last_status = resp.status_code
            pages += 1
            if resp.status_code != 200:
                errors.append(f"workday list HTTP {resp.status_code} at offset {offset}")
                complete = False
                break
            try:
                data = resp.json()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"workday list invalid JSON at offset {offset}: {exc}")
                complete = False
                break
            if not isinstance(data, dict):
                errors.append(f"workday list unexpected payload type at offset {offset}")
                complete = False
                break

            if total is None:
                raw_total = data.get("total")
                total = int(raw_total) if isinstance(raw_total, int) and raw_total >= 0 else None

            batch = data.get("jobPostings") or []
            if not isinstance(batch, list) or not batch:
                complete = True
                break
            for item in batch:
                if isinstance(item, dict):
                    listings.append(item)

            offset += len(batch)
            if total is not None and offset >= total:
                complete = True
                break
            if len(batch) < self.page_size:
                complete = True
                break
            # Safety cap against runaway boards
            if offset >= 5000:
                errors.append("workday list stopped at 5000-job safety cap")
                complete = False
                break

        meta = {
            "pages": pages,
            "complete": complete,
            "elapsed_s": time.monotonic() - t0,
            "total_reported": total,
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
