#!/usr/bin/env python3
"""Export a public Canada-eligible engineering shortlist into site/jobs.json.

Usage:
  python scripts/export_public_shortlist.py [--db PATH] [--site-dir PATH] [--limit N]

Does not print or write personal profiles, scores, or credentials.
Exit codes:
  0 — wrote a non-empty snapshot (or intentionally empty first snapshot)
  2 — new snapshot empty while a previous good snapshot was preserved (soft fail)
  1 — hard error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="SQLite path (default: settings)")
    parser.add_argument(
        "--site-dir",
        type=Path,
        default=ROOT / "site",
        help="Static site directory (default: ./site)",
    )
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--max-age-days", type=int, default=21)
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Write an empty snapshot even when a previous file exists",
    )
    parser.add_argument(
        "--jobs-json",
        type=Path,
        default=None,
        help="Optional fixture JSON list of job dicts (skips DB)",
    )
    args = parser.parse_args(argv)

    from jobseek.public_shortlist.export import (
        build_public_snapshot,
        load_jobs_from_db,
        select_public_jobs,
        write_public_site,
    )

    if args.jobs_json is not None:
        jobs = json.loads(Path(args.jobs_json).read_text(encoding="utf-8"))
        if not isinstance(jobs, list):
            print("jobs-json must be a list", file=sys.stderr)
            return 1
    else:
        from jobseek.config_loader import Settings
        from jobseek.db.store import Database

        settings = Settings.from_env()
        db_path = Path(args.db) if args.db else settings.db_path
        db = Database(db_path)
        try:
            jobs = load_jobs_from_db(db)
        finally:
            db.close()

    selected = select_public_jobs(
        jobs,
        limit=int(args.limit),
        max_age_days=int(args.max_age_days),
    )
    snapshot = build_public_snapshot(selected, limit=int(args.limit))
    meta = write_public_site(
        snapshot,
        Path(args.site_dir),
        preserve_on_empty=not bool(args.allow_empty),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "count": meta["count"],
                "written": meta["written"],
                "preserved_previous": meta["preserved_previous"],
                "path": meta["path"],
                "generated_at": snapshot.get("generated_at"),
            },
            indent=2,
        )
    )
    if meta["preserved_previous"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
