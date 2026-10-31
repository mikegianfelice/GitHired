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
# Soft per-company wall clock for detail hydration (list pagination always finishes).
# Complete mode (company_budget_s=None / 0) hydrates every posting.
_DEFAULT_COMPANY_BUDGET_S = 120.0
_LOCATION_COUNT = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)
_POSTED_AGO = re.compile(r"Posted\s+(\d+)\s+Days?\s+Ago", re.I)
log = logging.getLogger("jobseek.workday")


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
        complete: bool = False,
    ) -> None:
        # Shared keep-alive client; slightly tighter spacing is safe with the
        # global throttle lock and bounded detail concurrency below.
        self.client = client or RateLimitedClient(min_interval_s=0.25)
        self.page_size = max(1, min(page_size, 20))  # Workday CXS commonly caps at 20
        self.fetch_details = fetch_details
        self.max_jobs = max_jobs
        self.detail_concurrency = max(1, min(int(detail_concurrency), 8))
        # complete=True disables the per-company wall clock (full hydration).
        if complete or company_budget_s is None or float(company_budget_s) <= 0:
            self.company_budget_s: float | None = None
        else:
            self.company_budget_s = float(company_budget_s)

    def fetch_company(self, company: dict) -> AdapterResult:
        parsed = parse_workday_board(company)
        if not parsed:
            return AdapterResult(
                errors=[f"workday: missing host/tenant/site for {company.get('name')}"]
            )
        host, tenant, site = parsed
        list_url = _cxs_jobs_url(host, tenant, site)
        request_key = f"workday:{host}/{tenant}/{site}"
        result = AdapterResult(request_key=request_key)
        company_name = str(company.get("name") or site)
        t0 = time.monotonic()

        try:
            log.info(
                "workday start company=%s host=%s site=%s budget_s=%s",
                company_name,
                host,
                site,
                self.company_budget_s if self.company_budget_s is not None else "complete",
            )
            listings, list_status, list_errors = self._paginate_listings(list_url)
            result.raw_status = list_status
            result.errors.extend(list_errors)
            if list_status != 200:
                return result

            if self.max_jobs is not None:
                listings = listings[: self.max_jobs]

            log.info(
                "workday listed company=%s jobs=%s elapsed_s=%.1f",
                company_name,
                len(listings),
                time.monotonic() - t0,
            )

            details_by_path, budget_hit = self._hydrate_details(
                host, tenant, site, listings, company_name=company_name, started_at=t0
            )
            detail_failures = sum(1 for _path, (detail, err) in details_by_path.items() if err)
            detail_ok = sum(1 for _path, (detail, err) in details_by_path.items() if detail and not err)

            for listing in listings:
                if not isinstance(listing, dict):
                    continue
                detail: dict[str, Any] | None = None
                path_id = _job_path_id(str(listing.get("externalPath") or ""))
                if path_id and path_id in details_by_path:
                    detail, _derr = details_by_path[path_id]
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
                result.jobs.append(job)

            if detail_failures:
                result.errors.append(
                    f"workday {company_name}: {detail_failures} detail fetch(es) failed; "
                    "list-level fields used where possible"
                )
            if budget_hit:
                result.errors.append(
                    f"workday {company_name}: company detail budget "
                    f"({self.company_budget_s:.0f}s) reached after {detail_ok} detail(s); "
                    "remaining postings kept from list payload — re-run with "
                    "sources.workday_complete: true for full hydration"
                )
            log.info(
                "workday done company=%s jobs=%s details_ok=%s failures=%s "
                "budget_hit=%s elapsed_s=%.1f",
                company_name,
                len(result.jobs),
                detail_ok,
                detail_failures,
                budget_hit,
                time.monotonic() - t0,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"workday {company_name}: {exc}")
            log.warning(
                "workday exception company=%s elapsed_s=%.1f err=%s",
                company_name,
                time.monotonic() - t0,
                exc,
            )
            if result.raw_status is None:
                result.raw_status = None
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
    ) -> tuple[dict[str, tuple[dict[str, Any] | None, str | None]], bool]:
        """Fetch job details with bounded concurrency and optional time budget.

        Returns ``(details_by_path_id, budget_exhausted)``. List-level jobs are
        always preserved when the budget stops further detail calls.
        """
        out: dict[str, tuple[dict[str, Any] | None, str | None]] = {}
        budget_hit = False
        if not self.fetch_details:
            return out, False

        path_ids: list[str] = []
        seen: set[str] = set()
        # Prefer hydrating multi-location stubs first (geography), then the rest.
        prioritized: list[str] = []
        deferred: list[str] = []
        for listing in listings:
            if not isinstance(listing, dict):
                continue
            path_id = _job_path_id(str(listing.get("externalPath") or ""))
            if not path_id or path_id in seen:
                continue
            seen.add(path_id)
            if list_location_needs_detail(str(listing.get("locationsText") or "")):
                prioritized.append(path_id)
            else:
                deferred.append(path_id)
        path_ids = prioritized + deferred

        if not path_ids:
            return out, False

        t0 = started_at if started_at is not None else time.monotonic()
        budget = self.company_budget_s

        def _over_budget() -> bool:
            return budget is not None and (time.monotonic() - t0) >= budget

        workers = min(self.detail_concurrency, len(path_ids))
        if workers == 1:
            for i, path_id in enumerate(path_ids):
                if _over_budget():
                    budget_hit = True
                    log.info(
                        "workday budget stop company=%s after=%s/%s details",
                        company_name,
                        i,
                        len(path_ids),
                    )
                    break
                out[path_id] = self._fetch_detail(host, tenant, site, path_id)
            return out, budget_hit

        # Submit in waves so a budget cut does not leave a huge in-flight pool.
        wave = max(workers * 2, workers)
        idx = 0
        while idx < len(path_ids):
            if _over_budget():
                budget_hit = True
                log.info(
                    "workday budget stop company=%s after=%s/%s details",
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
                        out[path_id] = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        out[path_id] = (None, str(exc))
            if (idx // wave) % 5 == 0 or idx >= len(path_ids):
                log.info(
                    "workday details progress company=%s done=%s/%s elapsed_s=%.1f",
                    company_name,
                    len(out),
                    len(path_ids),
                    time.monotonic() - t0,
                )
        return out, budget_hit

    def _paginate_listings(
        self, list_url: str
    ) -> tuple[list[dict[str, Any]], int | None, list[str]]:
        errors: list[str] = []
        listings: list[dict[str, Any]] = []
        offset = 0
        total: int | None = None
        last_status: int | None = None

        while True:
            payload = {
                "appliedFacets": {},
                "limit": self.page_size,
                "offset": offset,
                "searchText": "",
            }
            resp = self.client.post(list_url, json_body=payload)
            last_status = resp.status_code
            if resp.status_code != 200:
                errors.append(f"workday list HTTP {resp.status_code} at offset {offset}")
                break
            try:
                data = resp.json()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"workday list invalid JSON at offset {offset}: {exc}")
                break
            if not isinstance(data, dict):
                errors.append(f"workday list unexpected payload type at offset {offset}")
                break

            if total is None:
                raw_total = data.get("total")
                total = int(raw_total) if isinstance(raw_total, int) and raw_total >= 0 else None

            batch = data.get("jobPostings") or []
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if isinstance(item, dict):
                    listings.append(item)

            offset += len(batch)
            if total is not None and offset >= total:
                break
            if len(batch) < self.page_size:
                break
            # Safety cap against runaway boards
            if offset >= 5000:
                errors.append("workday list stopped at 5000-job safety cap")
                break

        return listings, last_status, errors

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
