"""Lever public postings API adapter."""

from __future__ import annotations

from typing import Any

from jobseek.adapters.base import AdapterResult
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob


def _location(job: dict[str, Any]) -> str | None:
    cats = job.get("categories") or {}
    if isinstance(cats, dict):
        loc = cats.get("location")
        if loc:
            return str(loc)
    loc = job.get("location")
    return str(loc) if loc else None


def _salary(job: dict[str, Any]) -> tuple[str | None, float | None, float | None, str | None]:
    salary = job.get("salaryRange") or job.get("salary") or {}
    if not isinstance(salary, dict):
        return None, None, None, None
    amin = salary.get("min")
    amax = salary.get("max")
    currency = salary.get("currency")
    raw = None
    if amin is not None or amax is not None:
        raw = f"{currency or ''} {amin or ''}-{amax or ''}".strip()
    try:
        smin = float(amin) if amin is not None else None
        smax = float(amax) if amax is not None else None
    except (TypeError, ValueError):
        smin, smax = None, None
    return raw, smin, smax, str(currency) if currency else None


class LeverAdapter:
    name = "lever"

    def __init__(self, client: RateLimitedClient | None = None) -> None:
        self.client = client or RateLimitedClient()

    def fetch_company(self, company: dict) -> AdapterResult:
        site = (company.get("board_token") or company.get("site_slug") or "").strip()
        if not site:
            return AdapterResult(errors=[f"lever: missing board_token for {company.get('name')}"])
        url = f"https://api.lever.co/v0/postings/{site}"
        result = AdapterResult(request_key=f"lever:{site}")
        try:
            resp = self.client.get(url, params={"mode": "json"})
            result.raw_status = resp.status_code
            if resp.status_code != 200:
                result.errors.append(f"lever {site}: HTTP {resp.status_code}")
                return result
            payload = resp.json()
            if not isinstance(payload, list):
                result.errors.append(f"lever {site}: unexpected payload")
                return result
            company_name = company.get("name") or site
            for item in payload:
                if not isinstance(item, dict):
                    continue
                title = (item.get("text") or "").strip()
                hosted = (item.get("hostedUrl") or item.get("applyUrl") or "").strip()
                job_id = str(item.get("id") or "").strip() or None
                if not title or not hosted:
                    continue
                description = item.get("descriptionPlain") or item.get("description") or ""
                lists = item.get("lists") or []
                if isinstance(lists, list):
                    extras = []
                    for block in lists:
                        if isinstance(block, dict):
                            extras.append(block.get("text") or "")
                            content = block.get("content")
                            if isinstance(content, str):
                                extras.append(content)
                    if extras:
                        description = (description or "") + "\n" + "\n".join(extras)
                salary_raw, smin, smax, scur = _salary(item)
                result.jobs.append(
                    RawJob(
                        company=company_name,
                        title=title,
                        url=hosted,
                        source="lever",
                        ats_provider="lever",
                        ats_job_id=job_id,
                        location_raw=_location(item),
                        apply_url=item.get("applyUrl") or hosted,
                        description=description,
                        salary_raw=salary_raw,
                        salary_min=smin,
                        salary_max=smax,
                        salary_currency=scur,
                        posted_date=None,
                        raw_payload=item,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"lever {site}: {exc}")
        return result
