#!/usr/bin/env python3
"""Discover jobs for a named subset of companies (no full registry sweep).

Usage:
  python3 scripts/discover_companies.py --names Lightspeed,AbCellera,Airbyte
"""

from __future__ import annotations

import argparse
from pathlib import Path

from jobseek.config_loader import load_companies
from jobseek.db.store import Database
from jobseek.discover import ADAPTERS
from jobseek.http_client import RateLimitedClient
from jobseek.paths import db_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", required=True, help="Comma-separated company names")
    ap.add_argument("--db", type=Path, default=None)
    args = ap.parse_args()
    wanted = {n.strip().casefold() for n in args.names.split(",") if n.strip()}
    companies = [
        c
        for c in load_companies()
        if str(c.get("name") or "").casefold() in wanted and c.get("enabled", True) is not False
    ]
    if not companies:
        raise SystemExit(f"No enabled companies matched: {sorted(wanted)}")

    db = Database(args.db or db_path())
    client = RateLimitedClient()
    total_new = 0
    total_upd = 0
    errors: list[str] = []
    for company in companies:
        ats = str(company.get("ats") or "").lower()
        cls = ADAPTERS.get(ats)
        if cls is None:
            errors.append(f"{company.get('name')}: no adapter for {ats}")
            continue
        adapter = cls(client)
        result = adapter.fetch_company(company)
        if result.errors:
            errors.extend(f"{company.get('name')}: {e}" for e in result.errors)
        for job in result.jobs:
            _jid, is_new = db.upsert_job(job)
            if is_new:
                total_new += 1
            else:
                total_upd += 1
        print(
            f"{company.get('name')}: fetched={len(result.jobs)} errors={len(result.errors)}"
        )
    db.close()
    print(
        {
            "new": total_new,
            "updated": total_upd,
            "errors": errors[:20],
            "companies": len(companies),
        }
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
