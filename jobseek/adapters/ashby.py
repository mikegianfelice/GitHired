"""Ashby public job board API adapter."""

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

# Official Public Job Posting API:
# GET .../posting-api/job-board/{board}?includeCompensation=true
# Compensation lives under jobs[].compensation with summaryComponents and
# compensationTiers[].components — never treat equity/bonus/commission as base.
_ANNUAL_INTERVALS = frozenset({"1 YEAR"})
_BASE_SALARY_TYPE = "Salary"


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


def _location_suggests_canada(location_raw: str | None) -> bool:
    """True when primary location text is Canada-facing (not US-only)."""
    blob = (location_raw or "").casefold()
    if not blob.strip():
        return False
    markers = (
        "canada",
        "toronto",
        "vancouver",
        "montréal",
        "montreal",
        "ottawa",
        "calgary",
        "edmonton",
        "ontario",
        "british columbia",
        "quebec",
        "québec",
        "alberta",
        "manitoba",
        "saskatchewan",
        "nova scotia",
    )
    return any(m in blob for m in markers)


def _tier_label(tier: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "tierSummary", "name", "label"):
        val = tier.get(key)
        if val:
            parts.append(str(val))
    return " ".join(parts)


def _canada_tier_components(compensation: dict[str, Any]) -> list[Any] | None:
    """Return salary components from Canada-labeled tiers, if any."""
    tiers = compensation.get("compensationTiers") or []
    if not isinstance(tiers, list):
        return None
    out: list[Any] = []
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        label = _tier_label(tier).casefold()
        if "canada" not in label and "canadian" not in label:
            continue
        comps = tier.get("components") or []
        if isinstance(comps, list):
            out.extend(comps)
    return out or None


def _annotate_location_arrangement(item: dict[str, Any], loc: str | None) -> str | None:
    """Prefer Ashby workplaceType over the isRemote boolean when labeling location.

    Cohere (and others) set isRemote=true with workplaceType=Hybrid. Annotating
    "(Remote)" from isRemote alone poisons downstream arrangement inference.
    """
    workplace = str(item.get("workplaceType") or item.get("workplace") or "").strip().casefold()
    is_remote = item.get("isRemote")
    base = (loc or "").strip() or None

    if workplace == "hybrid":
        if base and "hybrid" not in base.casefold():
            return f"{base} (Hybrid)"
        return base or "Hybrid"
    if workplace in {"onsite", "on-site", "office"}:
        return base
    if workplace == "remote" or is_remote:
        if base and "remote" not in base.casefold() and "hybrid" not in base.casefold():
            return f"{base} (Remote)"
        if not base:
            return "Remote"
    return base


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_annual_base_salary(component: dict[str, Any]) -> bool:
    """True only for annual Salary components — never equity/bonus/commission/hourly."""
    if not isinstance(component, dict):
        return False
    if str(component.get("compensationType") or "").strip() != _BASE_SALARY_TYPE:
        return False
    interval = str(component.get("interval") or "").strip().upper()
    return interval in _ANNUAL_INTERVALS


def _salary_from_components(
    components: list[Any],
) -> tuple[str | None, float | None, float | None, str | None]:
    """Extract annual base salary from Ashby compensation components.

    Multiple Salary components are accepted only when they share one currency.
    In that case we take the employer-published envelope (min of mins, max of
    maxes) — the same aggregation Ashby puts in ``summaryComponents`` / the
    scrapeable salary summary. Mixed currencies are refused (no invented FX).
    """
    salaries: list[tuple[float | None, float | None, str]] = []
    for raw in components:
        if not isinstance(raw, dict) or not _is_annual_base_salary(raw):
            continue
        currency = str(raw.get("currencyCode") or raw.get("currency") or "").strip().upper()
        if currency not in ("CAD", "USD"):
            continue
        amin = _as_float(raw.get("minValue") if "minValue" in raw else raw.get("min"))
        amax = _as_float(raw.get("maxValue") if "maxValue" in raw else raw.get("max"))
        if amin is None and amax is None:
            continue
        salaries.append((amin, amax, currency))

    if not salaries:
        return None, None, None, None

    currencies = {c for _, _, c in salaries}
    if len(currencies) != 1:
        # Do not invent a cross-currency range.
        return None, None, None, None

    currency = next(iter(currencies))
    mins = [v for v, _, _ in salaries if v is not None]
    maxs = [v for _, v, _ in salaries if v is not None]
    smin = min(mins) if mins else None
    smax = max(maxs) if maxs else None
    if smin is None and smax is None:
        return None, None, None, None
    if smin is None:
        smin = smax
    if smax is None:
        smax = smin
    raw = f"{currency} {smin:g}-{smax:g}"
    return raw, smin, smax, currency


def _collect_tier_components(compensation: dict[str, Any]) -> list[Any]:
    tiers = compensation.get("compensationTiers") or []
    out: list[Any] = []
    if not isinstance(tiers, list):
        return out
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        comps = tier.get("components") or []
        if isinstance(comps, list):
            out.extend(comps)
    return out


def _salary_from_description(
    description: str,
    *,
    location_raw: str | None,
) -> tuple[str | None, float | None, float | None, str | None]:
    """Fall back to employer prose when Ashby omits structured compensation.

    Common on multi-geo boards (e.g. 1Password): CAD/USD bands only in description.
    Never invents amounts — shared extractor requires clear evidence.
    """
    plain = strip_html(description or "")
    if not plain.strip():
        return None, None, None, None
    hint = currency_hint_from_location(location_raw)
    info = extract_salary_from_text(
        plain, currency_hint=hint, location_hint=location_raw
    )
    return apply_salary_info_to_raw(info=info)


def _salary(
    job: dict[str, Any],
    *,
    description: str | None = None,
    location_raw: str | None = None,
) -> tuple[str | None, float | None, float | None, str | None]:
    """Parse advertised annual base salary from an Ashby job posting payload.

    Prefer verified structured ``compensation`` components; fall back to
    description text when structure is absent or multi-currency (refused).
    """
    compensation = job.get("compensation")
    if isinstance(compensation, dict):
        # Prefer Canada geo tier when the posting's primary location is Canada-
        # facing. Ashby summaryComponents often envelope all geo bands
        # (e.g. US low + Canada high), which misstates the Canada range.
        if _location_suggests_canada(location_raw):
            canada_comps = _canada_tier_components(compensation)
            if canada_comps:
                parsed = _salary_from_components(canada_comps)
                if parsed[1] is not None or parsed[2] is not None:
                    return parsed

        # Prefer Ashby's published summary (already envelope-aggregated).
        summary = compensation.get("summaryComponents")
        if isinstance(summary, list) and summary:
            parsed = _salary_from_components(summary)
            if parsed[1] is not None or parsed[2] is not None:
                return parsed

        tier_comps = _collect_tier_components(compensation)
        if tier_comps:
            parsed = _salary_from_components(tier_comps)
            if parsed[1] is not None or parsed[2] is not None:
                return parsed

        # Legacy flat shape (minValue directly on compensation).
        if any(k in compensation for k in ("minValue", "maxValue", "min", "max")):
            parsed = _salary_from_components(
                [
                    {
                        "compensationType": _BASE_SALARY_TYPE,
                        "interval": "1 YEAR",
                        "currencyCode": compensation.get("currencyCode")
                        or compensation.get("currency"),
                        "minValue": compensation.get("minValue", compensation.get("min")),
                        "maxValue": compensation.get("maxValue", compensation.get("max")),
                    }
                ]
            )
            if parsed[1] is not None or parsed[2] is not None:
                return parsed

    # Rare: tiers at job root (older fixtures / partner feeds).
    root_tiers = job.get("compensationTiers")
    if isinstance(root_tiers, list) and root_tiers:
        comps: list[Any] = []
        for tier in root_tiers:
            if isinstance(tier, dict):
                tier_comps = tier.get("components") or []
                if isinstance(tier_comps, list):
                    comps.extend(tier_comps)
                elif any(k in tier for k in ("minValue", "maxValue")):
                    # Mis-shaped tier used as a salary blob
                    comps.append(
                        {
                            "compensationType": _BASE_SALARY_TYPE,
                            "interval": "1 YEAR",
                            "currencyCode": tier.get("currencyCode") or tier.get("currency"),
                            "minValue": tier.get("minValue", tier.get("min")),
                            "maxValue": tier.get("maxValue", tier.get("max")),
                        }
                    )
        parsed = _salary_from_components(comps)
        if parsed[1] is not None or parsed[2] is not None:
            return parsed

    # Legacy: job.salary flat object
    salary = job.get("salary")
    if isinstance(salary, dict):
        parsed = _salary_from_components(
            [
                {
                    "compensationType": _BASE_SALARY_TYPE,
                    "interval": "1 YEAR",
                    "currencyCode": salary.get("currencyCode") or salary.get("currency"),
                    "minValue": salary.get("minValue", salary.get("min")),
                    "maxValue": salary.get("maxValue", salary.get("max")),
                }
            ]
        )
        if parsed[1] is not None or parsed[2] is not None:
            return parsed

    return _salary_from_description(
        description or "",
        location_raw=location_raw or _location(job),
    )


class AshbyAdapter:
    name = "ashby"

    def __init__(self, client: RateLimitedClient | None = None) -> None:
        self.client = client or RateLimitedClient()

    def fetch_company(self, company: dict) -> AdapterResult:
        board = (company.get("board_token") or company.get("site_slug") or "").strip()
        if not board:
            return AdapterResult(errors=[f"ashby: missing board_token for {company.get('name')}"])
        # Compensation is omitted unless includeCompensation=true (Ashby docs).
        url = (
            f"https://api.ashbyhq.com/posting-api/job-board/{board}"
            f"?includeCompensation=true"
        )
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
                # Unpublished / unlisted postings occasionally appear; skip them.
                if item.get("isListed") is False:
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
                loc = _annotate_location_arrangement(item, _location(item))
                salary_raw, smin, smax, scur = _salary(
                    item, description=str(description or ""), location_raw=loc
                )
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
                        description_complete=bool(description and str(description).strip()),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"ashby {board}: {exc}")
        return result
