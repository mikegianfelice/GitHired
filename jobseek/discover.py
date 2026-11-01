"""Discovery orchestration across ATS adapters and compliant LinkedIn sources."""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from jobseek.adapters.ashby import AshbyAdapter
from jobseek.adapters.base import AdapterResult
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
    mode: str = "standard",
    force_refresh_descriptions: bool = False,
) -> dict[str, Any]:
    """Run ATS listing discovery (list-only; details via ``githired enrich``).

    Modes (listing pace / budgets):
      - ``quick``: shorter list budgets; bounded concurrency; daily incremental.
      - ``standard``: default list budgets; Workday description cache applied from
        SQLite without detail HTTP (complete bodies restored when present).
      - ``deep``: no list budget; still list-only — run ``githired enrich --mode deep``
        for full description refresh.

    Detail hydration was removed from discover so first results appear quickly.
    """
    settings = settings or Settings.from_env()
    logger = setup_logging(settings.log_level)
    search = load_search()
    sources = search.get("sources") or {}
    mode_norm = (mode or "standard").strip().lower()
    if mode_norm not in ("quick", "standard", "deep", "full"):
        mode_norm = "standard"
    if mode_norm == "full":
        mode_norm = "deep"
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
    # Per-company Workday clients (closed in finally) — avoid shared throttle starvation.
    workday_clients: list[RateLimitedClient] = []
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
        "by_company": [],
        "by_ats": {},
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

        workday_complete = bool(sources.get("workday_complete", False)) or mode_norm == "deep"
        force_refresh = bool(force_refresh_descriptions) or mode_norm == "deep"

        def _f(key: str, default: float) -> float:
            raw = sources.get(key, default)
            try:
                return float(raw) if raw is not None else float(default)
            except (TypeError, ValueError):
                return float(default)

        list_budget = _f("workday_list_budget_s", 90.0 if mode_norm == "quick" else 180.0)
        detail_budget = _f(
            "workday_detail_budget_s",
            sources.get("workday_company_budget_s", 60.0 if mode_norm == "quick" else 120.0),
        )
        desc_ttl = _f("workday_description_ttl_s", 7 * 24 * 3600)
        company_concurrency = int(sources.get("company_concurrency") or (6 if mode_norm == "quick" else 4))
        company_concurrency = max(1, min(company_concurrency, 8))
        workday_company_concurrency = int(
            sources.get("workday_company_concurrency") or (2 if mode_norm == "quick" else 3)
        )
        workday_company_concurrency = max(1, min(workday_company_concurrency, 3))

        from jobseek.http_client import workday_http_client

        adapter_instances: dict[str, Any] = {}
        workday_template: Any | None = None
        for name, cls in ADAPTERS.items():
            if not sources.get(name, name != "gem"):
                continue
            if name == "workday":
                # List-only: fetch_details=False. Enrich pipeline hydrates details.
                # SQLite description_cache still restores complete bodies on upsert.
                workday_template = cls(
                    client,
                    fetch_details=False,
                    list_budget_s=None if workday_complete else list_budget,
                    detail_budget_s=None,
                    company_budget_s=None,
                    description_ttl_s=desc_ttl,
                    force_refresh=False,
                    complete=workday_complete,
                )
                adapter_instances[name] = workday_template
            else:
                adapter_instances[name] = cls(client)

        fetchable = [
            c
            for c in companies
            if (c.get("ats") or "").lower() in adapter_instances
        ]
        total_boards = len(fetchable)
        discover_t0 = time.monotonic()
        summary["mode"] = mode_norm
        summary["timing"] = {}
        summary["http"] = {
            "workday_details_cached": 0,
            "workday_details_fetched": 0,
            "workday_details_requested": 0,
            "workday_geo_reuse": 0,
            "requests": 0,
        }
        summary["incomplete_boards"] = []
        logger.info(
            "discover fetch start mode=%s boards=%s concurrency=%s "
            "list_only=True list_budget_s=%s (details via enrich)",
            mode_norm,
            total_boards,
            company_concurrency,
            "complete" if workday_complete else list_budget,
        )
        summary["pipeline"] = "list_only"
        summary["enrich_hint"] = "githired enrich"

        progress_lock = threading.Lock()
        boards_done = 0

        def _process_company(company: dict[str, Any]) -> dict[str, Any]:
            """Fetch one company board. Safe for worker threads (DB writes locked)."""
            ats = (company.get("ats") or "").lower()
            company_name = str(company.get("name") or "")
            company_t0 = time.monotonic()
            local: dict[str, Any] = {
                "company": company_name,
                "ats": ats,
                "ok": False,
                "listing_complete": False,
                "jobs_new": 0,
                "jobs_updated": 0,
                "job_ids": [],
                "errors": [],
                "warnings": [],
                "details_cached": 0,
                "details_fetched": 0,
                "details_requested": 0,
                "elapsed_s": 0.0,
                "list_s": 0.0,
                "detail_s": 0.0,
            }
            adapter = adapter_instances.get(ats)
            if not adapter and ats != "workday":
                local["warnings"].append(
                    f"{company_name}: ats={ats} has no fetch adapter"
                )
                local["elapsed_s"] = round(time.monotonic() - company_t0, 2)
                return local
            try:
                if ats == "workday":
                    if workday_template is None:
                        local["warnings"].append(
                            f"{company_name}: workday adapter not enabled"
                        )
                        local["elapsed_s"] = round(time.monotonic() - company_t0, 2)
                        return local
                    # Isolated adapter + cache + HTTP client per company.
                    cache = db.workday_description_cache(company=company_name)
                    wd_client = workday_http_client()
                    with progress_lock:
                        workday_clients.append(wd_client)
                    adapter = workday_template.clone(
                        client=wd_client, description_cache=cache
                    )
                    result: AdapterResult = adapter.fetch_company(
                        company, description_cache=cache
                    )
                else:
                    result = adapter.fetch_company(company)
            except Exception as exc:  # noqa: BLE001
                local["errors"].append(str(exc))
                local["warnings"].append(f"{ats} {company_name}: unhandled {exc}")
                local["elapsed_s"] = round(time.monotonic() - company_t0, 2)
                db.mark_company_fetch(
                    company_name,
                    ok=False,
                    ats=ats,
                    board_token=company.get("board_token") or company.get("site_slug"),
                    error=str(exc),
                )
                return local

            timing = getattr(result, "timing", None) or {}
            local["list_s"] = round(float(timing.get("list_s") or 0.0), 2)
            local["detail_s"] = round(float(timing.get("detail_s") or 0.0), 2)
            local["elapsed_s"] = round(
                float(timing.get("total_s") or (time.monotonic() - company_t0)), 2
            )
            local["listing_complete"] = bool(getattr(result, "listing_complete", True))
            local["details_cached"] = int(getattr(result, "details_cached", 0) or 0)
            local["details_fetched"] = int(getattr(result, "details_fetched", 0) or 0)
            local["details_requested"] = int(getattr(result, "details_requested", 0) or 0)
            if result.raw_status is not None:
                db.store_raw(
                    source=ats,
                    request_key=result.request_key,
                    status_code=result.raw_status,
                    body=json.dumps(
                        [j.to_dict() for j in result.jobs], ensure_ascii=False
                    )[:500000],
                )

            soft_ok = result.raw_status == 200 and bool(result.jobs)
            hard_ok = result.raw_status == 200 and not result.errors
            if hard_ok or soft_ok:
                local["ok"] = True
                db.mark_company_fetch(
                    company_name,
                    ok=True,
                    ats=ats,
                    board_token=company.get("board_token") or company.get("site_slug"),
                    empty=not result.jobs,
                )
                if not result.jobs:
                    local["warnings"].append(
                        f"{company_name}: board OK but returned 0 jobs (empty board)"
                    )
                if result.errors:
                    local["warnings"].extend(result.errors)
            else:
                detail = "; ".join(result.errors) or f"HTTP {result.raw_status}"
                local["errors"].append(detail)
                local["warnings"].append(f"{ats} {company_name}: {detail}")
                db.mark_company_fetch(
                    company_name,
                    ok=False,
                    ats=ats,
                    board_token=company.get("board_token") or company.get("site_slug"),
                    error=detail,
                )

            for job in result.jobs:
                job_id, is_new = db.upsert_job(job)
                local["job_ids"].append(job_id)
                if is_new:
                    local["jobs_new"] += 1
                else:
                    local["jobs_updated"] += 1
            return local

        # Prefer finishing fast ATS boards first so jobs land early (progressive).
        non_wd = [c for c in fetchable if (c.get("ats") or "").lower() != "workday"]
        wd_only = [c for c in fetchable if (c.get("ats") or "").lower() == "workday"]

        def _run_pool(batch: list[dict[str, Any]], workers: int) -> None:
            nonlocal boards_attempted, boards_ok, boards_done
            if not batch:
                return
            with ThreadPoolExecutor(max_workers=max(1, min(workers, len(batch)))) as pool:
                futures = {pool.submit(_process_company, c): c for c in batch}
                for fut in as_completed(futures):
                    local = fut.result()
                    with progress_lock:
                        boards_attempted += 1
                        boards_done += 1
                        ats = local["ats"]
                        company_name = local["company"]
                        summary["fetched"] += local["jobs_new"] + local["jobs_updated"]
                        summary["new"] += local["jobs_new"]
                        summary["updated"] += local["jobs_updated"]
                        summary["http"]["workday_details_cached"] += local["details_cached"]
                        summary["http"]["workday_details_fetched"] += local["details_fetched"]
                        summary["http"]["workday_details_requested"] += local[
                            "details_requested"
                        ]
                        summary["by_company"].append(
                            {
                                "company": company_name,
                                "ats": ats,
                                "ok": local["ok"],
                                "elapsed_s": local.get("elapsed_s"),
                                "list_s": local.get("list_s"),
                                "detail_s": local.get("detail_s"),
                                "new": local["jobs_new"],
                                "updated": local["jobs_updated"],
                                "details_cached": local["details_cached"],
                                "details_fetched": local["details_fetched"],
                                "details_requested": local["details_requested"],
                            }
                        )
                        ats_bucket = summary["by_ats"].setdefault(
                            ats,
                            {
                                "boards": 0,
                                "ok": 0,
                                "elapsed_s": 0.0,
                                "jobs": 0,
                                "details_cached": 0,
                                "details_fetched": 0,
                            },
                        )
                        ats_bucket["boards"] += 1
                        if local["ok"]:
                            ats_bucket["ok"] += 1
                        ats_bucket["elapsed_s"] = round(
                            ats_bucket["elapsed_s"] + float(local.get("elapsed_s") or 0),
                            2,
                        )
                        ats_bucket["jobs"] += local["jobs_new"] + local["jobs_updated"]
                        ats_bucket["details_cached"] += local["details_cached"]
                        ats_bucket["details_fetched"] += local["details_fetched"]
                        for w in local["warnings"]:
                            summary["warnings"].append(w)
                        if local["ok"]:
                            boards_ok += 1
                            summary["boards_ok"].append(company_name)
                            # Only mark removals when listing pagination completed.
                            if local["listing_complete"] and ats in fetched_companies:
                                fetched_companies[ats].add(company_name)
                            elif not local["listing_complete"]:
                                summary["incomplete_boards"].append(company_name)
                            if ats in seen_by_source:
                                seen_by_source[ats].update(local["job_ids"])
                        else:
                            failure = {
                                "company": company_name,
                                "ats": ats,
                                "detail": "; ".join(local["errors"]) or "failed",
                            }
                            summary["board_failures"].append(failure)
                            db.add_run_event(
                                run_id, "warning", failure["detail"], failure
                            )
                        logger.info(
                            "discover board %s/%s company=%s ats=%s ok=%s "
                            "new=%s updated=%s cached=%s fetched=%s "
                            "list_s=%.1f detail_s=%.1f wall_s=%.1f",
                            boards_done,
                            total_boards,
                            company_name,
                            ats,
                            local["ok"],
                            local["jobs_new"],
                            local["jobs_updated"],
                            local["details_cached"],
                            local["details_fetched"],
                            float(local.get("list_s") or 0),
                            float(local.get("detail_s") or 0),
                            float(local.get("elapsed_s") or 0),
                        )

        # Overlap non-Workday and Workday pools for wall-clock (each keeps its
        # own concurrency cap and Workday uses isolated HTTP clients).
        nw_t0 = time.monotonic()
        wd_t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as meta:
            nw_fut = meta.submit(_run_pool, non_wd, company_concurrency)
            wd_fut = meta.submit(_run_pool, wd_only, workday_company_concurrency)
            nw_fut.result()
            summary["timing"]["non_workday_s"] = round(time.monotonic() - nw_t0, 1)
            wd_fut.result()
            summary["timing"]["workday_s"] = round(time.monotonic() - wd_t0, 1)

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
        summary["timing"]["total_s"] = round(time.monotonic() - discover_t0, 1)
        summary["http"]["requests"] = int(getattr(client, "request_count", 0) or 0) + sum(
            int(getattr(c, "request_count", 0) or 0) for c in workday_clients
        )
        cached = int(summary["http"].get("workday_details_cached") or 0)
        fetched = int(summary["http"].get("workday_details_fetched") or 0)
        considered = cached + fetched
        summary["http"]["workday_cache_hit_rate"] = (
            round(cached / considered, 3) if considered else None
        )
        # Partial board failures are warnings. Fatal only when every attempted
        # board failed AND nothing was fetched (empty successful search is OK).
        all_boards_failed = boards_attempted > 0 and boards_ok == 0
        if all_boards_failed and summary["fetched"] == 0:
            summary["errors"].append(
                "all enabled ATS boards failed and no jobs were fetched"
            )
        if summary.get("incomplete_boards"):
            summary["warnings"].append(
                f"{len(summary['incomplete_boards'])} board(s) had incomplete listing "
                "pagination — missing jobs were NOT marked removed"
            )
        ok = len(summary["errors"]) == 0
        summary["ok"] = ok
        # Compact by_company for run summary persistence (keep slowest Workday boards).
        by_co = summary.get("by_company") or []
        if len(by_co) > 40:
            ranked = sorted(
                by_co, key=lambda r: float(r.get("elapsed_s") or 0), reverse=True
            )
            summary["by_company_slowest"] = ranked[:15]
            summary["by_company"] = [
                r for r in by_co if (r.get("ats") or "") != "workday"
            ] + [r for r in ranked if (r.get("ats") or "") == "workday"][:20]
        db.finish_run(run_id, ok=ok, summary=summary)
        log_extra(
            logger,
            20,
            "discover_complete",
            mode=summary.get("mode"),
            total_s=summary["timing"].get("total_s"),
            non_workday_s=summary["timing"].get("non_workday_s"),
            workday_s=summary["timing"].get("workday_s"),
            boards_ok=boards_ok,
            boards_attempted=boards_attempted,
            new=summary.get("new"),
            updated=summary.get("updated"),
            removed=summary.get("removed_marked"),
            workday_cached=cached,
            workday_fetched=fetched,
            cache_hit_rate=summary["http"].get("workday_cache_hit_rate"),
            http_requests=summary["http"].get("requests"),
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        db.add_run_event(run_id, "error", str(exc), {})
        db.finish_run(run_id, ok=False, summary={**summary, "fatal": str(exc)})
        raise
    finally:
        client.close()
        for wd_c in workday_clients:
            try:
                wd_c.close()
            except Exception:  # noqa: BLE001
                pass
