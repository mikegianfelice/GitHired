#!/usr/bin/env python3
"""Audit discovery→public export exclusions (primary reason, no double-count).

Usage:
  python3 scripts/audit_inventory.py [--db PATH] [--out-json PATH] [--sample N]
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

from jobseek.filters.apply_url import select_actionable_apply_url
from jobseek.filters.hard import apply_hard_filters
from jobseek.public_shortlist.export import (
    DEFAULT_LIMIT,
    DEFAULT_MAX_AGE_DAYS,
    PUBLIC_SEARCH,
    is_job_specific_apply_url,
    is_valid_apply_url,
    select_public_jobs,
)
from jobseek.filters.tracks import match_track
from jobseek.showcase.top_paying import parse_iso_date


def _load_jobs(db_path: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT id, company, title, location_raw, url, apply_url, description,
               description_complete, salary_raw, salary_min, salary_max, salary_currency,
               source, ats_provider, posted_date, first_seen, last_seen, removed_at, status,
               enrichment_status
        FROM jobs
        """
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def primary_exclusion(job: dict[str, Any], *, now: datetime, cutoff: datetime) -> str:
    """Return one primary exclusion bucket (pipeline order mirrors select_public_jobs)."""
    if job.get("removed_at"):
        return "closed_or_removed"
    title = str(job.get("title") or "").strip()
    company = str(job.get("company") or "").strip()
    if not title or not company:
        return "other_missing_identity"

    if not int(job.get("description_complete") or 0):
        return "insufficient_description"

    track = match_track(title, PUBLIC_SEARCH)
    if not track.matched:
        return "nontechnical_or_off_track"

    last_seen = parse_iso_date(job.get("last_seen") or job.get("posted_date"))
    if last_seen is None or last_seen < cutoff:
        return "stale_or_unseen"

    apply_url, verdict = select_actionable_apply_url(
        primary=job.get("apply_url") or job.get("url"),
        fallbacks=[job.get("url")],
    )
    if not apply_url or not verdict.actionable or verdict.kind != "direct":
        return "apply_url_not_direct"
    if not is_valid_apply_url(apply_url) or not is_job_specific_apply_url(apply_url):
        return "apply_url_not_job_specific"

    hard = apply_hard_filters(job, PUBLIC_SEARCH)
    if hard.eligibility == "INELIGIBLE":
        blob = " ".join(hard.reasons).casefold()
        if "excludes canada" in blob or "us-only" in blob or "united states" in blob:
            return "outside_canada"
        if "province" in blob or "city" in blob:
            return "geographic_restrictions"
        return "outside_canada"
    if hard.eligibility == "UNCERTAIN":
        return "canada_eligibility_unknown"
    if hard.eligibility == "IRRELEVANT":
        if hard.relevance == "REVIEW":
            return "seniority_excluded"
        return "nontechnical_or_off_track"
    if hard.verdict != "PASS" or hard.eligibility != "ELIGIBLE":
        if hard.salary_verdict == "FAIL":
            return "salary_related"
        return "other_hard_filter"
    if hard.relevance == "NO_MATCH" or not hard.title_match:
        return "nontechnical_or_off_track"
    return "eligible"


def categorize_reason(reason: str) -> str:
    mapping = {
        "closed_or_removed": "Closed or stale job",
        "stale_or_unseen": "Closed or stale job",
        "insufficient_description": "Insufficient description",
        "nontechnical_or_off_track": "Nontechnical role",
        "seniority_excluded": "Other filtering rules",
        "apply_url_not_direct": "Other filtering rules",
        "apply_url_not_job_specific": "Other filtering rules",
        "outside_canada": "Outside Canada",
        "canada_eligibility_unknown": "Canada eligibility unknown",
        "geographic_restrictions": "Geographic restrictions",
        "salary_related": "Salary-related exclusion",
        "other_hard_filter": "Other filtering rules",
        "other_missing_identity": "Other filtering rules",
        "failed_enrichment": "Failed enrichment",
        "eligible": "Eligible",
        "duplicate": "Duplicate",
    }
    return mapping.get(reason, "Other filtering rules")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "jobseek.db")
    ap.add_argument(
        "--out-json",
        type=Path,
        default=ROOT / "reports" / "inventory_audit.json",
    )
    ap.add_argument("--sample", type=int, default=120)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=DEFAULT_MAX_AGE_DAYS)
    jobs = _load_jobs(args.db)

    raw = len(jobs)
    active = sum(1 for j in jobs if not j.get("removed_at"))
    complete = sum(1 for j in jobs if not j.get("removed_at") and int(j.get("description_complete") or 0))

    primary: Counter[str] = Counter()
    by_ats: dict[str, Counter[str]] = defaultdict(Counter)
    by_company: dict[str, Counter[str]] = defaultdict(Counter)
    eligible_rows: list[dict[str, Any]] = []
    excluded_for_sample: list[dict[str, Any]] = []

    for job in jobs:
        reason = primary_exclusion(job, now=now, cutoff=cutoff)
        primary[reason] += 1
        ats = str(job.get("ats_provider") or job.get("source") or "unknown")
        company = str(job.get("company") or "unknown")
        by_ats[ats][reason] += 1
        by_company[company][reason] += 1
        row = {
            "id": job["id"],
            "company": company,
            "title": job.get("title"),
            "location_raw": job.get("location_raw"),
            "ats": ats,
            "source": job.get("source"),
            "reason": reason,
            "category": categorize_reason(reason),
            "description_complete": bool(int(job.get("description_complete") or 0)),
            "enrichment_status": job.get("enrichment_status"),
        }
        if reason == "eligible":
            eligible_rows.append(row)
        else:
            excluded_for_sample.append(row)

    # Public export path (deduped + capped) — ground truth for published count.
    public = select_public_jobs(
        jobs, limit=DEFAULT_LIMIT, max_age_days=DEFAULT_MAX_AGE_DAYS, now=now
    )

    # Stratified sample of exclusions
    rng = random.Random(args.seed)
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in excluded_for_sample:
        by_cat[row["category"]].append(row)
    sample: list[dict[str, Any]] = []
    cats = sorted(by_cat.keys())
    if cats:
        per = max(1, args.sample // len(cats))
        for cat in cats:
            pool = by_cat[cat]
            rng.shuffle(pool)
            sample.extend(pool[:per])
        rng.shuffle(sample)
        sample = sample[: args.sample]

    # Enrichment failure proxy among active incomplete jobs
    failed_enrich = sum(
        1
        for j in jobs
        if not j.get("removed_at")
        and not int(j.get("description_complete") or 0)
        and str(j.get("enrichment_status") or "").lower()
        in ("failed", "error", "exhausted", "dead")
    )

    report = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "db": str(args.db),
        "inventory": {
            "raw_jobs": raw,
            "active_jobs": active,
            "removed_jobs": raw - active,
            "description_complete_active": complete,
            "pipeline_eligible_pre_dedupe": primary["eligible"],
            "public_export_eligible": len(public),
            "public_export_cap": DEFAULT_LIMIT,
            "failed_enrichment_proxy": failed_enrich,
            "exposure_rate_pct": round(100.0 * len(public) / raw, 2) if raw else 0.0,
            "active_to_public_pct": round(100.0 * len(public) / active, 2) if active else 0.0,
        },
        "primary_exclusion_counts": dict(primary.most_common()),
        "primary_exclusion_categories": dict(
            Counter(categorize_reason(r) for r, n in primary.items() for _ in range(n)).most_common()
        ),
        "by_ats_provider": {
            ats: dict(c.most_common()) for ats, c in sorted(by_ats.items(), key=lambda x: -sum(x[1].values()))
        },
        "top_companies_by_exclusion": [
            {
                "company": company,
                "excluded": sum(v for k, v in c.items() if k != "eligible"),
                "eligible": c.get("eligible", 0),
                "top_reasons": dict(c.most_common(5)),
            }
            for company, c in sorted(
                by_company.items(),
                key=lambda x: -sum(v for k, v in x[1].items() if k != "eligible"),
            )[:40]
        ],
        "notes": [
            "Primary reason uses select_public_jobs gate order (one bucket per job).",
            "Public export additionally dedupes company+title and caps at 400.",
            "PUBLIC_SEARCH salary policy is 'none' — undisclosed pay is not a public exclusion.",
            "Raw inventory includes global ATS scrapes; searchable inventory is Canada-eligible tech with direct apply URLs.",
        ],
        "exclusion_sample": sample,
        "public_track_breakdown": dict(Counter(j.track or "unknown" for j in public).most_common()),
        "public_arrangement_breakdown": dict(
            Counter(j.work_arrangement for j in public).most_common()
        ),
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["inventory"], indent=2))
    print("primary_exclusion_counts:")
    for k, v in primary.most_common():
        print(f"  {k}: {v}")
    print(f"wrote {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
