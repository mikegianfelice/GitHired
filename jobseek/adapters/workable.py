"""Workable public widget API adapter.

The public widget list endpoint does **not** expose salary fields. Structured
pay (`salary_from` / `salary_to` / `salary_currency_iso_code` / `salary_frequency`)
is available on the public job detail endpoint
``/api/v2/accounts/{token}/jobs/{shortcode}`` and is fetched by
``fetch_job_salary`` during salary refresh / optional enrichment — never during
list-only discovery for every posting.
"""

from __future__ import annotations

from typing import Any

from jobseek.adapters.base import AdapterResult
from jobseek.filters.salary import (
    apply_salary_info_to_raw,
    currency_hint_from_location,
    extract_salary_from_text,
    from_structured,
    strip_html,
)
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


def salary_from_workable_detail(detail: dict[str, Any]) -> tuple[str | None, float | None, float | None, str | None]:
    """Extract annual base from a Workable v2 job detail payload."""
    amin = detail.get("salary_from")
    amax = detail.get("salary_to")
    currency = detail.get("salary_currency_iso_code") or detail.get("salary_currency")
    frequency = detail.get("salary_frequency") or detail.get("salary_period")
    if amin is not None or amax is not None:
        try:
            smin = float(amin) if amin is not None else None
            smax = float(amax) if amax is not None else None
        except (TypeError, ValueError):
            smin = smax = None
        info = from_structured(
            amin=smin,
            amax=smax,
            currency=str(currency) if currency else None,
            interval=str(frequency) if frequency else None,
            raw=f"{currency or ''} {amin}-{amax}".strip(),
            source="structured_ats",
        )
        return apply_salary_info_to_raw(info=info)

    # Description fallback on detail payloads
    desc = detail.get("description") or ""
    if isinstance(desc, dict):
        desc = desc.get("text") or desc.get("html") or ""
    loc = _location(detail)
    hint = currency_hint_from_location(loc)
    info = extract_salary_from_text(
        strip_html(str(desc)), currency_hint=hint, location_hint=loc
    )
    return apply_salary_info_to_raw(info=info)


class WorkableAdapter:
    name = "workable"

    def __init__(self, client: RateLimitedClient | None = None) -> None:
        self.client = client or RateLimitedClient()

    def fetch_job_salary(self, board_token: str, shortcode: str) -> tuple[str | None, float | None, float | None, str | None]:
        """Public detail fetch for structured compensation (salary refresh only)."""
        token = board_token.strip()
        code = shortcode.strip()
        if not token or not code:
            return None, None, None, None
        url = f"https://apply.workable.com/api/v2/accounts/{token}/jobs/{code}"
        resp = self.client.get(url)
        if resp.status_code != 200:
            return None, None, None, None
        try:
            detail = resp.json()
        except Exception:  # noqa: BLE001
            return None, None, None, None
        if not isinstance(detail, dict):
            return None, None, None, None
        return salary_from_workable_detail(detail)

    def fetch_company(self, company: dict) -> AdapterResult:
        token = (company.get("board_token") or company.get("site_slug") or "").strip()
        if not token:
            return AdapterResult(errors=[f"workable: missing board_token for {company.get('name')}"])
        # Public widget API — no API key required; list has no salary fields.
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
                desc_s = str(description) if description else ""
                location_raw = _location(item)
                salary_raw = smin = smax = scur = None
                if desc_s.strip():
                    hint = currency_hint_from_location(location_raw)
                    info = extract_salary_from_text(
                        strip_html(desc_s),
                        currency_hint=hint,
                        location_hint=location_raw,
                    )
                    salary_raw, smin, smax, scur = apply_salary_info_to_raw(info=info)
                result.jobs.append(
                    RawJob(
                        company=str(company_name),
                        title=title,
                        url=absolute,
                        apply_url=absolute,
                        source="workable",
                        ats_provider="workable",
                        ats_job_id=shortcode or None,
                        location_raw=location_raw,
                        description=desc_s or None,
                        salary_raw=salary_raw,
                        salary_min=smin,
                        salary_max=smax,
                        salary_currency=scur,
                        posted_date=(item.get("published_on") or item.get("created_at") or None),
                        raw_payload=item,
                        description_complete=bool(desc_s.strip()),
                    )
                )
            return result
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"workable {token}: {exc}")
            return result
