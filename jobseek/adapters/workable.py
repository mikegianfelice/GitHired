"""Workable public widget API adapter."""

from __future__ import annotations

from typing import Any

from jobseek.adapters.base import AdapterResult
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob


def _location(job: dict[str, Any]) -> str | None:
    loc = job.get("location") or job.get("city")
    if isinstance(loc, dict):
        parts = [loc.get("city"), loc.get("region"), loc.get("country")]
        return ", ".join(p for p in parts if p) or None
    if isinstance(loc, str):
        return loc
    locs = job.get("locations")
    if isinstance(locs, list) and locs:
        first = locs[0]
        if isinstance(first, dict):
            parts = [first.get("city"), first.get("region"), first.get("country")]
            return ", ".join(p for p in parts if p) or None
        if isinstance(first, str):
            return first
    remote = job.get("remote")
    if remote is True:
        return "Remote"
    return None


class WorkableAdapter:
    name = "workable"

    def __init__(self, client: RateLimitedClient | None = None) -> None:
        self.client = client or RateLimitedClient()

    def fetch_company(self, company: dict) -> AdapterResult:
        token = (company.get("board_token") or company.get("site_slug") or "").strip()
        if not token:
            return AdapterResult(errors=[f"workable: missing board_token for {company.get('name')}"])
        # Public widget API — no API key required
        url = f"https://apply.workable.com/api/v1/widget/accounts/{token}"
        result = AdapterResult(request_key=f"workable:{token}")
        try:
            resp = self.client.get(url)
            result.raw_status = resp.status_code
            if resp.status_code != 200:
                result.errors.append(f"workable {token}: HTTP {resp.status_code}")
                return result
            try:
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"workable {token}: invalid JSON ({exc})")
                return result
            if not isinstance(payload, dict):
                result.errors.append(f"workable {token}: unexpected payload type")
                return result
            jobs = payload.get("jobs")
            if jobs is None:
                # Some accounts nest under results
                jobs = payload.get("results") or []
            if not isinstance(jobs, list):
                result.errors.append(f"workable {token}: jobs is not a list")
                return result
            company_name = company.get("name") or payload.get("name") or token
            for item in jobs:
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or "").strip()
                shortcode = str(item.get("shortcode") or item.get("id") or "").strip()
                absolute = (
                    (item.get("url") or item.get("application_url") or "").strip()
                    or (
                        f"https://apply.workable.com/{token}/j/{shortcode}/"
                        if shortcode
                        else ""
                    )
                )
                if not title or not absolute:
                    continue
                description = item.get("description") or item.get("full_description") or ""
                if isinstance(description, dict):
                    description = description.get("text") or description.get("html") or ""
                result.jobs.append(
                    RawJob(
                        company=str(company_name),
                        title=title,
                        url=absolute,
                        apply_url=absolute,
                        source="workable",
                        ats_provider="workable",
                        ats_job_id=shortcode or None,
                        location_raw=_location(item),
                        description=str(description) if description else None,
                        posted_date=(item.get("published_on") or item.get("created_at") or None),
                        raw_payload=item,
                    )
                )
            return result
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"workable {token}: {exc}")
            return result
