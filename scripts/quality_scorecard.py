#!/usr/bin/env python3
"""Lightweight GitHired data-quality scorecard (JSON + Markdown).

Intended to run after discover/enrich/export. No personal data.
Usage:
  python3 scripts/quality_scorecard.py [--db PATH] [--out-dir PATH]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]

from jobseek.public_shortlist.export import (
    DEFAULT_LIMIT,
    DEFAULT_MAX_AGE_DAYS,
    select_public_jobs,
)


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


def _http_json(url: str, timeout: float = 12.0) -> tuple[int, Any | None]:
    try:
        req = Request(url, headers={"User-Agent": "GitHired-scorecard/1.0"})
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", errors="replace")
            return int(resp.status), json.loads(body)
    except Exception as exc:  # noqa: BLE001
        return 0, {"error": str(exc)}


def _employer_stats(jobs: list[dict[str, Any]], public_companies: set[str]) -> list[dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    for j in jobs:
        if j.get("removed_at"):
            continue
        name = str(j.get("company") or "unknown")
        slot = by.setdefault(
            name,
            {
                "company": name,
                "discovered": 0,
                "complete": 0,
                "salary_disclosed": 0,
                "in_public": 0,
            },
        )
        slot["discovered"] += 1
        if int(j.get("description_complete") or 0):
            slot["complete"] += 1
        if j.get("salary_max") is not None and str(j.get("salary_currency") or "").upper() in (
            "CAD",
            "USD",
        ):
            slot["salary_disclosed"] += 1
        if name in public_companies:
            # counted once below via public list
            pass
    pub_counts = Counter()
    return by, pub_counts


def build_scorecard(
    *,
    db_path: Path,
    api_snapshot: Path,
    site_jobs: Path,
    check_live: bool,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    jobs = _load_jobs(db_path)
    raw = len(jobs)
    active = [j for j in jobs if not j.get("removed_at")]
    public = select_public_jobs(
        active, limit=DEFAULT_LIMIT, max_age_days=DEFAULT_MAX_AGE_DAYS, now=now
    )
    public_companies = {p.company for p in public}

    complete = sum(1 for j in active if int(j.get("description_complete") or 0))
    salary_disclosed = sum(
        1
        for j in active
        if j.get("salary_max") is not None
        and str(j.get("salary_currency") or "").upper() in ("CAD", "USD")
    )
    unknown_arrangement = sum(
        1
        for p in public
        if p.work_arrangement in ("unspecified", "unknown", "")
    )
    tech_tagged = sum(1 for p in public if p.technologies)
    apply_ok = sum(1 for p in public if p.apply_url)

    employer_rows: list[dict[str, Any]] = []
    by_co: dict[str, dict[str, int]] = {}
    for j in active:
        name = str(j.get("company") or "unknown")
        slot = by_co.setdefault(name, {"discovered": 0, "complete": 0, "salary": 0})
        slot["discovered"] += 1
        if int(j.get("description_complete") or 0):
            slot["complete"] += 1
        if j.get("salary_max") is not None:
            slot["salary"] += 1
    pub_by_co = Counter(p.company for p in public)
    for name, slot in sorted(by_co.items(), key=lambda x: -x[1]["discovered"])[:50]:
        employer_rows.append(
            {
                "company": name,
                "discovered_active": slot["discovered"],
                "description_complete": slot["complete"],
                "salary_disclosed": slot["salary"],
                "eligible_public": pub_by_co.get(name, 0),
                "complete_rate": round(slot["complete"] / slot["discovered"], 3)
                if slot["discovered"]
                else 0,
            }
        )

    api_meta: dict[str, Any] = {}
    if api_snapshot.exists():
        snap = json.loads(api_snapshot.read_text(encoding="utf-8"))
        api_meta = {
            "path": str(api_snapshot),
            "job_count": len(snap.get("jobs") or []),
            "dataset_id": snap.get("dataset_id"),
            "generated_at": snap.get("generated_at"),
        }
    site_meta: dict[str, Any] = {}
    if site_jobs.exists():
        site = json.loads(site_jobs.read_text(encoding="utf-8"))
        site_meta = {
            "path": str(site_jobs),
            "job_count": len(site.get("jobs") or []),
            "generated_at": site.get("generated_at"),
        }

    live: dict[str, Any] = {}
    if check_live:
        code, health = _http_json("https://api.githired.ca/api/v1/health")
        live["rest_health_http"] = code
        live["rest_health"] = health
        code2, mcp = _http_json("https://api.githired.ca/mcp")
        # MCP may require POST; record GET probe only
        live["mcp_get_http"] = code2
        live["mcp_get_body"] = mcp if isinstance(mcp, dict) else {"raw": str(mcp)[:200]}

    warnings: list[str] = []
    if len(public) < 200:
        warnings.append(f"Eligible public jobs low: {len(public)} (<200)")
    if api_meta.get("job_count") and abs(api_meta["job_count"] - len(public)) > 50:
        warnings.append(
            f"API snapshot ({api_meta['job_count']}) diverges from live select_public_jobs ({len(public)})"
        )
    if site_meta.get("job_count") and abs(site_meta["job_count"] - len(public)) > 50:
        warnings.append(
            f"site/jobs.json ({site_meta['job_count']}) diverges from live select_public_jobs ({len(public)})"
        )
    if active and complete / len(active) < 0.5:
        warnings.append(
            f"Description hydration below 50% on active jobs ({complete}/{len(active)})"
        )

    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inventory": {
            "raw_jobs": raw,
            "active_jobs": len(active),
            "removed_jobs": raw - len(active),
            "eligible_public_jobs": len(public),
            "duplicate_company_title_note": "Public export dedupes company+title before cap",
        },
        "quality": {
            "description_hydration_rate_active": round(complete / len(active), 4) if active else 0,
            "salary_disclosure_rate_active": round(salary_disclosed / len(active), 4)
            if active
            else 0,
            "public_skill_tag_rate": round(tech_tagged / len(public), 4) if public else 0,
            "public_unknown_arrangement": unknown_arrangement,
            "public_apply_url_completeness": round(apply_ok / len(public), 4) if public else 0,
            "max_age_days": DEFAULT_MAX_AGE_DAYS,
        },
        "employer_performance_top50_active": employer_rows,
        "datasets": {"api_snapshot": api_meta, "site_jobs": site_meta},
        "live_probes": live,
        "warnings": warnings,
        "public_tracks": dict(Counter(p.track or "unknown" for p in public).most_common()),
        "public_arrangements": dict(Counter(p.work_arrangement for p in public).most_common()),
    }


def to_markdown(report: dict[str, Any]) -> str:
    inv = report["inventory"]
    q = report["quality"]
    lines = [
        f"# GitHired data quality scorecard",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Inventory",
        "",
        f"- Raw jobs: **{inv['raw_jobs']}**",
        f"- Active jobs: **{inv['active_jobs']}**",
        f"- Eligible public jobs: **{inv['eligible_public_jobs']}**",
        f"- Removed: {inv['removed_jobs']}",
        "",
        "## Quality",
        "",
        f"- Description hydration (active): **{q['description_hydration_rate_active']:.1%}**",
        f"- Salary disclosure (active): **{q['salary_disclosure_rate_active']:.1%}**",
        f"- Public jobs with skill tags: **{q['public_skill_tag_rate']:.1%}**",
        f"- Public unknown arrangements: {q['public_unknown_arrangement']}",
        f"- Public apply URL completeness: **{q['public_apply_url_completeness']:.1%}**",
        "",
        "## Datasets",
        "",
        f"- API snapshot: {json.dumps(report['datasets']['api_snapshot'])}",
        f"- Site jobs: {json.dumps(report['datasets']['site_jobs'])}",
        "",
        "## Warnings",
        "",
    ]
    if report["warnings"]:
        lines.extend(f"- {w}" for w in report["warnings"])
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "jobseek.db")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "reports")
    ap.add_argument("--api-snapshot", type=Path, default=ROOT / "api" / "data" / "jobs.snapshot.json")
    ap.add_argument("--site-jobs", type=Path, default=ROOT / "site" / "jobs.json")
    ap.add_argument("--check-live", action="store_true")
    ap.add_argument("--history", action="store_true", help="Also append to reports/history/")
    args = ap.parse_args()

    report = build_scorecard(
        db_path=args.db,
        api_snapshot=args.api_snapshot,
        site_jobs=args.site_jobs,
        check_live=args.check_live,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "quality_scorecard.json"
    md_path = args.out_dir / "quality_scorecard.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    if args.history:
        hist = args.out_dir / "history"
        hist.mkdir(parents=True, exist_ok=True)
        stamp = report["generated_at"].replace(":", "")
        (hist / f"quality_scorecard_{stamp}.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    print(to_markdown(report))
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
