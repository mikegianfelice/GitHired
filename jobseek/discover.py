"""Discovery orchestration across ATS adapters and compliant LinkedIn sources."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from jobseek.adapters.ashby import AshbyAdapter
from jobseek.adapters.detector import detect_careers_page
from jobseek.adapters.gem import GemAdapter
from jobseek.adapters.greenhouse import GreenhouseAdapter
from jobseek.adapters.lever import LeverAdapter
from jobseek.adapters.linkedin_compliant import LinkedInSearchIndexAdapter
from jobseek.adapters.rippling import RipplingAdapter
from jobseek.adapters.rss import RssAdapter
from jobseek.adapters.workable import WorkableAdapter
from jobseek.adapters.freehire import FreehireAdapter, default_freehire_queries
from jobseek.adapters.workday import WorkdayAdapter
from jobseek.companies.registry import load_local_overrides, load_merged_companies
from jobseek.config_loader import Settings, load_companies, load_search
from jobseek.db.store import Database
from jobseek.http_client import RateLimitedClient
from jobseek.logging_util import log_extra, setup_logging

logger = logging.getLogger("jobseek.discover")

ADAPTERS = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "workable": WorkableAdapter,
    "rss": RssAdapter,
    "rippling": RipplingAdapter,
    "gem": GemAdapter,
    "workday": WorkdayAdapter,
}

_FETCHABLE_ATS = tuple(ADAPTERS.keys())


def _enabled_companies(companies: list[dict], sources: dict[str, Any]) -> list[dict]:
    out = []
    for company in companies:
        if company.get("excluded"):
            continue
        if not company.get("enabled", True):
            continue
        ats = (company.get("ats") or "unknown").lower()
        if ats in _FETCHABLE_ATS and not sources.get(ats, True):
            continue
        out.append(company)
    return out


def _source_status(sources: dict[str, Any], settings: Settings) -> dict[str, Any]:
    enabled = []
    skipped = []
    for name in (
        "greenhouse",
        "lever",
        "ashby",
        "workable",
        "rss",
        "rippling",
        "workday",
        "gem",
        "career_pages",
    ):
        default = name != "gem"
        if sources.get(name, default):
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
        enabled.append("freehire")
    else:
        skipped.append(
            {
                "source": "freehire",
                "reason": "disabled in search.yaml (optional aggregator; default off)",
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
    merged = load_merged_companies(
        builtin=yaml_companies,
        db_rows=db.list_companies(),
        overrides=load_local_overrides(),
    )
    companies = _enabled_companies(merged, sources)

    run_id = db.start_run("discover")
    client = RateLimitedClient()
    source_info = _source_status(sources, settings)
    summary: dict[str, Any] = {
        "fetched": 0,
        "new": 0,
        "updated": 0,
        "errors": [],
        "warnings": [],
        "board_failures": [],
        "boards_ok": [],
        "detections": [],
        **source_info,
    }
    boards_attempted = 0
    boards_ok = 0
    seen_by_source: dict[str, set[int]] = {name: set() for name in ADAPTERS}
    fetched_companies: dict[str, set[str]] = {name: set() for name in ADAPTERS}

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

        workday_complete = bool(sources.get("workday_complete", False))
        workday_budget = sources.get("workday_company_budget_s", 120)
        try:
            workday_budget_f = float(workday_budget) if workday_budget is not None else 120.0
        except (TypeError, ValueError):
            workday_budget_f = 120.0

        adapter_instances: dict[str, Any] = {}
        for name, cls in ADAPTERS.items():
            if not sources.get(name, name != "gem"):
                continue
            if name == "workday":
                adapter_instances[name] = cls(
                    client,
                    company_budget_s=None if workday_complete else workday_budget_f,
                    complete=workday_complete,
                )
            else:
                adapter_instances[name] = cls(client)

        total_boards = len(
            [
                c
                for c in companies
                if (c.get("ats") or "").lower() in adapter_instances
            ]
        )
        discover_t0 = time.monotonic()
        logger.info(
            "discover fetch start boards=%s workday_complete=%s workday_budget_s=%s",
            total_boards,
            workday_complete,
            "complete" if workday_complete else workday_budget_f,
        )

        for company in companies:
            ats = (company.get("ats") or "").lower()
            adapter = adapter_instances.get(ats)
            if not adapter:
                summary["warnings"].append(
                    f"{company.get('name')}: ats={ats} has no fetch adapter "
                    "(registry entry retained; enable when adapter exists)"
                )
                continue
            boards_attempted += 1
            company_name = company.get("name") or ""
            logger.info(
                "discover board %s/%s company=%s ats=%s fetched_so_far=%s elapsed_s=%.1f",
                boards_attempted,
                total_boards,
                company_name,
                ats,
                summary["fetched"],
                time.monotonic() - discover_t0,
            )
            try:
                result = adapter.fetch_company(company)
            except Exception as exc:  # noqa: BLE001 — never let one board abort the run
                summary["warnings"].append(f"{ats} {company_name}: unhandled {exc}")
                db.add_run_event(
                    run_id,
                    "warning",
                    f"{ats} {company_name}: {exc}",
                    {"company": company_name, "ats": ats},
                )
                logger.warning(
                    "discover board failed company=%s ats=%s err=%s",
                    company_name,
                    ats,
                    exc,
                )
                continue
            if result.raw_status is not None:
                db.store_raw(
                    source=ats,
                    request_key=result.request_key,
                    status_code=result.raw_status,
                    body=json.dumps([j.to_dict() for j in result.jobs], ensure_ascii=False)[:500000],
                )
            if result.raw_status == 200 and not result.errors:
                boards_ok += 1
                summary["boards_ok"].append(company_name)
                if ats in fetched_companies and company_name:
                    fetched_companies[ats].add(company_name)
                db.mark_company_fetch(
                    company_name,
                    ok=True,
                    ats=ats,
                    board_token=company.get("board_token") or company.get("site_slug"),
                    empty=not result.jobs,
                )
                # Empty successful board is not a failure
                if not result.jobs:
                    summary["warnings"].append(
                        f"{company_name}: board OK but returned 0 jobs (empty board)"
                    )
            elif result.raw_status == 200 and result.jobs:
                # Structure warnings but jobs parsed — treat as success
                boards_ok += 1
                summary["boards_ok"].append(company_name)
                if ats in fetched_companies and company_name:
                    fetched_companies[ats].add(company_name)
                db.mark_company_fetch(
                    company_name,
                    ok=True,
                    ats=ats,
                    board_token=company.get("board_token") or company.get("site_slug"),
                )
            else:
                detail = "; ".join(result.errors) or f"HTTP {result.raw_status}"
                failure = {
                    "company": company_name,
                    "ats": ats,
                    "board_token": company.get("board_token") or company.get("site_slug"),
                    "status_code": result.raw_status,
                    "detail": detail,
                }
                summary["board_failures"].append(failure)
                summary["warnings"].append(f"{ats} {company_name}: {detail}")
                db.add_run_event(run_id, "warning", detail, failure)
                log_extra(logger, 30, detail, company=company_name, ats=ats)
                if company_name:
                    db.mark_company_fetch(
                        company_name,
                        ok=False,
                        ats=ats,
                        board_token=company.get("board_token") or company.get("site_slug"),
                        error=detail,
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

        # Optional Freehire aggregator — default off; soft-fail on provider errors
        if sources.get("freehire"):
            fh = FreehireAdapter(client=client)
            fh_queries = default_freehire_queries(search)
            fh_result = fh.search(fh_queries)
            fh_stats = getattr(fh, "last_stats", {}) or {}
            summary["freehire"] = fh_stats
            for err in fh_result.errors:
                summary["warnings"].append(err)
                db.add_run_event(run_id, "warning", err, {"source": "freehire"})
            if fh_result.jobs:
                db.store_raw(
                    source="freehire",
                    request_key=fh_result.request_key,
                    status_code=fh_result.raw_status,
                    body=json.dumps(
                        [j.to_dict() for j in fh_result.jobs], ensure_ascii=False
                    )[:500000],
                )
            for job in fh_result.jobs:
                summary["fetched"] += 1
                job_id, is_new = db.upsert_job(job)
                if is_new:
                    summary["new"] += 1
                else:
                    summary["updated"] += 1
            if fh_stats.get("affiliate_rejected"):
                summary["warnings"].append(
                    f"freehire: {fh_stats['affiliate_rejected']} affiliate-only "
                    "URL(s) stored as freehire_review (excluded from confirmed shortlist)"
                )

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

        summary["boards_attempted"] = boards_attempted
        summary["boards_succeeded"] = boards_ok
        # Partial board failures are warnings. Fatal only when every attempted
        # board failed AND nothing was fetched (empty successful search is OK).
        all_boards_failed = boards_attempted > 0 and boards_ok == 0
        if all_boards_failed and summary["fetched"] == 0:
            summary["errors"].append(
                "all enabled ATS boards failed and no jobs were fetched"
            )
        ok = len(summary["errors"]) == 0
        summary["ok"] = ok
        db.finish_run(run_id, ok=ok, summary=summary)
        log_extra(
            logger,
            20,
            "discover_complete",
            **{k: v for k, v in summary.items() if k not in ("errors", "warnings", "board_failures")},
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        db.add_run_event(run_id, "error", str(exc), {})
        db.finish_run(run_id, ok=False, summary={**summary, "fatal": str(exc)})
        raise
    finally:
        client.close()
