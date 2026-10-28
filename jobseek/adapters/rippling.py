"""Rippling public board API adapter (only when endpoint is stable)."""

from __future__ import annotations

from typing import Any

from jobseek.adapters.base import AdapterResult
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob


def _location(job: dict[str, Any]) -> str | None:
    loc = job.get("location") or job.get("locations")
    if isinstance(loc, str):
        return loc
    if isinstance(loc, list) and loc:
        first = loc[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("name") or first.get("city")
    if isinstance(loc, dict):
        return loc.get("name") or loc.get("city")
    return None


class RipplingAdapter:
    name = "rippling"

    def __init__(self, client: RateLimitedClient | None = None) -> None:
        self.client = client or RateLimitedClient()

    def fetch_company(self, company: dict) -> AdapterResult:
        token = (company.get("board_token") or company.get("site_slug") or "").strip()
        if not token:
            return AdapterResult(errors=[f"rippling: missing board_token for {company.get('name')}"])
        url = f"https://ats.rippling.com/api/v2/board/{token}/jobs"
        result = AdapterResult(request_key=f"rippling:{token}")
        try:
            resp = self.client.get(url)
            result.raw_status = resp.status_code
            if resp.status_code != 200:
                result.errors.append(f"rippling {token}: HTTP {resp.status_code}")
                return result
            try:
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"rippling {token}: invalid JSON ({exc})")
                return result
            jobs: list[Any]
            if isinstance(payload, list):
                jobs = payload
            elif isinstance(payload, dict):
                jobs = payload.get("jobs") or payload.get("items") or payload.get("results") or []
            else:
                result.errors.append(f"rippling {token}: unexpected payload type")
                return result
            if not isinstance(jobs, list):
                result.errors.append(f"rippling {token}: jobs is not a list")
                return result
            company_name = company.get("name") or token
            for item in jobs:
                if not isinstance(item, dict):
                    continue
                title = (item.get("name") or item.get("title") or "").strip()
                job_id = str(item.get("id") or item.get("uuid") or "").strip()
                absolute = (
                    (item.get("url") or item.get("jobUrl") or item.get("applyUrl") or "").strip()
                )
                if not absolute and job_id:
                    absolute = f"https://ats.rippling.com/{token}/jobs/{job_id}"
                if not title or not absolute:
                    continue
                result.jobs.append(
                    RawJob(
                        company=str(company_name),
                        title=title,
                        url=absolute,
                        apply_url=absolute,
                        source="rippling",
                        ats_provider="rippling",
                        ats_job_id=job_id or None,
                        location_raw=_location(item),
                        description=(item.get("description") or item.get("jobDescription") or None),
                        raw_payload=item,
                    )
                )
            return result
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"rippling {token}: {exc}")
            return result
