"""Orchestrate company discovery providers → validate → SQLite."""

from __future__ import annotations

from typing import Any

from jobseek.adapters.ashby import AshbyAdapter
from jobseek.adapters.gem import GemAdapter
from jobseek.adapters.greenhouse import GreenhouseAdapter
from jobseek.adapters.lever import LeverAdapter
from jobseek.adapters.rippling import RipplingAdapter
from jobseek.adapters.rss import RssAdapter
from jobseek.adapters.workable import WorkableAdapter
from jobseek.adapters.workday import WorkdayAdapter
from jobseek.companies.domain_util import canonical_domain
from jobseek.companies.providers.builtin_seed import collect_builtin_candidates
from jobseek.companies.providers.career_page import collect_career_page_candidates
from jobseek.companies.providers.careers_seed import collect_careers_seed_candidates
from jobseek.companies.providers.search_index import collect_search_index_candidates
from jobseek.companies.registry import (
    _company_key,
    _normalize_row,
    load_local_overrides,
    load_merged_companies,
)
from jobseek.companies.validate import persist_validation, validate_company
from jobseek.config_loader import Settings, load_search
from jobseek.db.store import Database
from jobseek.http_client import RateLimitedClient
from jobseek.identity import normalize_text
from jobseek.logging_util import log_extra, setup_logging

COMPANY_ADAPTERS: dict[str, type] = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "workable": WorkableAdapter,
    "rss": RssAdapter,
    "rippling": RipplingAdapter,
    "gem": GemAdapter,
    "workday": WorkdayAdapter,
}


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    order: list[tuple[str, ...]] = []
    for raw in candidates:
        row = _normalize_row(raw, layer=str(raw.get("discovery_source") or "discover"))
        key = _company_key(row)
        if key not in by_key:
            by_key[key] = row
            order.append(key)
        else:
            # Prefer rows that already have board tokens / concrete ats
            existing = by_key[key]
            if not existing.get("board_token") and row.get("board_token"):
                by_key[key] = {**existing, **row}
            elif row.get("ats") and existing.get("ats") in ("unknown", None, ""):
                by_key[key] = {**existing, **row}
    return [by_key[k] for k in order]


def run_companies_discover(
    db: Database,
    *,
    settings: Settings | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    settings = settings or Settings.from_env()
    logger = setup_logging(settings.log_level)
    search = load_search()
    cd = search.get("company_discovery") or {}
    providers = cd.get("providers") or {}
    auto_enable = bool(cd.get("auto_enable_validated", True))
    max_pages = int(cd.get("max_career_pages_per_run") or 40)
    max_queries = int(cd.get("max_search_queries") or 8)

    run_id = db.start_run("companies_discover")
    client = RateLimitedClient()
    summary: dict[str, Any] = {
        "candidates": 0,
        "upserted": 0,
        "validated": 0,
        "warnings": [],
        "results": [],
        "ok": True,
    }

    try:
        # Seed builtin into DB first (preserves prior validation)
        from jobseek.config_loader import load_companies

        db.seed_companies_from_yaml(load_companies())

        candidates: list[dict[str, Any]] = []
        if providers.get("builtin_seed", True):
            for c in collect_builtin_candidates(
                include_community=bool(providers.get("community", True))
            ):
                candidates.append(c.as_company_dict())

        merged = load_merged_companies(
            db_rows=db.list_companies(),
            overrides=load_local_overrides(),
            include_excluded=True,
        )

        # Careers-URL seeds fill gaps when search indexes are blocked (no tokens invented).
        seed_rows: list[dict[str, Any]] = []
        if providers.get("careers_seed", True):
            for c in collect_careers_seed_candidates(merged):
                d = c.as_company_dict()
                candidates.append(d)
                seed_rows.append(d)

        if providers.get("career_page", True):
            career_rows, warns = collect_career_page_candidates(
                list(merged) + seed_rows, client, max_pages=max_pages
            )
            summary["warnings"].extend(warns)
            for c in career_rows:
                candidates.append(c.as_company_dict())

        if providers.get("search_index", True):
            use_serpapi = bool(providers.get("serpapi", True)) and bool(settings.serpapi_key)
            search_rows, warns = collect_search_index_candidates(
                search,
                client,
                serpapi_key=settings.serpapi_key,
                max_queries=max_queries,
                use_serpapi=use_serpapi,
            )
            if warns and not search_rows:
                summary["warnings"].append(
                    "search_index returned no new employers (free web search often "
                    "rate-limits). Builtin + community registries and careers-page "
                    "detection still expand coverage without paid APIs."
                )
            summary["warnings"].extend(warns)
            for c in search_rows:
                candidates.append(c.as_company_dict())

        # Apply exclusions from local overrides before upsert
        overrides = load_local_overrides()
        deduped = _dedupe_candidates(candidates)
        summary["candidates"] = len(deduped)

        for company in deduped:
            # Honor exclude rules
            from jobseek.companies.registry import _matches_exclude

            excluded = False
            for rule in overrides.get("exclude") or []:
                if _matches_exclude(company, rule):
                    excluded = True
                    break
            company["excluded"] = excluded
            name = str(company.get("name") or "")
            if not name:
                continue
            # Overlay user company overrides
            for ov in overrides.get("companies") or []:
                if normalize_text(str(ov.get("name") or "")) == normalize_text(name):
                    company.update({k: v for k, v in ov.items() if v is not None})
            existing = None
            rows = [
                r
                for r in db.list_companies()
                if r.get("name_norm") == normalize_text(name)
            ]
            if rows:
                existing = rows[0]
            # Never invent tokens — skip unknown without token unless careers_url for later detect
            ats = (company.get("ats") or "unknown").lower()
            token = company.get("board_token")
            if ats not in COMPANY_ADAPTERS and ats != "unknown":
                company["validation_status"] = "unsupported"

            enabled = bool(company.get("enabled", False))
            if existing and existing.get("enabled") and not excluded:
                enabled = True
            # Builtin YAML / pre-validated community boards stay enabled
            if company.get("discovery_source") == "builtin" and company.get("evidence", {}).get(
                "enabled_in_yaml"
            ):
                enabled = True and not excluded
            if company.get("discovery_source") == "community" and company.get("evidence", {}).get(
                "enable"
            ):
                enabled = True and not excluded
            if company.get("enabled") and not excluded:
                enabled = True

            db.upsert_company(
                name=name,
                careers_url=company.get("careers_url"),
                ats=ats,
                board_token=token,
                validation_status=str(
                    existing.get("validation_status")
                    if existing and existing.get("validation_status") not in (None, "unvalidated")
                    else company.get("validation_status") or "unvalidated"
                ),
                industry=company.get("industry"),
                enabled=enabled and not excluded,
                notes=company.get("notes"),
                source=str(company.get("source") or "discover"),
                domain=company.get("domain")
                or canonical_domain(str(company.get("careers_url") or "")),
                discovery_source=company.get("discovery_source"),
                excluded=excluded,
                preserve_enabled=bool(existing),
            )
            summary["upserted"] += 1

        if validate:
            to_check = load_merged_companies(
                db_rows=db.list_companies(),
                overrides=load_local_overrides(),
            )
            # Prefer rows that have adapters + tokens
            checkable = [
                c
                for c in to_check
                if (c.get("ats") or "").lower() in COMPANY_ADAPTERS
                and (
                    c.get("board_token")
                    or (c.get("ats") or "").lower() == "rss"
                )
                and not c.get("excluded")
            ]
            for company in checkable:
                result = validate_company(
                    company,
                    adapters=COMPANY_ADAPTERS,
                    client=client,
                    auto_enable=auto_enable,
                )
                persist_validation(db, company, result)
                summary["validated"] += 1
                summary["results"].append(
                    {
                        "name": company.get("name"),
                        "status": result.status,
                        "enable": result.enable,
                        "jobs": result.evidence.get("job_count"),
                        "error": result.error,
                    }
                )

        db.finish_run(run_id, ok=True, summary=summary)
        log_extra(logger, 20, "companies_discover_complete", **{
            k: summary[k] for k in ("candidates", "upserted", "validated")
        })
        return summary
    except Exception as exc:  # noqa: BLE001
        summary["ok"] = False
        summary["errors"] = [str(exc)]
        db.add_run_event(run_id, "error", str(exc), {})
        db.finish_run(run_id, ok=False, summary=summary)
        raise
    finally:
        client.close()
