"""Greenhouse public Board API adapter."""

from __future__ import annotations

import re
from typing import Any

from jobseek.adapters.base import AdapterResult
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob

_SALARY = re.compile(
    r"(?P<currency>\$|CAD|USD|C\$)?\s*(?P<min>\d{2,3}(?:,\d{3})?)(?:\s*[-–—to]+\s*(?P<max>\d{2,3}(?:,\d{3})?))?",
    re.I,
)


def _parse_money(raw: str | None) -> tuple[float | None, float | None, str | None]:
    if not raw:
        return None, None, None
    match = _SALARY.search(raw.replace(",", ""))
    if not match:
        return None, None, None
    currency = match.group("currency")
    if currency in ("$", "USD"):
        currency = "USD"
    elif currency in ("CAD", "C$"):
        currency = "CAD"
    else:
        currency = None
    amin = float(match.group("min")) if match.group("min") else None
    amax = float(match.group("max")) if match.group("max") else amin
    # Greenhouse often uses thousands without commas once stripped oddly — leave as-is
    if amin and amin < 1000 and "k" in raw.lower():
        amin *= 1000
        if amax:
            amax *= 1000
    return amin, amax, currency


def _location(job: dict[str, Any]) -> str | None:
    loc = job.get("location") or {}
    if isinstance(loc, dict):
        return loc.get("name")
    if isinstance(loc, str):
        return loc
    return None


class GreenhouseAdapter:
    name = "greenhouse"

    def __init__(self, client: RateLimitedClient | None = None) -> None:
        self.client = client or RateLimitedClient()

    def fetch_company(self, company: dict) -> AdapterResult:
        token = (company.get("board_token") or company.get("site_slug") or "").strip()
        if not token:
            return AdapterResult(errors=[f"greenhouse: missing board_token for {company.get('name')}"])
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        result = AdapterResult(request_key=f"greenhouse:{token}")
        try:
            resp = self.client.get(url, params={"content": "true"})
            result.raw_status = resp.status_code
            if resp.status_code != 200:
                result.errors.append(f"greenhouse {token}: HTTP {resp.status_code}")
                return result
            payload = resp.json()
            jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
            company_name = company.get("name") or token
            for item in jobs:
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or "").strip()
                absolute = (item.get("absolute_url") or "").strip()
                job_id = str(item.get("id") or "").strip() or None
                if not title or not absolute:
                    continue
                content = item.get("content") or ""
                # Greenhouse content is often HTML-escaped
                description = content
                salary_raw = None
                metadata = item.get("metadata") or []
                if isinstance(metadata, list):
                    for meta in metadata:
                        if isinstance(meta, dict) and "salary" in (meta.get("name") or "").lower():
                            salary_raw = str(meta.get("value") or "")
                smin, smax, scur = _parse_money(salary_raw)
                result.jobs.append(
                    RawJob(
                        company=company_name,
                        title=title,
                        url=absolute,
                        source="greenhouse",
                        ats_provider="greenhouse",
                        ats_job_id=job_id,
                        location_raw=_location(item),
                        apply_url=absolute,
                        description=description,
                        salary_raw=salary_raw,
                        salary_min=smin,
                        salary_max=smax,
                        salary_currency=scur,
                        posted_date=(item.get("updated_at") or item.get("created_at") or "")[:10] or None,
                        raw_payload=item,
                    )
                )
        except Exception as exc:  # noqa: BLE001 — surface adapter failures
            result.errors.append(f"greenhouse {token}: {exc}")
        return result
