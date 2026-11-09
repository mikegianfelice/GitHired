#!/usr/bin/env python3
"""Export the GitHired API/MCP dataset snapshot.

Usage:
  python3 scripts/export_api_snapshot.py [--db PATH] [--out PATH] [--limit N]

Writes a versioned JSON snapshot used by the Cloudflare Worker (bundled and/or R2).
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
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "api" / "data" / "jobs.snapshot.json",
    )
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--max-age-days", type=int, default=21)
    parser.add_argument(
        "--jobs-json",
        type=Path,
        default=None,
        help="Optional fixture list of raw job dicts (skips DB)",
    )
    args = parser.parse_args(argv)

    from jobseek.api_snapshot import build_api_snapshot, write_api_snapshot

    if args.jobs_json is not None:
        jobs = json.loads(Path(args.jobs_json).read_text(encoding="utf-8"))
        if not isinstance(jobs, list):
            print("jobs-json must be a list", file=sys.stderr)
            return 1
    else:
        from jobseek.config_loader import Settings
        from jobseek.db.store import Database
        from jobseek.public_shortlist.export import load_jobs_from_db

        settings = Settings.from_env()
        db_path = Path(args.db) if args.db else settings.db_path
        db = Database(db_path)
        try:
            jobs = load_jobs_from_db(db)
        finally:
            db.close()

    snapshot = build_api_snapshot(
        jobs,
        limit=int(args.limit),
        max_age_days=int(args.max_age_days),
    )
    meta = write_api_snapshot(snapshot, Path(args.out))
    # Also mirror under site for Pages-hosted openapi consumers who want a static copy.
    mirror = ROOT / "site" / "api-dataset.json"
    # Strip bulky excerpts from the Pages mirror to keep GH Pages lean; Worker uses full file.
    lean = dict(snapshot)
    lean_jobs = []
    for j in snapshot.get("jobs") or []:
        row = dict(j)
        row.pop("description_excerpt", None)
        lean_jobs.append(row)
    lean["jobs"] = lean_jobs
    lean["note"] = (
        "Lean mirror without description excerpts. Full snapshots are served by api.githired.ca."
    )
    write_api_snapshot(lean, mirror)
    print(json.dumps({**meta, "mirror": str(mirror)}, indent=2))
    return 0 if int(snapshot.get("count") or 0) > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
