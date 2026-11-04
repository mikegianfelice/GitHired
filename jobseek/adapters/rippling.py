"""Rippling public board API adapter (only when endpoint is stable).

List endpoint exposes title/location only — no compensation. Detail responses
may include ``payRangeDetails``; use ``fetch_job_salary`` during salary refresh
(not list-only discovery).
"""

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


def salary_from_rippling_detail(detail: dict[str, Any]) -> tuple[str | None, float | None, float | None, str | None]:
    """Extract annual base from Rippling job detail when publicly present."""
    pay = detail.get("payRangeDetails")
    components: list[dict[str, Any]] = []
    if isinstance(pay, list):
        components = [c for c in pay if isinstance(c, dict)]
    elif isinstance(pay, dict):
        components = [pay]

    for comp in components:
        # Observed shapes vary; accept explicit min/max + currency + period.
        amin = comp.get("min") or comp.get("minValue") or comp.get("minimum")
        amax = comp.get("max") or comp.get("maxValue") or comp.get("maximum")
        currency = (
            comp.get("currency")
            or comp.get("currencyCode")
            or comp.get("currency_code")
        )
        interval = (
            comp.get("interval")
            or comp.get("period")
            or comp.get("frequency")
            or comp.get("payPeriod")
        )
        if amin is None and amax is None:
            continue
        try:
            smin = float(amin) if amin is not None else None
            smax = float(amax) if amax is not None else None
        except (TypeError, ValueError):
            continue
        info = from_structured(
            amin=smin,
            amax=smax,
            currency=str(currency) if currency else None,
            interval=str(interval) if interval else "year",
            raw=str(comp),
            source="structured_ats",
        )
        raw, out_min, out_max, out_cur = apply_salary_info_to_raw(info=info)
        if out_min is not None:
            return raw, out_min, out_max, out_cur

    # jsonLd baseSalary (schema.org) when present
    ld = detail.get("jsonLd")
    if isinstance(ld, dict):
        base = ld.get("baseSalary")
        if isinstance(base, dict):
            value = base.get("value")
            currency = base.get("currency")
            amin = amax = None
            interval = None
            if isinstance(value, dict):
                amin = value.get("minValue") or value.get("value")
                amax = value.get("maxValue") or value.get("value")
                interval = value.get("unitText") or base.get("unitText")
            elif isinstance(value, (int, float)):
                amin = amax = float(value)
            info = from_structured(
                amin=float(amin) if amin is not None else None,
                amax=float(amax) if amax is not None else None,
                currency=str(currency) if currency else None,
                interval=str(interval) if interval else "YEAR",
                raw=str(base),
                source="structured_ats",
            )
            return apply_salary_info_to_raw(info=info)

    # Description HTML fallback
    desc = detail.get("description")
    text = ""
    if isinstance(desc, dict):
        text = " ".join(str(desc.get(k) or "") for k in ("role", "company", "text", "html"))
    elif isinstance(desc, str):
        text = desc
    if text.strip():
        return apply_salary_info_to_raw(info=extract_salary_from_text(strip_html(text)))
    return None, None, None, None


class RipplingAdapter:
    name = "rippling"

    def __init__(self, client: RateLimitedClient | None = None) -> None:
        self.client = client or RateLimitedClient()

    def fetch_job_salary(self, board_token: str, job_id: str) -> tuple[str | None, float | None, float | None, str | None]:
        token = board_token.strip()
        jid = job_id.strip()
        if not token or not jid:
            return None, None, None, None
        url = f"https://ats.rippling.com/api/v2/board/{token}/jobs/{jid}"
        resp = self.client.get(url)
        if resp.status_code != 200:
            return None, None, None, None
        try:
            detail = resp.json()
        except Exception:  # noqa: BLE001
            return None, None, None, None
        if not isinstance(detail, dict):
            return None, None, None, None
        return salary_from_rippling_detail(detail)

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
                description = item.get("description") or item.get("jobDescription") or None
                salary_raw = smin = smax = scur = None
                if description:
                    info = extract_salary_from_text(strip_html(str(description)))
                    salary_raw, smin, smax, scur = apply_salary_info_to_raw(info=info)
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
                        description=description,
                        salary_raw=salary_raw,
                        salary_min=smin,
                        salary_max=smax,
                        salary_currency=scur,
                        raw_payload=item,
                        description_complete=bool(description and str(description).strip()),
                    )
                )
            return result
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"rippling {token}: {exc}")
            return result
