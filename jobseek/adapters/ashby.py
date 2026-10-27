"""Ashby public job board API adapter."""

from __future__ import annotations

from typing import Any

from jobseek.adapters.base import AdapterResult
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob


def _location(job: dict[str, Any]) -> str | None:
    loc = job.get("location")
    if isinstance(loc, str) and loc.strip():
        return loc
    locs = job.get("locations") or []
    if isinstance(locs, list) and locs:
        names = []
        for item in locs:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
        if names:
            return ", ".join(names)
    address = job.get("address") or {}
    if isinstance(address, dict) and address.get("postalAddress"):
        return str(address["postalAddress"])
    return None


def _salary(job: dict[str, Any]) -> tuple[str | None, float | None, float | None, str | None]:
    comp = job.get("compensation") or job.get("salary") or {}
    if not isinstance(comp, dict):
        # Ashby sometimes nests under compensationTier
        tiers = job.get("compensationTier") or []
        if isinstance(tiers, list) and tiers and isinstance(tiers[0], dict):
            comp = tiers[0]
        else:
            return None, None, None, None
    amin = comp.get("minValue") or comp.get("min")
    amax = comp.get("maxValue") or comp.get("max")
    currency = comp.get("currencyCode") or comp.get("currency")
    raw = None
    if amin is not None or amax is not None:
        raw = f"{currency or ''} {amin or ''}-{amax or ''}".strip()
    try:
        smin = float(amin) if amin is not None else None
        smax = float(amax) if amax is not None else None
    except (TypeError, ValueError):
        smin, smax = None, None
    return raw, smin, smax, str(currency) if currency else None


class AshbyAdapter:
    name = "ashby"

    def __init__(self, client: RateLimitedClient | None = None) -> None:
        self.client = client or RateLimitedClient()

    def fetch_company(self, company: dict) -> AdapterResult:
        board = (company.get("board_token") or company.get("site_slug") or "").strip()
        if not board:
            return AdapterResult(errors=[f"ashby: missing board_token for {company.get('name')}"])
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
        result = AdapterResult(request_key=f"ashby:{board}")
        try:
            resp = self.client.get(url)
            result.raw_status = resp.status_code
            if resp.status_code != 200:
                result.errors.append(f"ashby {board}: HTTP {resp.status_code}")
                return result
            payload = resp.json()
            jobs = []
            if isinstance(payload, dict):
                jobs = payload.get("jobs") or payload.get("jobPostings") or []
            elif isinstance(payload, list):
                jobs = payload
            company_name = company.get("name") or board
            for item in jobs:
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or item.get("name") or "").strip()
                job_url = (
                    item.get("jobUrl")
                    or item.get("applyUrl")
                    or item.get("externalLink")
                    or ""
                ).strip()
                job_id = str(item.get("id") or item.get("jobId") or "").strip() or None
                if not job_url and job_id:
                    job_url = f"https://jobs.ashbyhq.com/{board}/{job_id}"
                if not title or not job_url:
                    continue
                description = (
                    item.get("descriptionPlain")
                    or item.get("descriptionHtml")
                    or item.get("description")
                    or ""
                )
                salary_raw, smin, smax, scur = _salary(item)
                is_remote = item.get("isRemote")
                loc = _location(item)
                if is_remote and loc and "remote" not in loc.lower():
                    loc = f"{loc} (Remote)"
                elif is_remote and not loc:
                    loc = "Remote"
                result.jobs.append(
                    RawJob(
                        company=company_name,
                        title=title,
                        url=job_url,
                        source="ashby",
                        ats_provider="ashby",
                        ats_job_id=job_id,
                        location_raw=loc,
                        apply_url=item.get("applyUrl") or job_url,
                        description=description,
                        salary_raw=salary_raw,
                        salary_min=smin,
                        salary_max=smax,
                        salary_currency=scur,
                        posted_date=(item.get("publishedAt") or item.get("updatedAt") or "")[:10]
                        or None,
                        raw_payload=item,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"ashby {board}: {exc}")
        return result
