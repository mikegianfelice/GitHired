"""Ashby public job board API adapter."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

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
_CAD_TOKEN = re.compile(r"\b(?:CAD|CDN)\b|C\$|CA\$", re.I)
_USD_TOKEN = re.compile(r"\b(?:USD)\b|US\$", re.I)
# "base salary … USD" / "USD … base" — structured USD corroborated in prose.
_EXPLICIT_USD_BASE = re.compile(
    r"(?:base\s+salary|salary\s+range|annual\s+base).{0,40}\bUSD\b|"
    r"\bUSD\b.{0,40}(?:base\s+salary|salary\s+range|annual\s+base)",
    re.I | re.S,
)


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


def _location_suggests_usa(location_raw: str | None) -> bool:
    """True when primary location is US-facing and not also Canada-labeled."""
    blob = (location_raw or "").casefold()
    if not blob.strip() or _location_suggests_canada(location_raw):
        return False
    markers = (
        "united states",
        "u.s.a",
        "u.s.",
        "usa",
        "us -",
        "us remote",
        "remote - us",
        "remote, us",
    )
    if any(m in blob for m in markers):
        return True
    # Bare "US - Remote" / leading "US "
    return bool(re.match(r"^\s*us\b", blob))


def _tier_matches_labels(tier: dict[str, Any], labels: tuple[str, ...]) -> bool:
    label = _tier_label(tier).casefold()
    return any(token in label for token in labels)


_CANADA_TIER_LABELS = ("canada", "canadian")
_USA_TIER_LABELS = (
    "united states",
    "u.s.",
    "usa",
    "us -",
    "us,",
    "california",
    "new york",
    "all other states",
)


def _canada_tier_components(compensation: dict[str, Any]) -> list[Any] | None:
    """Return salary components from Canada-labeled tiers, if any."""
    tiers = compensation.get("compensationTiers") or []
    if not isinstance(tiers, list):
        return None
    out: list[Any] = []
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        if not _tier_matches_labels(tier, _CANADA_TIER_LABELS):
            continue
        comps = tier.get("components") or []
        if isinstance(comps, list):
            out.extend(comps)
    return out or None


def _usa_tier_components(compensation: dict[str, Any]) -> list[Any] | None:
    """Return salary components from USA-labeled tiers, if any."""
    tiers = compensation.get("compensationTiers") or []
    if not isinstance(tiers, list):
        return None
    out: list[Any] = []
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        if not _tier_matches_labels(tier, _USA_TIER_LABELS):
            continue
        comps = tier.get("components") or []
        if isinstance(comps, list):
            out.extend(comps)
    return out or None


def _compensation_prose(compensation: dict[str, Any] | None, description: str | None) -> str:
    """Concatenate employer-authored compensation prose (not currencyCode fields)."""
    parts: list[str] = []
    if isinstance(compensation, dict):
        for key in (
            "compensationTiersSummary",
            "scrapeableCompensationSalarySummary",
        ):
            val = compensation.get(key)
            if val:
                parts.append(str(val))
        for tier in compensation.get("compensationTiers") or []:
            if not isinstance(tier, dict):
                continue
            for key in ("tierSummary", "title", "additionalInformation", "summary"):
                val = tier.get(key)
                if val:
                    parts.append(str(val))
            for comp in tier.get("components") or []:
                if isinstance(comp, dict) and comp.get("summary"):
                    parts.append(str(comp["summary"]))
    if description:
        parts.append(strip_html(description))
    return "\n".join(parts)


def _reconcile_structured_currency(
    smin: float | None,
    smax: float | None,
    scur: str | None,
    *,
    location_raw: str | None,
    compensation: dict[str, Any] | None,
    description: str | None,
) -> tuple[float | None, float | None, str | None]:
    """Align structured currencyCode with Canada/US location + employer prose.

    Hopper (and similar) stamp ``currencyCode=USD`` on Canada Remote postings
    while tier summaries explicitly quote CAD total/base bands. Montreal twins
    publish the same numeric base band as CAD. Relabel only when CAD is
    evidenced in prose and USD is not corroborated as the Canada base currency.

    When prose CAD and explicit USD-base language both appear for a Canada
    listing, refuse rather than guess.
    """
    if scur not in ("CAD", "USD") or smin is None and smax is None:
        return smin, smax, scur

    prose = _compensation_prose(compensation, description)
    loc_ca = _location_suggests_canada(location_raw)

    if loc_ca and scur == "USD":
        prose_cad = bool(_CAD_TOKEN.search(prose))
        prose_usd_base = bool(_EXPLICIT_USD_BASE.search(prose))
        # Canada-named tiers that themselves declare USD (e.g. Cohere Senior
        # Staff DE) are employer-explicit — keep USD.
        canada_comps = (
            _canada_tier_components(compensation) if isinstance(compensation, dict) else None
        )
        canada_tier_usd = False
        if canada_comps:
            for raw in canada_comps:
                if not isinstance(raw, dict) or not _is_annual_base_salary(raw):
                    continue
                code = str(raw.get("currencyCode") or raw.get("currency") or "").strip().upper()
                if code == "USD":
                    canada_tier_usd = True
                    break
        if canada_tier_usd:
            return smin, smax, "USD"
        if prose_cad and prose_usd_base:
            # Conflicting explicit signals — do not invent a currency.
            return None, None, None
        if prose_cad:
            # Same numeric base band; currencyCode was wrong relative to prose
            # (Hopper Canada Remote vs Montréal CAD twin).
            return smin, smax, "CAD"

    return smin, smax, scur


def _tier_label(tier: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "tierSummary", "name", "label"):
        val = tier.get(key)
        if val:
            parts.append(str(val))
    return " ".join(parts)


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


def _finalize_structured_salary(
    parsed: tuple[str | None, float | None, float | None, str | None],
    *,
    location_raw: str | None,
    compensation: dict[str, Any] | None,
    description: str | None,
) -> tuple[str | None, float | None, float | None, str | None] | None:
    """Apply currency reconciliation; return None to try the next source."""
    _, smin, smax, scur = parsed
    if smin is None and smax is None:
        return None
    smin, smax, scur = _reconcile_structured_currency(
        smin,
        smax,
        scur,
        location_raw=location_raw,
        compensation=compensation,
        description=description,
    )
    if smin is None and smax is None:
        # Ambiguous currency — fall through to description extraction.
        return None
    if smin is None:
        smin = smax
    if smax is None:
        smax = smin
    raw = f"{scur} {smin:g}-{smax:g}" if scur else None
    return raw, smin, smax, scur


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
    loc = location_raw or _location(job)
    desc = description or ""
    compensation = job.get("compensation")
    if isinstance(compensation, dict):
        # Prefer geo-matched tiers. Ashby summaryComponents often envelopes
        # all bands (US + Canada) or stamps the wrong currencyCode on a
        # Canada Remote twin that publishes CAD in tier prose (Hopper).
        if _location_suggests_canada(loc):
            canada_comps = _canada_tier_components(compensation)
            if canada_comps:
                finalized = _finalize_structured_salary(
                    _salary_from_components(canada_comps),
                    location_raw=loc,
                    compensation=compensation,
                    description=desc,
                )
                if finalized is not None:
                    return finalized
        elif _location_suggests_usa(loc):
            usa_comps = _usa_tier_components(compensation)
            if usa_comps:
                finalized = _finalize_structured_salary(
                    _salary_from_components(usa_comps),
                    location_raw=loc,
                    compensation=compensation,
                    description=desc,
                )
                if finalized is not None:
                    return finalized

        # Prefer Ashby's published summary (already envelope-aggregated).
        summary = compensation.get("summaryComponents")
        if isinstance(summary, list) and summary:
            finalized = _finalize_structured_salary(
                _salary_from_components(summary),
                location_raw=loc,
                compensation=compensation,
                description=desc,
            )
            if finalized is not None:
                return finalized

        tier_comps = _collect_tier_components(compensation)
        if tier_comps:
            finalized = _finalize_structured_salary(
                _salary_from_components(tier_comps),
                location_raw=loc,
                compensation=compensation,
                description=desc,
            )
            if finalized is not None:
                return finalized

        # Legacy flat shape (minValue directly on compensation).
        if any(k in compensation for k in ("minValue", "maxValue", "min", "max")):
            finalized = _finalize_structured_salary(
                _salary_from_components(
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
                ),
                location_raw=loc,
                compensation=compensation,
                description=desc,
            )
            if finalized is not None:
                return finalized

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
        finalized = _finalize_structured_salary(
            _salary_from_components(comps),
            location_raw=loc,
            compensation=compensation if isinstance(compensation, dict) else None,
            description=desc,
        )
        if finalized is not None:
            return finalized

    # Legacy: job.salary flat object
    salary = job.get("salary")
    if isinstance(salary, dict):
        finalized = _finalize_structured_salary(
            _salary_from_components(
                [
                    {
                        "compensationType": _BASE_SALARY_TYPE,
                        "interval": "1 YEAR",
                        "currencyCode": salary.get("currencyCode") or salary.get("currency"),
                        "minValue": salary.get("minValue", salary.get("min")),
                        "maxValue": salary.get("maxValue", salary.get("max")),
                    }
                ]
            ),
            location_raw=loc,
            compensation=compensation if isinstance(compensation, dict) else None,
            description=desc,
        )
        if finalized is not None:
            return finalized

    return _salary_from_description(desc, location_raw=loc)


class AshbyAdapter:
    name = "ashby"

    def __init__(self, client: RateLimitedClient | None = None) -> None:
        self.client = client or RateLimitedClient()

    def fetch_company(self, company: dict) -> AdapterResult:
        board = (company.get("board_token") or company.get("site_slug") or "").strip()
        if not board:
            return AdapterResult(errors=[f"ashby: missing board_token for {company.get('name')}"])
        # Path-encode board tokens that contain spaces (e.g. "blackpoint cyber").
        board_path = quote(board, safe="")
        # Compensation is omitted unless includeCompensation=true (Ashby docs).
        url = (
            f"https://api.ashbyhq.com/posting-api/job-board/{board_path}"
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
