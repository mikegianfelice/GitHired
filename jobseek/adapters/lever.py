"""Lever public postings API adapter."""

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
    """Job-specific location — never company HQ.

    Append Lever ``country`` when the location text lacks an explicit country
    signal so US-only remote is not mistaken for Canada-eligible remote.
    """
    cats = job.get("categories") or {}
    loc = None
    if isinstance(cats, dict):
        loc = cats.get("location")
        if loc:
            loc = str(loc).strip()
    if not loc:
        raw = job.get("location")
        loc = str(raw).strip() if raw else None
    if not loc:
        return None

    country = str(job.get("country") or "").strip().upper()
    if not country:
        return loc

    loc_u = loc.upper()
    # Already names a country / US / Canada — leave employer text intact.
    if any(
        token in loc_u
        for token in (
            "USA",
            "U.S",
            "UNITED STATES",
            "CANADA",
            "CANADIAN",
            " UK",
            "U.K",
            "UNITED KINGDOM",
        )
    ) or loc_u.endswith(" US") or loc_u.startswith("US ") or ", US" in loc_u:
        return loc

    country_label = {
        "US": "USA",
        "USA": "USA",
        "CA": "Canada",
        "CAN": "Canada",
    }.get(country, country)
    return f"{loc}, {country_label}"


def _salary(
    job: dict[str, Any],
    *,
    description: str | None = None,
    location_raw: str | None = None,
) -> tuple[str | None, float | None, float | None, str | None]:
    """Parse Lever salaryRange with interval awareness.

    Prefer structured ``salaryRange``. Fall back to ``salaryDescriptionPlain``
    then full description prose. Annual intervals populate salary_min/max;
    hourly/monthly keep salary_raw only.
    """
    salary = job.get("salaryRange") or job.get("salary") or {}
    plain = job.get("salaryDescriptionPlain")
    plain_s = str(plain).strip() if plain else ""

    if isinstance(salary, dict):
        amin = salary.get("min")
        amax = salary.get("max")
        currency = salary.get("currency")
        interval = salary.get("interval")
        if amin is not None or amax is not None:
            try:
                smin = float(amin) if amin is not None else None
                smax = float(amax) if amax is not None else None
            except (TypeError, ValueError):
                smin = smax = None
            if smin is not None or smax is not None:
                structured_raw = f"{currency or ''} {smin or ''}-{smax or ''}".strip()
                raw = plain_s or structured_raw
                info = from_structured(
                    amin=smin,
                    amax=smax,
                    currency=str(currency) if currency else None,
                    interval=str(interval) if interval else None,
                    raw=raw,
                    source="structured_ats",
                )
                out_raw, out_min, out_max, out_cur = apply_salary_info_to_raw(info=info)
                if plain_s:
                    out_raw = plain_s
                if out_min is not None:
                    return out_raw, out_min, out_max, out_cur

    # Description / plain prose fallback (never invent).
    blob_parts = [plain_s, strip_html(description or "")]
    blob = " ".join(p for p in blob_parts if p).strip()
    if not blob:
        return (plain_s or None), None, None, None
    hint = currency_hint_from_location(location_raw)
    info = extract_salary_from_text(
        blob, currency_hint=hint, location_hint=location_raw
    )
    out_raw, out_min, out_max, out_cur = apply_salary_info_to_raw(info=info)
    if plain_s and not out_raw:
        out_raw = plain_s
    return out_raw, out_min, out_max, out_cur


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
                loc = _location(item)
                salary_raw, smin, smax, scur = _salary(
                    item, description=str(description or ""), location_raw=loc
                )
                result.jobs.append(
                    RawJob(
                        company=company_name,
                        title=title,
                        url=hosted,
                        source="lever",
                        ats_provider="lever",
                        ats_job_id=job_id,
                        location_raw=loc,
                        apply_url=item.get("applyUrl") or hosted,
                        description=description,
                        salary_raw=salary_raw,
                        salary_min=smin,
                        salary_max=smax,
                        salary_currency=scur,
                        posted_date=None,
                        raw_payload=item,
                        description_complete=bool(description and str(description).strip()),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"lever {site}: {exc}")
        return result
