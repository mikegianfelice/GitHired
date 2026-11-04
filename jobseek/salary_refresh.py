"""Safe salary backfill / coverage diagnostics.

Re-parses cached descriptions and optionally refetches structured ATS pay
without inventing compensation or changing job identity / first_seen.
"""

from __future__ import annotations

import json
from typing import Any

from jobseek.companies.registry import load_local_overrides, load_merged_companies
from jobseek.config_loader import Settings, load_companies, load_search
from jobseek.db.store import Database
from jobseek.filters.salary import enrich_job_salary, extract_salary_from_text, strip_html
from jobseek.http_client import RateLimitedClient


def _is_verified_row(row: dict[str, Any]) -> bool:
    conf = (row.get("salary_confidence") or "").lower()
    if conf == "verified":
        return True
    amin = row.get("salary_min")
    amax = row.get("salary_max")
    cur = (row.get("salary_currency") or "").upper()
    if amin is None and amax is None:
        return False
    if cur not in ("CAD", "USD"):
        return False
    try:
        vals = [float(v) for v in (amin, amax) if v is not None]
    except (TypeError, ValueError):
        return False
    return bool(vals) and all(30_000 <= v <= 800_000 for v in vals)


def salary_coverage_report(db: Database) -> dict[str, Any]:
    """Per-ATS salary coverage for active jobs."""
    rows = db._conn.execute(
        """
        SELECT ats_provider, source, salary_raw,
               salary_min, salary_max, salary_currency, salary_confidence, salary_period
        FROM jobs
        WHERE removed_at IS NULL
        """
    ).fetchall()
    buckets: dict[str, dict[str, int]] = {}
    for r in rows:
        key = (r["ats_provider"] or r["source"] or "unknown").lower()
        b = buckets.setdefault(
            key,
            {"total": 0, "verified": 0, "unverified": 0, "undisclosed": 0},
        )
        b["total"] += 1
        conf = (r["salary_confidence"] or "").lower()
        if conf == "verified" or _is_verified_row(dict(r)):
            b["verified"] += 1
        elif conf == "unverified":
            b["unverified"] += 1
        elif r["salary_min"] is not None and (r["salary_currency"] or "").upper() not in ("CAD", "USD"):
            b["unverified"] += 1
        elif r["salary_raw"] and r["salary_min"] is None:
            b["unverified"] += 1
        else:
            b["undisclosed"] += 1

    out = []
    for ats, b in sorted(buckets.items()):
        total = b["total"] or 1
        out.append(
            {
                "ats": ats,
                "total": b["total"],
                "verified": b["verified"],
                "unverified": b["unverified"],
                "undisclosed": b["undisclosed"],
                "verified_pct": round(100.0 * b["verified"] / total, 1),
            }
        )
    return {
        "providers": out,
        "totals": {
            "total": sum(b["total"] for b in buckets.values()),
            "verified": sum(b["verified"] for b in buckets.values()),
            "unverified": sum(b["unverified"] for b in buckets.values()),
            "undisclosed": sum(b["undisclosed"] for b in buckets.values()),
        },
    }


def _company_board_lookup() -> dict[str, dict[str, Any]]:
    settings = Settings.from_env()
    db = Database(settings.db_path)
    try:
        merged = load_merged_companies(
            db_rows=db.list_companies(),
            yaml_companies=load_companies(),
            local_overrides=load_local_overrides(),
        )
    finally:
        db.close()
    by_name = {str(c.get("name") or "").casefold(): c for c in merged if isinstance(c, dict)}
    return by_name


def _update_salary(
    db: Database,
    job_id: int,
    *,
    salary_raw: str | None,
    salary_min: float | None,
    salary_max: float | None,
    salary_currency: str | None,
    salary_confidence: str | None,
    salary_period: str | None,
    salary_source: str | None,
) -> None:
    """Write salary fields without touching first_seen / identity / discovered flags."""
    db._conn.execute(
        """
        UPDATE jobs SET
            salary_raw = COALESCE(?, salary_raw),
            salary_min = CASE
                WHEN ? IS NOT NULL THEN ?
                ELSE salary_min
            END,
            salary_max = CASE
                WHEN ? IS NOT NULL THEN ?
                ELSE salary_max
            END,
            salary_currency = CASE
                WHEN ? IS NOT NULL AND ? != '' THEN ?
                ELSE salary_currency
            END,
            salary_confidence = COALESCE(?, salary_confidence),
            salary_period = COALESCE(?, salary_period),
            salary_source = COALESCE(?, salary_source)
        WHERE id = ?
        """,
        (
            salary_raw,
            salary_min,
            salary_min,
            salary_max,
            salary_max,
            salary_currency,
            salary_currency or "",
            salary_currency,
            salary_confidence,
            salary_period,
            salary_source,
            job_id,
        ),
    )
    db._conn.commit()


def refresh_salaries(
    db: Database,
    *,
    limit: int = 500,
    refetch_structured: bool = False,
    ats: str | None = None,
) -> dict[str, Any]:
    """Backfill missing/unverified salaries from cached descriptions (+ optional ATS).

    Idempotent: verified annual rows are left untouched. Never writes null over
    existing verified amounts.
    """
    before = salary_coverage_report(db)
    clauses = ["removed_at IS NULL"]
    params: list[Any] = []
    if ats:
        clauses.append("LOWER(COALESCE(ats_provider, source)) = ?")
        params.append(ats.lower())
    # Candidates: missing min OR not verified confidence
    clauses.append(
        "(salary_min IS NULL OR salary_confidence IS NULL OR salary_confidence != 'verified')"
    )
    sql = f"""
        SELECT id, company, title, ats_provider, source, ats_job_id, url,
               description, salary_raw, salary_min, salary_max, salary_currency,
               salary_confidence
        FROM jobs
        WHERE {' AND '.join(clauses)}
        ORDER BY id
        LIMIT ?
    """
    params.append(int(limit))
    rows = db._conn.execute(sql, params).fetchall()

    client = RateLimitedClient(min_interval_s=0.2) if refetch_structured else None
    companies = _company_board_lookup() if refetch_structured else {}
    recovered = 0
    reparsed = 0
    refetched = 0
    skipped_verified = 0
    errors: list[str] = []

    try:
        for row in rows:
            job = dict(row)
            if _is_verified_row(job) and (job.get("salary_confidence") or "").lower() == "verified":
                skipped_verified += 1
                continue

            # 1) Re-parse cached description / salary_raw (no network)
            enriched = enrich_job_salary(job)
            if enriched.get("salary_confidence") == "verified" and enriched.get("salary_min") is not None:
                _update_salary(
                    db,
                    int(job["id"]),
                    salary_raw=enriched.get("salary_raw") or job.get("salary_raw"),
                    salary_min=float(enriched["salary_min"]),
                    salary_max=float(enriched["salary_max"]) if enriched.get("salary_max") is not None else float(enriched["salary_min"]),
                    salary_currency=enriched.get("salary_currency"),
                    salary_confidence="verified",
                    salary_period="annual",
                    salary_source=enriched.get("salary_source") or "employer_description",
                )
                recovered += 1
                reparsed += 1
                continue

            if not refetch_structured or client is None:
                continue

            provider = (job.get("ats_provider") or job.get("source") or "").lower()
            company = companies.get(str(job.get("company") or "").casefold())
            token = (company or {}).get("board_token") or (company or {}).get("site_slug")
            ats_id = job.get("ats_job_id")
            if not token or not ats_id:
                continue
            try:
                sraw = smin = smax = scur = None
                if provider == "workable":
                    from jobseek.adapters.workable import WorkableAdapter

                    sraw, smin, smax, scur = WorkableAdapter(client=client).fetch_job_salary(
                        str(token), str(ats_id)
                    )
                elif provider == "rippling":
                    from jobseek.adapters.rippling import RipplingAdapter

                    sraw, smin, smax, scur = RipplingAdapter(client=client).fetch_job_salary(
                        str(token), str(ats_id)
                    )
                else:
                    continue
                refetched += 1
                if smin is None:
                    continue
                _update_salary(
                    db,
                    int(job["id"]),
                    salary_raw=sraw,
                    salary_min=float(smin),
                    salary_max=float(smax) if smax is not None else float(smin),
                    salary_currency=scur,
                    salary_confidence="verified",
                    salary_period="annual",
                    salary_source="structured_ats",
                )
                recovered += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{job.get('company')}/{ats_id}: {exc}")
    finally:
        if client is not None:
            client.close()

    after = salary_coverage_report(db)
    return {
        "candidates": len(rows),
        "recovered": recovered,
        "reparsed_from_description": reparsed,
        "refetched_structured": refetched,
        "skipped_verified": skipped_verified,
        "errors": errors[:20],
        "coverage_before": before,
        "coverage_after": after,
    }


def coverage_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)
