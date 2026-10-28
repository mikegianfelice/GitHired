"""Discovery orchestration across ATS adapters and compliant LinkedIn sources."""

from __future__ import annotations

import json
from typing import Any

from jobseek.adapters.ashby import AshbyAdapter
from jobseek.adapters.detector import detect_careers_page
from jobseek.adapters.greenhouse import GreenhouseAdapter
from jobseek.adapters.lever import LeverAdapter
from jobseek.adapters.linkedin_compliant import LinkedInSearchIndexAdapter
from jobseek.config_loader import Settings, load_companies, load_search
from jobseek.db.store import Database
from jobseek.http_client import RateLimitedClient
from jobseek.logging_util import log_extra, setup_logging


ADAPTERS = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
}


def _enabled_companies(companies: list[dict], sources: dict[str, Any]) -> list[dict]:
    out = []
    for company in companies:
        if not company.get("enabled", True):
            continue
        ats = (company.get("ats") or "unknown").lower()
        if ats in ("greenhouse", "lever", "ashby") and not sources.get(ats, True):
            continue
        out.append(company)
    return out


def _source_status(sources: dict[str, Any], settings: Settings) -> dict[str, Any]:
    enabled = []
    skipped = []
    for name in ("greenhouse", "lever", "ashby", "career_pages"):
        if sources.get(name, True):
            enabled.append(name)
        else:
            skipped.append({"source": name, "reason": "disabled in search.yaml"})
    if sources.get("linkedin_search_index", True):
        if settings.serpapi_key:
            enabled.append("linkedin_search_index:serpapi")
        else:
            enabled.append("linkedin_search_index:free")
    else:
        skipped.append({"source": "linkedin_search_index", "reason": "disabled in search.yaml"})
    if sources.get("linkedin_alert_import", True):
        enabled.append("linkedin_alert_import")
    else:
        skipped.append({"source": "linkedin_alert_import", "reason": "disabled in search.yaml"})
    if sources.get("linkedin_guest"):
        skipped.append(
            {
                "source": "linkedin_guest",
                "reason": "not implemented in jobseek; use portal CLI interactively if needed",
            }
        )
    if sources.get("freehire"):
        skipped.append(
            {
                "source": "freehire",
                "reason": "not wired into jobseek discover yet",
            }
        )
    return {"sources_enabled": enabled, "sources_skipped": skipped}


def run_discover(
    db: Database,
    *,
    settings: Settings | None = None,
    detect_unknown: bool = True,
) -> dict[str, Any]:
    settings = settings or Settings.from_env()
    logger = setup_logging(settings.log_level)
    search = load_search()
    sources = search.get("sources") or {}
    yaml_companies = load_companies()
    db.seed_companies_from_yaml(yaml_companies)
    companies = _enabled_companies(yaml_companies, sources)

    run_id = db.start_run("discover")
    client = RateLimitedClient()
    source_info = _source_status(sources, settings)
    summary: dict[str, Any] = {
        "fetched": 0,
        "new": 0,
        "updated": 0,
        "errors": [],
        "warnings": [],
        "detections": [],
        **source_info,
    }
    seen_by_source: dict[str, set[int]] = {
        "greenhouse": set(),
        "lever": set(),
        "ashby": set(),
    }
    fetched_companies: dict[str, set[str]] = {
        "greenhouse": set(),
        "lever": set(),
        "ashby": set(),
    }

    try:
        # Optional ATS auto-detect for unknown careers pages
        if detect_unknown and sources.get("career_pages", True):
            for company in yaml_companies:
                if not company.get("enabled", True):
                    continue
                ats = (company.get("ats") or "unknown").lower()
                careers = company.get("careers_url") or ""
                if ats not in ("unknown", "") or not careers:
                    continue
                try:
                    detection = detect_careers_page(careers, client)
                    if detection and detection.board_token and detection.ats in ADAPTERS:
                        # Validate by fetching before persisting
                        adapter = ADAPTERS[detection.ats](client)
                        probe = adapter.fetch_company(
                            {
                                **company,
                                "ats": detection.ats,
                                "board_token": detection.board_token,
                            }
                        )
                        if probe.raw_status == 200:
                            db.upsert_company(
                                name=str(company.get("name") or detection.board_token),
                                careers_url=careers,
                                ats=detection.ats,
                                board_token=detection.board_token,
                                validation_status="ok",
                                last_success_at=None,
                                source="detect",
                            )
                            # Use detection for this run
                            company["ats"] = detection.ats
                            company["board_token"] = detection.board_token
                            if company not in companies:
                                companies.append(company)
                            summary["detections"].append(
                                {
                                    "company": company.get("name"),
                                    "ats": detection.ats,
                                    "board_token": detection.board_token,
                                    "confidence": detection.confidence,
                                    "persisted": True,
                                }
                            )
                        else:
                            summary["warnings"].append(
                                f"detect {company.get('name')}: validation fetch failed "
                                f"(HTTP {probe.raw_status})"
                            )
                    elif detection:
                        summary["detections"].append(
                            {
                                "company": company.get("name"),
                                "ats": detection.ats,
                                "board_token": detection.board_token,
                                "confidence": detection.confidence,
                                "persisted": False,
                                "reason": "no validating adapter or missing token",
                            }
                        )
                except Exception as exc:  # noqa: BLE001
                    summary["warnings"].append(f"detect {company.get('name')}: {exc}")

        adapter_instances = {
            name: cls(client) for name, cls in ADAPTERS.items() if sources.get(name, True)
        }

        for company in companies:
            ats = (company.get("ats") or "").lower()
            adapter = adapter_instances.get(ats)
            if not adapter:
                continue
            result = adapter.fetch_company(company)
            company_name = company.get("name") or ""
            if result.raw_status is not None:
                db.store_raw(
                    source=ats,
                    request_key=result.request_key,
                    status_code=result.raw_status,
                    body=json.dumps([j.to_dict() for j in result.jobs], ensure_ascii=False)[:500000],
                )
            for err in result.errors:
                summary["errors"].append(err)
                db.add_run_event(run_id, "error", err, {"company": company_name})
                log_extra(logger, 40, err, company=company_name, ats=ats)
            if result.raw_status == 200:
                if ats in fetched_companies and company_name:
                    fetched_companies[ats].add(company_name)
                db.mark_company_fetch(
                    company_name,
                    ok=True,
                    ats=ats,
                    board_token=company.get("board_token") or company.get("site_slug"),
                )
            else:
                if company_name:
                    db.mark_company_fetch(
                        company_name,
                        ok=False,
                        ats=ats,
                        board_token=company.get("board_token") or company.get("site_slug"),
                        error="; ".join(result.errors) or f"HTTP {result.raw_status}",
                    )
            for job in result.jobs:
                summary["fetched"] += 1
                job_id, is_new = db.upsert_job(job)
                if ats in seen_by_source:
                    seen_by_source[ats].add(job_id)
                if is_new:
                    summary["new"] += 1
                else:
                    summary["updated"] += 1

        # LinkedIn search-index (compliant) — warnings must not fail the run
        if sources.get("linkedin_search_index", True):
            li = LinkedInSearchIndexAdapter(api_key=settings.serpapi_key, client=client)
            queries = list(search.get("linkedin_search_queries") or [])
            li_result = li.search(queries)
            for err in li_result.errors:
                summary["warnings"].append(err)
                db.add_run_event(run_id, "warning", err, {})
            if li_result.jobs:
                db.store_raw(
                    source="linkedin_search_index",
                    request_key=li_result.request_key,
                    status_code=li_result.raw_status,
                    body=json.dumps([j.to_dict() for j in li_result.jobs], ensure_ascii=False)[:500000],
                )
            for job in li_result.jobs:
                summary["fetched"] += 1
                job_id, is_new = db.upsert_job(job)
                if is_new:
                    summary["new"] += 1
                else:
                    summary["updated"] += 1

        removed = 0
        for source, ids in seen_by_source.items():
            companies_ok = fetched_companies.get(source) or set()
            if ids and companies_ok:
                removed += db.mark_missing_removed(
                    source_prefix=source,
                    seen_ids=ids,
                    companies=companies_ok,
                )
        summary["removed_marked"] = removed

        # Hard errors = ATS fetch errors only; LinkedIn warnings do not fail the run
        ok = len(summary["errors"]) == 0
        db.finish_run(run_id, ok=ok, summary=summary)
        log_extra(logger, 20, "discover_complete", **{k: v for k, v in summary.items() if k not in ("errors", "warnings")})
        return summary
    except Exception as exc:  # noqa: BLE001
        db.add_run_event(run_id, "error", str(exc), {})
        db.finish_run(run_id, ok=False, summary={**summary, "fatal": str(exc)})
        raise
    finally:
        client.close()
