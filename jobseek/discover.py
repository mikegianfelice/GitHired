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
    companies = _enabled_companies(load_companies(), sources)

    run_id = db.start_run("discover")
    client = RateLimitedClient()
    summary: dict[str, Any] = {
        "fetched": 0,
        "new": 0,
        "updated": 0,
        "errors": [],
        "detections": [],
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
            for company in load_companies():
                if not company.get("enabled", True):
                    continue
                ats = (company.get("ats") or "unknown").lower()
                careers = company.get("careers_url") or ""
                if ats not in ("unknown", "") or not careers:
                    continue
                try:
                    detection = detect_careers_page(careers, client)
                    if detection:
                        summary["detections"].append(
                            {
                                "company": company.get("name"),
                                "ats": detection.ats,
                                "board_token": detection.board_token,
                                "confidence": detection.confidence,
                            }
                        )
                        db.add_run_event(
                            run_id,
                            "info",
                            "ats_detected",
                            {
                                "company": company.get("name"),
                                "ats": detection.ats,
                                "board_token": detection.board_token,
                            },
                        )
                except Exception as exc:  # noqa: BLE001
                    summary["errors"].append(f"detect {company.get('name')}: {exc}")

        adapter_instances = {
            name: cls(client) for name, cls in ADAPTERS.items() if sources.get(name, True)
        }

        for company in companies:
            ats = (company.get("ats") or "").lower()
            adapter = adapter_instances.get(ats)
            if not adapter:
                continue
            result = adapter.fetch_company(company)
            if result.raw_status is not None:
                db.store_raw(
                    source=ats,
                    request_key=result.request_key,
                    status_code=result.raw_status,
                    body=json.dumps([j.to_dict() for j in result.jobs], ensure_ascii=False)[:500000],
                )
            for err in result.errors:
                summary["errors"].append(err)
                db.add_run_event(run_id, "error", err, {"company": company.get("name")})
                log_extra(logger, 40, err, company=company.get("name"), ats=ats)
            if result.raw_status == 200:
                company_name = company.get("name") or ""
                if ats in fetched_companies and company_name:
                    fetched_companies[ats].add(company_name)
            for job in result.jobs:
                summary["fetched"] += 1
                job_id, is_new = db.upsert_job(job)
                if ats in seen_by_source:
                    seen_by_source[ats].add(job_id)
                if is_new:
                    summary["new"] += 1
                else:
                    summary["updated"] += 1

        # LinkedIn search-index (compliant)
        if sources.get("linkedin_search_index", True):
            li = LinkedInSearchIndexAdapter(api_key=settings.serpapi_key, client=client)
            queries = list(search.get("linkedin_search_queries") or [])
            li_result = li.search(queries)
            for err in li_result.errors:
                summary["errors"].append(err)
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

        db.finish_run(run_id, ok=len(summary["errors"]) == 0, summary=summary)
        log_extra(logger, 20, "discover_complete", **{k: v for k, v in summary.items() if k != "errors"})
        return summary
    except Exception as exc:  # noqa: BLE001
        db.add_run_event(run_id, "error", str(exc), {})
        db.finish_run(run_id, ok=False, summary={**summary, "fatal": str(exc)})
        raise
    finally:
        client.close()
