"""Independent enrichment pipeline — hydrate details after list-only discovery.

Discover persists listing metadata quickly. Enrich fetches full descriptions,
resolved geography, and related fields with bounded concurrency, leases, and
cache reuse. Never invents Canadian eligibility.
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable
from urllib.parse import urlparse

from jobseek.adapters.workday import (
    WorkdayAdapter,
    _job_path_id,
    normalize_workday_job,
    parse_workday_board,
)
from jobseek.companies.registry import load_local_overrides, load_merged_companies
from jobseek.config_loader import Settings, load_companies, load_search
from jobseek.db.store import Database
from jobseek.http_client import workday_http_client
from jobseek.logging_util import log_extra, setup_logging
from jobseek.models import RawJob

log = logging.getLogger("jobseek.enrich")


def _path_id_from_job(job: dict[str, Any]) -> str | None:
    for key in ("url", "apply_url"):
        raw = str(job.get(key) or "")
        if not raw:
            continue
        path = urlparse(raw).path or raw
        # Workday paths: /site/.../job/Role_R123 or /job/City/Role_R123
        segment = path.rstrip("/").split("/")[-1].split("?")[0]
        if segment:
            return segment
    ats_id = job.get("ats_job_id")
    return str(ats_id) if ats_id else None


def _company_lookup(merged: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for c in merged:
        name = str(c.get("name") or "").strip()
        if name:
            out[name.casefold()] = c
    return out


def prioritize_enrichment(
    db: Database,
    *,
    search: dict[str, Any],
    profile: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Score the full pending enrichment queue from listing metadata.

    Considers every pending/stale/failed Workday row (not a recent subset).
    Recalculates when the search/profile fingerprint changes.
    """
    from jobseek.config_loader import load_profile
    from jobseek.enrich_priority import (
        compute_enrich_priority,
        priority_fingerprint,
    )

    profile = profile if profile is not None else load_profile()
    fp = priority_fingerprint(search, profile)
    if not force:
        sample = db._conn.execute(
            """
            SELECT enrich_priority_fp FROM jobs
            WHERE removed_at IS NULL
              AND enrichment_status IN ('pending', 'stale', 'failed')
              AND LOWER(COALESCE(ats_provider, '')) = 'workday'
            LIMIT 1
            """
        ).fetchone()
        # If queue empty or already stamped with this fingerprint, skip full scan
        # only when every pending row matches — check mismatch cheaply.
        mismatch = db._conn.execute(
            """
            SELECT COUNT(*) AS n FROM jobs
            WHERE removed_at IS NULL
              AND enrichment_status IN ('pending', 'stale', 'failed')
              AND LOWER(COALESCE(ats_provider, '')) = 'workday'
              AND (enrich_priority_fp IS NULL OR enrich_priority_fp != ?)
            """,
            (fp,),
        ).fetchone()
        if mismatch and int(mismatch["n"] or 0) == 0:
            total = db._conn.execute(
                """
                SELECT COUNT(*) AS n FROM jobs
                WHERE removed_at IS NULL
                  AND enrichment_status IN ('pending', 'stale', 'failed')
                  AND LOWER(COALESCE(ats_provider, '')) = 'workday'
                """
            ).fetchone()
            return {
                "updated": 0,
                "skipped": "fingerprint_unchanged",
                "fingerprint": fp,
                "pending": int(total["n"] if total else 0),
            }

    rows = db._conn.execute(
        """
        SELECT id, company, title, location_raw, salary_raw, salary_min, salary_max,
               posted_date, first_seen, last_seen, enrich_priority
        FROM jobs
        WHERE removed_at IS NULL
          AND enrichment_status IN ('pending', 'stale', 'failed')
          AND LOWER(COALESCE(ats_provider, '')) = 'workday'
        """
    ).fetchall()
    updates: list[tuple[int, int]] = []
    track_hits = 0
    for row in rows:
        job = dict(row)
        pri = compute_enrich_priority(job, search, profile)
        if pri >= 500:
            track_hits += 1
        updates.append((int(job["id"]), pri))
    written = db.set_enrich_priorities(updates, fingerprint=fp)
    return {
        "updated": written,
        "fingerprint": fp,
        "pending": len(updates),
        "track_relevant": track_hits,
    }


def _enrich_workday_job(
    adapter: WorkdayAdapter,
    company: dict[str, Any],
    job_row: dict[str, Any],
) -> tuple[RawJob | None, str | None]:
    parsed = parse_workday_board(company)
    if not parsed:
        return None, "missing workday board config"
    host, tenant, site = parsed
    path_id = _path_id_from_job(job_row)
    if not path_id:
        return None, "missing job path id"
    detail, err = adapter._fetch_detail(host, tenant, site, path_id)
    if err or not detail:
        return None, err or "empty detail"
    external_path = f"/job/{path_id}"
    for key in ("url", "apply_url"):
        raw = str(job_row.get(key) or "")
        if "/job/" not in raw.casefold():
            continue
        try:
            path = urlparse(raw).path
            if "/job/" in path:
                external_path = "/job/" + path.split("/job/", 1)[1]
                break
        except Exception:  # noqa: BLE001
            pass
    listing = {
        "title": job_row.get("title"),
        "externalPath": external_path,
        "locationsText": job_row.get("location_raw") or "",
        "bulletFields": [job_row.get("ats_job_id")] if job_row.get("ats_job_id") else [],
    }
    company_name = str(company.get("name") or job_row.get("company") or site)
    normalized = normalize_workday_job(
        company_name=company_name,
        host=host,
        site=site,
        listing=listing,
        detail=detail,
    )
    if normalized is not None and normalized.description_complete:
        return normalized, None
    # Fallback: attach detail body onto the already-persisted listing URL.
    info = detail.get("jobPostingInfo") if isinstance(detail, dict) else None
    if not isinstance(info, dict):
        return None, "normalize failed"
    desc = info.get("jobDescription")
    if not isinstance(desc, str) or not desc.strip():
        return None, "detail missing description"
    from datetime import datetime, timezone

    from jobseek.adapters.workday import _combine_locations

    loc = _combine_locations(
        info.get("location"),
        info.get("additionalLocations")
        if isinstance(info.get("additionalLocations"), list)
        else None,
        info.get("remoteType"),
        list_locations_text=job_row.get("location_raw"),
    )
    url = str(job_row.get("url") or job_row.get("apply_url") or "")
    if not url:
        return None, "missing job url"
    return (
        RawJob(
            company=company_name,
            title=str(info.get("title") or job_row.get("title") or "").strip()
            or str(job_row.get("title") or "Untitled"),
            url=url,
            apply_url=str(job_row.get("apply_url") or url),
            source="workday",
            ats_provider="workday",
            ats_job_id=str(
                info.get("jobReqId") or info.get("id") or job_row.get("ats_job_id") or path_id
            ),
            location_raw=loc or job_row.get("location_raw"),
            description=desc.strip(),
            posted_date=job_row.get("posted_date"),
            raw_payload={"listing": listing, "detail": detail},
            description_complete=True,
            description_fetched_at=datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        ),
        None,
    )


def run_enrich(
    db: Database,
    *,
    settings: Settings | None = None,
    mode: str = "standard",
    limit: int | None = None,
    workers: int | None = None,
    time_budget_s: float | None = None,
    force_refresh: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Enrich queued jobs (primarily Workday detail hydration).

    Modes:
      - quick: smaller batch, shorter budget, TTL-aware stale refresh
      - standard: default daily enrichment
      - deep: mark TTL-stale + force refresh incomplete aggressively
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

    def _f(key: str, default: float) -> float:
        raw = sources.get(key, default)
        try:
            return float(raw) if raw is not None else float(default)
        except (TypeError, ValueError):
            return float(default)

    desc_ttl = _f("workday_description_ttl_s", 7 * 24 * 3600)
    batch_limit = int(
        limit
        if limit is not None
        else sources.get(
            "enrich_batch_size",
            80 if mode_norm == "quick" else (400 if mode_norm == "deep" else 200),
        )
    )
    batch_limit = max(1, min(batch_limit, 2000))
    worker_n = int(
        workers
        if workers is not None
        else sources.get("enrich_concurrency", 4 if mode_norm != "quick" else 3)
    )
    worker_n = max(1, min(worker_n, 8))
    budget = time_budget_s
    if budget is None:
        budget = _f(
            "enrich_budget_s",
            90.0 if mode_norm == "quick" else (600.0 if mode_norm == "deep" else 300.0),
        )
    if force_refresh or mode_norm == "deep":
        stale_n = db.mark_enrichment_stale(ttl_s=0 if force_refresh else desc_ttl)
    else:
        stale_n = db.mark_enrichment_stale(ttl_s=desc_ttl)

    from jobseek.config_loader import load_profile

    profile = load_profile()
    prioritized = prioritize_enrichment(db, search=search, profile=profile)
    max_per_company = int(sources.get("enrich_max_per_company") or max(5, batch_limit // 6))
    max_per_company = max(2, min(max_per_company, batch_limit))
    run_id = db.start_run("enrich")
    worker_id = f"enrich-{uuid.uuid4().hex[:10]}"
    t0 = time.monotonic()
    summary: dict[str, Any] = {
        "mode": mode_norm,
        "ok": True,
        "claimed": 0,
        "enriched": 0,
        "failed": 0,
        "skipped": 0,
        "stale_marked": stale_n,
        "prioritized": prioritized,
        "http_requests": 0,
        "cache_reused": 0,
        "errors": [],
        "warnings": [],
        "by_company": {},
        "companies_in_batch": [],
        "queue_before": db.count_enrichment_by_status(),
        "timing": {},
        "max_per_company": max_per_company,
    }

    yaml_companies = load_companies()
    merged = load_merged_companies(
        builtin=yaml_companies,
        db_rows=db.list_companies(),
        overrides=load_local_overrides(),
    )
    by_name = _company_lookup(merged)

    claimed = db.claim_enrichment_jobs(
        limit=batch_limit,
        worker_id=worker_id,
        lease_s=max(90.0, float(budget) / max(worker_n, 1) + 60.0),
        max_per_company=max_per_company,
    )
    summary["claimed"] = len(claimed)
    summary["companies_in_batch"] = sorted(
        {str(r.get("company") or "") for r in claimed if r.get("company")}
    )
    from jobseek.filters.tracks import title_matches_selected_tracks

    claimed_track = sum(
        1
        for r in claimed
        if title_matches_selected_tracks(str(r.get("title") or ""), search)
    )
    summary["claimed_track_relevant"] = claimed_track
    summary["claimed_irrelevant"] = max(0, len(claimed) - claimed_track)
    if progress:
        progress(
            f"enrich: claimed {len(claimed)} job(s) across "
            f"{len(summary['companies_in_batch'])} employer(s) (mode={mode_norm}); "
            f"batch_track={claimed_track} batch_off_track={summary['claimed_irrelevant']}; "
            f"queue_track≈{prioritized.get('track_relevant')}"
        )

    if not claimed:
        summary["timing"]["total_s"] = round(time.monotonic() - t0, 2)
        summary["queue_after"] = db.count_enrichment_by_status()
        db.finish_run(run_id, ok=True, summary=summary)
        return summary

    # Group by company for shared HTTP clients (isolated per company).
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in claimed:
        groups.setdefault(str(row.get("company") or ""), []).append(row)

    clients: list[Any] = []

    clients_lock = __import__("threading").Lock()

    def _process_group(company_name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        local: dict[str, Any] = {
            "enriched": 0,
            "failed": 0,
            "http": 0,
            "cache": 0,
            "warnings": [],
        }
        def _done(row: dict[str, Any], *, ok: bool, error: str | None = None) -> bool:
            return db.complete_enrichment(
                int(row["id"]),
                ok=ok,
                error=error,
                worker_id=worker_id,
                lease_token=str(row.get("enrich_lease_token") or "") or None,
            )

        company = by_name.get(company_name.casefold())
        if not company:
            for row in rows:
                if _done(row, ok=False, error=f"company config missing: {company_name}"):
                    local["failed"] += 1
            return local
        if (company.get("ats") or "").lower() != "workday":
            for row in rows:
                if row.get("description_complete"):
                    if _done(row, ok=True):
                        local["enriched"] += 1
                else:
                    if _done(row, ok=False, error="enrichment not supported for ATS"):
                        local["failed"] += 1
            return local

        client = workday_http_client()
        with clients_lock:
            clients.append(client)
        adapter = WorkdayAdapter(
            client,
            fetch_details=True,
            description_ttl_s=desc_ttl,
            force_refresh=force_refresh or mode_norm == "deep",
            list_budget_s=30,
            detail_budget_s=None,
        )
        for row in rows:
            if budget is not None and (time.monotonic() - t0) >= budget:
                if db.complete_enrichment(
                    int(row["id"]),
                    ok=False,
                    error="enrichment time budget reached",
                    worker_id=worker_id,
                    lease_token=str(row.get("enrich_lease_token") or "") or None,
                    retry_backoff_s=15.0,
                ):
                    local["failed"] += 1
                continue
            token = str(row.get("enrich_lease_token") or "")
            if token:
                db.renew_enrichment_lease(
                    int(row["id"]),
                    worker_id=worker_id,
                    lease_token=token,
                    lease_s=120.0,
                )
            if (
                row.get("description_complete")
                and row.get("enrichment_status") != "stale"
                and not (force_refresh or mode_norm == "deep")
            ):
                if _done(row, ok=True):
                    local["enriched"] += 1
                    local["cache"] += 1
                continue
            try:
                enriched, err = _enrich_workday_job(adapter, company, row)
                local["http"] += 1
                if enriched is None:
                    if row.get("description_complete"):
                        if _done(row, ok=True):
                            local["enriched"] += 1
                            local["warnings"].append(
                                f"{company_name}#{row['id']}: refresh failed ({err}); kept prior"
                            )
                    else:
                        if _done(row, ok=False, error=err):
                            local["failed"] += 1
                    continue
                db.upsert_job(enriched)
                if _done(row, ok=True):
                    local["enriched"] += 1
            except Exception as exc:  # noqa: BLE001
                if row.get("description_complete"):
                    if _done(row, ok=True):
                        local["enriched"] += 1
                        local["warnings"].append(
                            f"{company_name}#{row['id']}: {exc}; kept prior description"
                        )
                else:
                    if _done(row, ok=False, error=str(exc)):
                        local["failed"] += 1
        return local

    try:
        with ThreadPoolExecutor(max_workers=min(worker_n, max(len(groups), 1))) as pool:
            futs = {
                pool.submit(_process_group, name, rows): name
                for name, rows in groups.items()
            }
            for fut in as_completed(futs):
                name = futs[fut]
                try:
                    local = fut.result()
                except Exception as exc:  # noqa: BLE001
                    summary["errors"].append(f"{name}: {exc}")
                    summary["ok"] = False
                    continue
                summary["enriched"] += local["enriched"]
                summary["failed"] += local["failed"]
                summary["http_requests"] += local["http"]
                summary["cache_reused"] += local["cache"]
                summary["warnings"].extend(local.get("warnings") or [])
                summary["by_company"][name] = {
                    k: local[k] for k in ("enriched", "failed", "http", "cache")
                }
                if progress:
                    progress(
                        f"enrich: {name} +{local['enriched']} ok "
                        f"{local['failed']} fail (total {summary['enriched']})"
                    )
    finally:
        for c in clients:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass

    summary["timing"]["total_s"] = round(time.monotonic() - t0, 2)
    summary["queue_after"] = db.count_enrichment_by_status()
    hit = summary["cache_reused"]
    req = summary["http_requests"]
    summary["cache_hit_rate"] = (
        round(hit / (hit + req), 3) if (hit + req) else None
    )
    if summary["errors"]:
        summary["ok"] = False
    db.finish_run(run_id, ok=summary["ok"], summary=summary)
    log_extra(
        logger,
        20,
        "enrich_complete",
        mode=mode_norm,
        enriched=summary["enriched"],
        failed=summary["failed"],
        claimed=summary["claimed"],
        total_s=summary["timing"]["total_s"],
        http_requests=summary["http_requests"],
    )
    return summary
