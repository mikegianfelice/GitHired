"""SmartRecruiters public postings API adapter (list-only, no key)."""

from __future__ import annotations

from typing import Any

from jobseek.adapters.base import AdapterResult
from jobseek.filters.salary import (
    apply_salary_info_to_raw,
    currency_hint_from_location,
    extract_salary_from_text,
    strip_html,
)
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob


def _location(item: dict[str, Any]) -> str | None:
    locs = item.get("jobAdLocations") or item.get("locations")
    if isinstance(locs, list) and locs:
        first = locs[0]
        if isinstance(first, dict):
            parts = [first.get("city"), first.get("region"), first.get("country")]
            out = ", ".join(p for p in parts if p)
            return out or None
        if isinstance(first, str):
            return first
    return None


class SmartRecruitersAdapter:
    name = "smartrecruiters"

    def __init__(self, client: RateLimitedClient | None = None) -> None:
        self.client = client or RateLimitedClient()

    def fetch_company(self, company: dict[str, Any]) -> AdapterResult:
        token = (company.get("board_token") or company.get("site_slug") or "").strip()
        if not token:
            return AdapterResult(errors=[f"smartrecruiters: missing board_token for {company.get('name')}"])
        url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=200"
        result = AdapterResult(request_key=f"smartrecruiters:{token}")
        try:
            resp = self.client.get(url)
            result.raw_status = resp.status_code
            if resp.status_code != 200:
                result.errors.append(f"smartrecruiters {token}: HTTP {resp.status_code}")
                return result
            try:
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"smartrecruiters {token}: invalid JSON ({exc})")
                return result
            jobs = payload.get("content") or payload.get("postings") or []
            if not isinstance(jobs, list):
                result.errors.append(f"smartrecruiters {token}: postings not a list")
                return result
            for item in jobs:
                if not isinstance(item, dict):
                    continue
                title = (item.get("name") or "").strip()
                id_ = str(item.get("id") or "").strip()
                # Public posting URL path is provided as 'ref' or 'url' in some payloads
                absolute = (item.get("ref") or {}).get("self") or item.get("url") or ""
                absolute = absolute.strip()
                if not title or not absolute:
                    continue
                desc = item.get("jobAd") or {}
                description = desc.get("sections", {}).get("jobDescription", {}).get("text", "") or desc.get("jobDescription", "") or ""
                desc_s = strip_html(str(description))
                location_raw = _location(item)
                # Salary is not structured; attempt extraction from description as hint-only
                hint = currency_hint_from_location(location_raw)
                salary_raw, smin, smax, scur = apply_salary_info_to_raw(
                    extract_salary_from_text(desc_s, currency_hint=hint, location_hint=location_raw)
                )
                result.jobs.append(
                    RawJob(
                        company=str(company.get("name") or token),
                        title=title,
                        url=absolute,
                        apply_url=absolute,
                        source="smartrecruiters",
                        ats_provider="smartrecruiters",
                        ats_job_id=id_ or None,
                        location_raw=location_raw,
                        description=desc_s or None,
                        salary_raw=salary_raw,
                        salary_min=smin,
                        salary_max=smax,
                        salary_currency=scur,
                        posted_date=item.get("releasedDate") or item.get("activatedOn"),
                        raw_payload=item,
                        description_complete=bool(desc_s.strip()),
                    )
                )
            return result
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"smartrecruiters {token}: {exc}")
            return result
