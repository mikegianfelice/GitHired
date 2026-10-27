"""jobseek CLI: discover, rank, digest, email-digest, run-daily, prepare, import-*.

Resume drafting and application submission stay behind explicit user approval.
`prepare` only prints a briefing; it never drafts or submits.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jobseek.adapters.linkedin_compliant import import_alert_file
from jobseek.config_loader import Settings, load_dotenv, load_profile, load_search
from jobseek.db.store import Database
from jobseek.digest.build import build_digest, render_digest_markdown
from jobseek.discover import run_discover
from jobseek.email.send import send_digest_email
from jobseek.logging_util import setup_logging
from jobseek.paths import seen_jobs_path, tracker_path
from jobseek.rank.scorer import score_job


def _db(settings: Settings) -> Database:
    return Database(settings.db_path)


def cmd_discover(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    setup_logging(settings.log_level)
    db = _db(settings)
    try:
        if args.import_tracker:
            n = db.import_tracker_csv(tracker_path())
            print(json.dumps({"imported_tracker_rows": n}))
        summary = run_discover(db, settings=settings, detect_unknown=not args.no_detect)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if not summary.get("errors") else 1
    finally:
        db.close()


def cmd_rank(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    setup_logging(settings.log_level)
    db = _db(settings)
    search = load_search()
    profile = load_profile()
    try:
        db.import_tracker_csv(tracker_path())
        jobs = db.jobs_needing_score(limit=args.limit, re_rank=args.re_rank)
        results = []
        for job in jobs:
            if db.should_skip_recommendation(job["company"], job["title"]):
                results.append({"id": job["id"], "skipped": "tracked_application"})
                continue
            scored = score_job(job, search_cfg=search, profile=profile, settings=settings)
            db.save_score(
                job["id"],
                overall=scored.overall,
                scores=scored.scores,
                hard_filter=scored.hard_filter.to_dict() if scored.hard_filter else None,
                strengths=scored.strengths,
                gaps=scored.gaps,
                salary_alignment=scored.salary_alignment,
                rejection_reasons=scored.rejection_reasons,
                evidence=scored.evidence,
                model=scored.model,
                description_hash=job.get("description_hash") or "",
            )
            results.append(
                {
                    "id": job["id"],
                    "company": job["company"],
                    "title": job["title"],
                    "overall": scored.overall,
                    "verdict": scored.hard_filter.verdict if scored.hard_filter else None,
                    "model": scored.model,
                }
            )
        print(json.dumps({"scored": len(results), "results": results}, indent=2, ensure_ascii=False))
        return 0
    finally:
        db.close()


def cmd_digest(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    db = _db(settings)
    try:
        digest = build_digest(db, since=args.since)
        text = render_digest_markdown(digest)
        if args.json:
            print(json.dumps(digest, indent=2, ensure_ascii=False, default=str))
        else:
            print(text)
        if args.save:
            ids = [int(j["id"]) for j in digest.get("jobs") or []]
            db.save_digest(ids, emailed=False)
        return 0
    finally:
        db.close()


def cmd_email_digest(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    db = _db(settings)
    try:
        digest = build_digest(db, since=args.since)
        text = render_digest_markdown(digest)
        result = send_digest_email(text, settings=settings)
        ids = [int(j["id"]) for j in digest.get("jobs") or []]
        db.save_digest(ids, emailed=True)
        print(json.dumps({"digest_count": digest["count"], "email": result}, indent=2))
        return 0
    finally:
        db.close()


def cmd_run_daily(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    setup_logging(settings.log_level)
    db = _db(settings)
    report: dict = {}
    try:
        db.import_tracker_csv(tracker_path())
        report["discover"] = run_discover(db, settings=settings)
        # Rank
        ns = argparse.Namespace(limit=args.limit, re_rank=False)
        # inline rank
        search = load_search()
        profile = load_profile()
        jobs = db.jobs_needing_score(limit=args.limit, re_rank=False)
        ranked = 0
        for job in jobs:
            if db.should_skip_recommendation(job["company"], job["title"]):
                continue
            scored = score_job(job, search_cfg=search, profile=profile, settings=settings)
            db.save_score(
                job["id"],
                overall=scored.overall,
                scores=scored.scores,
                hard_filter=scored.hard_filter.to_dict() if scored.hard_filter else None,
                strengths=scored.strengths,
                gaps=scored.gaps,
                salary_alignment=scored.salary_alignment,
                rejection_reasons=scored.rejection_reasons,
                evidence=scored.evidence,
                model=scored.model,
                description_hash=job.get("description_hash") or "",
            )
            ranked += 1
        report["ranked"] = ranked
        digest = build_digest(db)
        report["digest_count"] = digest["count"]
        text = render_digest_markdown(digest)
        emailed = False
        if args.email:
            try:
                report["email"] = send_digest_email(text, settings=settings)
                emailed = True
            except Exception as exc:  # noqa: BLE001
                report["email_error"] = str(exc)
                # Failure alert path: try to email the error if possible
                try:
                    send_digest_email(
                        f"jobseek run-daily failure alert:\n{exc}\n\nReport:\n{json.dumps(report, default=str)}",
                        subject="jobseek failure alert",
                        settings=settings,
                    )
                except Exception:
                    pass
        ids = [int(j["id"]) for j in digest.get("jobs") or []]
        db.save_digest(ids, emailed=emailed)
        if not args.quiet:
            print(text)
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 0 if not report.get("discover", {}).get("errors") else 1
    finally:
        db.close()


def cmd_prepare(args: argparse.Namespace) -> int:
    """Print briefing only. Never drafts resume/cover letter or submits."""
    load_dotenv()
    settings = Settings.from_env()
    db = _db(settings)
    try:
        job = db.get_job(args.job_id)
        if not job:
            print(f"job {args.job_id} not found", file=sys.stderr)
            return 1
        print(f"# Prepare (approval required before /apply)\n")
        print(f"- Company: {job['company']}")
        print(f"- Title: {job['title']}")
        print(f"- URL: {job['url']}")
        print(f"- Location: {job.get('location_raw')}")
        print(f"- Source: {job.get('source')}")
        print()
        print("Next steps (manual approval):")
        print(f"  1. Review the posting at the URL above")
        print(f"  2. In Cursor/Claude run: /apply {job['url']}")
        print("  3. Confirm drafting when asked; submit the application yourself")
        if args.approve:
            print()
            print(
                "NOTE: --approve only acknowledges you intend to proceed; "
                "no documents were generated and nothing was submitted."
            )
        return 0
    finally:
        db.close()


def cmd_import_alerts(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    db = _db(settings)
    try:
        path = Path(args.path)
        result = import_alert_file(path)
        new = updated = 0
        for job in result.jobs:
            _id, is_new = db.upsert_job(job)
            if is_new:
                new += 1
            else:
                updated += 1
        print(
            json.dumps(
                {"path": str(path), "parsed": len(result.jobs), "new": new, "updated": updated, "errors": result.errors},
                indent=2,
            )
        )
        return 0 if not result.errors else 1
    finally:
        db.close()


def cmd_import_seen(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    db = _db(settings)
    try:
        path = Path(args.path) if args.path else seen_jobs_path()
        n = db.import_seen_jobs_json(path)
        print(json.dumps({"imported": n, "path": str(path)}))
        return 0
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobseek", description="Canada-remote job discovery & ranking")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="Run ATS + compliant LinkedIn discovery")
    d.add_argument("--no-detect", action="store_true", help="Skip ATS auto-detect")
    d.add_argument("--import-tracker", action="store_true", help="Import job_search_tracker.csv first")
    d.set_defaults(func=cmd_discover)

    r = sub.add_parser("rank", help="Hard-filter then LLM-score unscored jobs")
    r.add_argument("--limit", type=int, default=25)
    r.add_argument("--re-rank", action="store_true")
    r.set_defaults(func=cmd_rank)

    g = sub.add_parser("digest", help="Print top-N digest")
    g.add_argument("--since", default=None)
    g.add_argument("--json", action="store_true")
    g.add_argument("--save", action="store_true")
    g.set_defaults(func=cmd_digest)

    e = sub.add_parser("email-digest", help="Email the digest via SMTP or Resend")
    e.add_argument("--since", default=None)
    e.set_defaults(func=cmd_email_digest)

    daily = sub.add_parser("run-daily", help="discover → rank → digest → optional email")
    daily.add_argument("--limit", type=int, default=40)
    daily.add_argument("--email", action="store_true")
    daily.add_argument("--quiet", action="store_true")
    daily.set_defaults(func=cmd_run_daily)

    prep = sub.add_parser("prepare", help="Briefing only; no auto draft/submit")
    prep.add_argument("job_id", type=int)
    prep.add_argument(
        "--approve",
        action="store_true",
        help="Acknowledge intent only; still does not draft or submit",
    )
    prep.set_defaults(func=cmd_prepare)

    ia = sub.add_parser("import-alerts", help="Import LinkedIn saved-alert HTML/JSON")
    ia.add_argument("path")
    ia.set_defaults(func=cmd_import_alerts)

    isp = sub.add_parser("import-seen", help="Migrate job_scraper/seen_jobs.json into SQLite")
    isp.add_argument("--path", default=None)
    isp.set_defaults(func=cmd_import_seen)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
