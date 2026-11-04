"""Greenhouse public Board API adapter."""

from __future__ import annotations

from typing import Any

from jobseek.adapters.base import AdapterResult
from jobseek.filters.salary import (
    apply_salary_info_to_raw,
    extract_salary_from_text,
    from_structured,
    strip_html,
)
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob


def _location(job: dict[str, Any]) -> str | None:
    loc = job.get("location") or {}
    if isinstance(loc, dict):
        return loc.get("name")
    if isinstance(loc, str):
        return loc
    return None


def _salary_from_job(
    item: dict[str, Any],
    description: str,
    *,
    location_raw: str | None = None,
) -> tuple[str | None, float | None, float | None, str | None]:
    """Prefer structured Greenhouse metadata; fall back to description text.

    Multi-zone pay tables (e.g. Robinhood) select the band matching ``location_raw``.
    """
    from jobseek.filters.salary import currency_hint_from_location

    hint = currency_hint_from_location(location_raw)
    salary_raw = None
    metadata = item.get("metadata") or []
    if isinstance(metadata, list):
        for meta in metadata:
            if not isinstance(meta, dict):
                continue
            name = (meta.get("name") or "").lower()
            if "salary" in name or "compensation" in name or "pay" in name:
                value = meta.get("value")
                if value is None:
                    continue
                if isinstance(value, dict):
                    # Rare structured shape: {min_value, max_value, unit}
                    amin = value.get("min_value") or value.get("min")
                    amax = value.get("max_value") or value.get("max")
                    currency = value.get("unit") or value.get("currency")
                    info = from_structured(
                        amin=float(amin) if amin is not None else None,
                        amax=float(amax) if amax is not None else None,
                        currency=str(currency) if currency else None,
                        interval="year",
                        raw=str(value),
                    )
                    if info.confidence == "verified":
                        return apply_salary_info_to_raw(info=info)
                    salary_raw = str(value)
                else:
                    salary_raw = str(value)
                break

    if salary_raw:
        info = extract_salary_from_text(
            salary_raw, currency_hint=hint, location_hint=location_raw
        )
        if info.confidence == "verified":
            return apply_salary_info_to_raw(info=info)
        # Keep raw even when unverified
        raw, amin, amax, cur = apply_salary_info_to_raw(info=info)
        if raw:
            return raw, amin, amax, cur

    # Description fallback (HTML content)
    plain = strip_html(description or "")
    if plain:
        info = extract_salary_from_text(
            plain, currency_hint=hint, location_hint=location_raw
        )
        return apply_salary_info_to_raw(info=info)
    return None, None, None, None


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
                description = content
                location_raw = _location(item)
                salary_raw, smin, smax, scur = _salary_from_job(
                    item, description, location_raw=location_raw
                )
                result.jobs.append(
                    RawJob(
                        company=company_name,
                        title=title,
                        url=absolute,
                        source="greenhouse",
                        ats_provider="greenhouse",
                        ats_job_id=job_id,
                        location_raw=location_raw,
                        apply_url=absolute,
                        description=description,
                        salary_raw=salary_raw,
                        salary_min=smin,
                        salary_max=smax,
                        salary_currency=scur,
                        posted_date=(item.get("updated_at") or item.get("created_at") or "")[:10] or None,
                        raw_payload=item,
                        description_complete=bool(description and str(description).strip()),
                    )
                )
        except Exception as exc:  # noqa: BLE001 — surface adapter failures
            result.errors.append(f"greenhouse {token}: {exc}")
        return result
