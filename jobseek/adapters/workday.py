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

import re
from typing import Any

from jobseek.adapters.base import AdapterResult
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob

_PAGE_SIZE = 20
_LOCATION_COUNT = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)
_POSTED_AGO = re.compile(r"Posted\s+(\d+)\s+Days?\s+Ago", re.I)


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
    ) -> None:
        self.client = client or RateLimitedClient(min_interval_s=0.4)
        self.page_size = max(1, min(page_size, 20))  # Workday CXS commonly caps at 20
        self.fetch_details = fetch_details
        self.max_jobs = max_jobs

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

        try:
            listings, list_status, list_errors = self._paginate_listings(list_url)
            result.raw_status = list_status
            result.errors.extend(list_errors)
            if list_status != 200:
                return result

            if self.max_jobs is not None:
                listings = listings[: self.max_jobs]

            detail_failures = 0
            for listing in listings:
                if not isinstance(listing, dict):
                    continue
                detail: dict[str, Any] | None = None
                if self.fetch_details:
                    path_id = _job_path_id(str(listing.get("externalPath") or ""))
                    if path_id:
                        detail, derr = self._fetch_detail(host, tenant, site, path_id)
                        if derr:
                            detail_failures += 1
                            # Keep going with list-level fields; do not invent URLs.
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
            return result
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"workday {company_name}: {exc}")
            if result.raw_status is None:
                result.raw_status = None
            return result

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
