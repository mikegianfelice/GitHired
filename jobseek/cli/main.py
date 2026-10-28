"""githired / jobseek CLI.

Resume drafting and application submission stay behind explicit user approval.
`prepare` only prints a briefing; it never drafts or submits.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from jobseek.adapters.linkedin_compliant import import_alert_file
from jobseek.config_loader import Settings, load_dotenv, load_profile, load_search, load_companies
from jobseek.db.store import Database
from jobseek.digest.build import build_digest, render_digest_markdown
from jobseek.discover import run_discover
from jobseek.email.send import send_digest_email
from jobseek.filters.tracks import DEFAULT_TRACK_ALIASES
from jobseek.logging_util import setup_logging
from jobseek.paths import ROOT, config_dir, db_path, packaged_defaults_dir, seen_jobs_path, tracker_path
from jobseek.rank.scorer import score_job


def _prog_name() -> str:
    base = Path(sys.argv[0]).name if sys.argv else "githired"
    if "jobseek" in base:
        return "jobseek"
    return "githired"


def _db(settings: Settings) -> Database:
    return Database(settings.db_path)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def cmd_discover(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    setup_logging(settings.log_level)
    db = _db(settings)
    try:
        if args.import_tracker or True:
            # Always refresh applications from tracker when present
            n = db.import_tracker_csv(tracker_path())
            if args.import_tracker:
                print(json.dumps({"imported_tracker_rows": n}))
        summary = run_discover(db, settings=settings, detect_unknown=not args.no_detect)
        _print_json(summary)
        # Board failures are warnings; nonzero only when summary.errors is set
        # (e.g. all boards failed and nothing fetched).
        return 0 if summary.get("ok", not summary.get("errors")) else 1
    finally:
        db.close()


def cmd_rank(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    setup_logging(settings.log_level)
    db = _db(settings)
    search = load_search()
    profile = load_profile()
    from jobseek.profile_util import profile_warnings

    use_llm = bool(args.llm) or settings.rank_llm
    score_kind = "llm" if use_llm else "deterministic"
    try:
        db.import_tracker_csv(tracker_path())
        warn = profile_warnings(profile)
        for w in warn:
            _err(f"warning: {w}")
        jobs = db.jobs_needing_score(
            limit=args.limit, re_rank=args.re_rank, score_kind=score_kind
        )
        results = []
        for job in jobs:
            if db.should_skip_recommendation(job["company"], job["title"]):
                results.append({"id": job["id"], "skipped": "tracked_application"})
                continue
            scored = score_job(
                job,
                search_cfg=search,
                profile=profile,
                settings=settings,
                use_llm=use_llm,
            )
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
                score_kind=scored.score_kind,
            )
            results.append(
                {
                    "id": job["id"],
                    "company": job["company"],
                    "title": job["title"],
                    "overall": scored.overall,
                    "score_kind": scored.score_kind,
                    "verdict": scored.hard_filter.verdict if scored.hard_filter else None,
                    "model": scored.model,
                }
            )
        companies = sorted({r.get("company") for r in results if r.get("company")})
        _print_json(
            {
                "scored": len(results),
                "score_kind": score_kind,
                "profile_warnings": warn,
                "companies_in_batch": companies,
                "results": results,
            }
        )
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
            _print_json(digest)
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
        _print_json({"digest_count": digest["count"], "email": result})
        return 0
    finally:
        db.close()


def cmd_companies(args: argparse.Namespace) -> int:
    """Dispatch nested `githired companies …` subcommands."""
    load_dotenv()
    settings = Settings.from_env()
    setup_logging(settings.log_level)
    action = getattr(args, "companies_command", None)
    db = _db(settings)
    try:
        if action == "discover":
            from jobseek.companies.discover import run_companies_discover

            summary = run_companies_discover(
                db, settings=settings, validate=not args.no_validate
            )
            _print_json(summary)
            return 0 if summary.get("ok", True) else 1

        if action == "validate":
            from jobseek.companies.discover import COMPANY_ADAPTERS
            from jobseek.companies.registry import load_local_overrides, load_merged_companies
            from jobseek.companies.validate import run_validate

            search = load_search()
            cd = search.get("company_discovery") or {}
            companies = load_merged_companies(
                db_rows=db.list_companies(),
                overrides=load_local_overrides(),
            )
            if args.ats:
                companies = [c for c in companies if (c.get("ats") or "").lower() == args.ats.lower()]
            if args.status:
                companies = [
                    c for c in companies if (c.get("validation_status") or "") == args.status
                ]
            summary = run_validate(
                db,
                companies,
                adapters=COMPANY_ADAPTERS,
                force=bool(args.force),
                auto_enable=bool(cd.get("auto_enable_validated", True)),
                transient_cooldown_days=int(cd.get("transient_cooldown_days") or 7),
            )
            _print_json(summary)
            return 0

        if action == "list":
            rows = db.list_companies(
                ats=args.ats,
                status=args.status,
                enabled=None if args.enabled is None else args.enabled == "true",
            )
            if args.json:
                _print_json(rows)
                return 0
            for c in rows:
                en = "on" if c.get("enabled") else "off"
                ex = " EXCLUDED" if c.get("excluded") else ""
                print(
                    f"  [{en}]{ex} {c['name']}: {c.get('ats')}/{c.get('board_token')} "
                    f"status={c.get('validation_status')} "
                    f"source={c.get('discovery_source') or c.get('source')} "
                    f"failures={c.get('failure_count') or 0}"
                )
            print(f"\n{len(rows)} companies")
            return 0

        if action == "stats":
            stats = db.company_stats()
            _print_json(stats)
            return 0

        if action == "export":
            from jobseek.companies.registry import company_to_community_export

            rows = db.list_companies()
            if args.validated:
                rows = [r for r in rows if r.get("validation_status") in ("ok", "empty")]
            doc = {
                "version": 1,
                "companies": [company_to_community_export(r) for r in rows],
            }
            import yaml

            text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
                print(json.dumps({"wrote": args.out, "count": len(doc["companies"])}))
            else:
                print(text)
            return 0

        if action == "import":
            from jobseek.companies.domain_util import canonical_domain
            from jobseek.companies.registry import parse_community_document, validate_community_shape

            path = Path(args.path)
            companies = parse_community_document(path.read_text(encoding="utf-8"))
            errors = validate_community_shape(companies)
            if errors:
                _print_json({"ok": False, "errors": errors})
                return 1
            n = 0
            for company in companies:
                db.upsert_company(
                    name=str(company["name"]),
                    careers_url=company.get("careers_url"),
                    ats=company.get("ats") or "unknown",
                    board_token=company.get("board_token"),
                    validation_status=company.get("validation_status") or "unvalidated",
                    notes=company.get("notes"),
                    enabled=False,
                    source="community",
                    domain=company.get("domain")
                    or canonical_domain(str(company.get("careers_url") or "")),
                    discovery_source="community",
                    last_validated_at=company.get("last_validated_at"),
                )
                n += 1
            _print_json({"ok": True, "imported": n})
            return 0

        _err(f"unknown companies command: {action}")
        return 2
    finally:
        db.close()


def cmd_run_daily(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    setup_logging(settings.log_level)
    db = _db(settings)
    report: dict = {}
    use_llm = bool(getattr(args, "llm", False)) or settings.rank_llm
    try:
        db.import_tracker_csv(tracker_path())
        if getattr(args, "companies", False):
            from jobseek.companies.discover import run_companies_discover

            report["companies"] = run_companies_discover(db, settings=settings)
        report["discover"] = run_discover(db, settings=settings)
        search = load_search()
        profile = load_profile()
        score_kind = "llm" if use_llm else "deterministic"
        jobs = db.jobs_needing_score(limit=args.limit, re_rank=False, score_kind=score_kind)
        ranked = 0
        for job in jobs:
            if db.should_skip_recommendation(job["company"], job["title"]):
                continue
            scored = score_job(
                job, search_cfg=search, profile=profile, settings=settings, use_llm=use_llm
            )
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
                score_kind=scored.score_kind,
            )
            ranked += 1
        report["ranked"] = ranked
        report["score_kind"] = score_kind
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
                try:
                    send_digest_email(
                        f"{_prog_name()} run-daily failure alert:\n{exc}\n\nReport:\n{json.dumps(report, default=str)}",
                        subject=f"{_prog_name()} failure alert",
                        settings=settings,
                    )
                except Exception:
                    pass
        ids = [int(j["id"]) for j in digest.get("jobs") or []]
        db.save_digest(ids, emailed=emailed)
        if not args.quiet:
            print(text)
        _print_json(report)
        return 0 if not report.get("discover", {}).get("errors") else 1
    finally:
        db.close()


def cmd_prepare(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    db = _db(settings)
    try:
        job = db.get_job(args.job_id)
        if not job:
            _err(f"job {args.job_id} not found")
            return 1
        print("# Prepare (approval required before /apply)\n")
        print(f"- Company: {job['company']}")
        print(f"- Title: {job['title']}")
        print(f"- URL: {job['url']}")
        print(f"- Location: {job.get('location_raw')}")
        print(f"- Source: {job.get('source')}")
        print()
        print("Next steps (manual approval):")
        print("  1. Review the posting at the URL above")
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
        _print_json(
            {
                "path": str(path),
                "parsed": len(result.jobs),
                "new": new,
                "updated": updated,
                "errors": result.errors,
            }
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
        _print_json({"imported": n, "path": str(path)})
        return 0
    finally:
        db.close()


def cmd_migrate(args: argparse.Namespace) -> int:
    """Import legacy seen_jobs.json + tracker CSV into SQLite."""
    load_dotenv()
    settings = Settings.from_env()
    db = _db(settings)
    try:
        seen = Path(args.seen) if args.seen else seen_jobs_path()
        tracker = Path(args.tracker) if args.tracker else tracker_path()
        n_seen = db.import_seen_jobs_json(seen)
        n_tracker = db.import_tracker_csv(tracker)
        n_companies = db.seed_companies_from_yaml(load_companies())
        _print_json(
            {
                "imported_seen_jobs": n_seen,
                "imported_tracker_rows": n_tracker,
                "seeded_companies": n_companies,
                "db": str(settings.db_path),
            }
        )
        return 0
    finally:
        db.close()


def cmd_sync_application(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    db = _db(settings)
    try:
        db.sync_application(args.company, args.role, args.status, args.notes or "")
        # Optionally append to tracker CSV for legacy agent compatibility
        if args.write_tracker:
            path = tracker_path()
            header = "date,company,role,status,cv_file,cover_letter_file,source,notes\n"
            if not path.is_file():
                path.write_text(header, encoding="utf-8")
            from datetime import date

            notes = (args.notes or "").replace(",", " ").replace("\n", " ")
            with path.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"{date.today().isoformat()},{args.company},{args.role},{args.status},,,,cli,{notes}\n"
                )
        _print_json(
            {"company": args.company, "role": args.role, "status": args.status, "ok": True}
        )
        return 0
    finally:
        db.close()


def cmd_jobs(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    db = _db(settings)
    try:
        rows = db.list_jobs(
            min_score=args.min_score,
            status=args.status,
            limit=args.limit,
            score_kind=args.score_kind,
        )
        if args.json:
            _print_json({"count": len(rows), "jobs": rows})
            return 0
        if not rows:
            print("No jobs matched.")
            return 0
        for row in rows:
            score = row.get("overall")
            score_s = f"{score:.0f}" if score is not None else "-"
            print(
                f"[{row['id']}] {score_s:>3}  {row['company']} — {row['title']}\n"
                f"       {row.get('location_raw') or '?'} | {row.get('url')}"
            )
        return 0
    finally:
        db.close()


def cmd_sources(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    search = load_search()
    sources = search.get("sources") or {}
    db = _db(settings)
    try:
        companies = db.list_companies()
        if not companies:
            db.seed_companies_from_yaml(load_companies())
            companies = db.list_companies()
        payload = {
            "sources_config": sources,
            "serpapi_configured": bool(settings.serpapi_key),
            "linkedin_mode": "serpapi" if settings.serpapi_key else "free_or_alerts",
            "companies": [
                {
                    "name": c["name"],
                    "ats": c.get("ats"),
                    "board_token": c.get("board_token"),
                    "validation_status": c.get("validation_status"),
                    "last_success_at": c.get("last_success_at"),
                    "enabled": bool(c.get("enabled")),
                    "last_error": c.get("last_error"),
                }
                for c in companies
            ],
        }
        if args.json:
            _print_json(payload)
            return 0
        validated = [c for c in companies if c.get("validation_status") == "ok" and c.get("enabled")]
        invalid = [c for c in companies if c.get("validation_status") == "invalid"]
        inactive = [c for c in companies if not c.get("enabled")]
        unresolved = [
            c
            for c in companies
            if c.get("enabled")
            and c.get("validation_status") not in ("ok", "invalid")
            and (c.get("ats") or "") not in ("greenhouse", "lever", "ashby")
        ]
        print("Discovery sources")
        for k, v in sources.items():
            print(f"  {k}: {'on' if v else 'off'}")
        print(f"  serpapi: {'configured' if settings.serpapi_key else 'not set (free/alerts)'}")
        print(f"\nValidated ({len(validated)}) | Invalid ({len(invalid)}) | "
              f"Unresolved/no-adapter ({len(unresolved)}) | Inactive ({len(inactive)})")
        print(f"\nCompanies ({len(companies)})")
        for c in companies:
            flag = "✓" if c.get("validation_status") == "ok" else c.get("validation_status")
            en = "on" if c.get("enabled") else "off"
            print(
                f"  [{en}] {c['name']}: {c.get('ats')}/{c.get('board_token')} "
                f"status={flag} last_ok={c.get('last_success_at') or '-'}"
            )
        return 0
    finally:
        db.close()


def cmd_doctor(args: argparse.Namespace) -> int:
    load_dotenv()
    settings = Settings.from_env()
    issues: list[str] = []
    info: dict[str, Any] = {
        "python": sys.version.split()[0],
        "prog": _prog_name(),
        "cwd": str(Path.cwd()),
        "repo_root": str(ROOT),
        "config_dir": str(config_dir()),
        "packaged_defaults": str(packaged_defaults_dir()),
        "db_path": str(settings.db_path),
        "db_exists": settings.db_path.is_file(),
        "tracker_exists": tracker_path().is_file(),
        "seen_jobs_exists": seen_jobs_path().is_file(),
        "keys": {
            "ANTHROPIC_API_KEY": bool(settings.anthropic_api_key),
            "OPENAI_API_KEY": bool(settings.openai_api_key),
            "SERPAPI_KEY": bool(settings.serpapi_key),
        },
        "llm_required_for_rank": False,
    }
    try:
        search = load_search()
        info["tracks"] = search.get("tracks")
        info["sources"] = search.get("sources")
    except FileNotFoundError as exc:
        issues.append(str(exc))
    try:
        load_companies()
    except FileNotFoundError as exc:
        issues.append(str(exc))
    if sys.version_info < (3, 10):
        issues.append(f"Python >=3.10 required (found {sys.version.split()[0]})")
    db = _db(settings)
    try:
        companies = db.list_companies()
        info["companies_in_db"] = len(companies)
        info["jobs_in_db"] = db._conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE removed_at IS NULL"
        ).fetchone()["n"]
    finally:
        db.close()
    info["issues"] = issues
    info["ok"] = len(issues) == 0
    if args.json:
        _print_json(info)
    else:
        print(f"{_prog_name()} doctor")
        print(f"  Python: {info['python']}")
        print(f"  Config: {info['config_dir']}")
        print(f"  DB: {info['db_path']} ({'exists' if info['db_exists'] else 'missing — will create on first run'})")
        print(f"  Tracks: {', '.join(info.get('tracks') or []) or '(defaults)'}")
        print("  API keys present (values hidden):")
        for k, v in info["keys"].items():
            print(f"    {k}: {'yes' if v else 'no'}")
        print(f"  Rank LLM required: no (deterministic by default)")
        if issues:
            print("  Issues:")
            for issue in issues:
                print(f"    - {issue}")
        else:
            print("  Status: OK")
    return 1 if issues else 0


def cmd_setup(args: argparse.Namespace) -> int:
    """Interactive initial configuration for Canadian engineering search."""
    load_dotenv()
    cfg_target = Path(args.config_dir) if args.config_dir else (Path.cwd() / "config")
    cfg_target.mkdir(parents=True, exist_ok=True)

    defaults = packaged_defaults_dir()
    for name in ("search.yaml", "companies.yaml", "profile.yaml"):
        dest = cfg_target / name
        if dest.exists() and not args.force:
            continue
        src = None
        if defaults is not None and (defaults / name).is_file():
            src = defaults / name
        elif (ROOT / "config" / name).is_file():
            src = ROOT / "config" / name
        if src is not None:
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    tracks = list(DEFAULT_TRACK_ALIASES.keys())
    selected: list[str] = []
    chosen_modes: list[str] = ["remote_canada"]
    if args.non_interactive:
        selected = list(args.tracks) if args.tracks else [
            "software_engineering",
            "ai_engineering",
            "data_engineering",
            "forward_deployed",
        ]
        chosen_modes = list(args.modes) if args.modes else ["remote_canada"]
    else:
        print("GitHired setup — Canadian engineering job discovery\n")
        print("Select engineering tracks (comma-separated numbers, Enter for defaults):")
        for i, t in enumerate(tracks, 1):
            print(f"  {i}. {t}")
        raw = input("> ").strip()
        if not raw:
            selected = [
                "software_engineering",
                "ai_engineering",
                "data_engineering",
                "forward_deployed",
            ]
        else:
            for part in raw.split(","):
                part = part.strip()
                if part.isdigit() and 1 <= int(part) <= len(tracks):
                    selected.append(tracks[int(part) - 1])
            if not selected:
                selected = tracks[:]

        print("\nLocation modes (comma-separated, Enter for remote_canada):")
        modes = ["remote_canada", "remote_province", "hybrid", "onsite"]
        for i, m in enumerate(modes, 1):
            print(f"  {i}. {m}")
        raw_m = input("> ").strip()
        if raw_m:
            chosen_modes = []
            for part in raw_m.split(","):
                part = part.strip()
                if part.isdigit() and 1 <= int(part) <= len(modes):
                    chosen_modes.append(modes[int(part) - 1])
            if not chosen_modes:
                chosen_modes = ["remote_canada"]

    # Patch search.yaml tracks/modes
    import yaml

    search_path = cfg_target / "search.yaml"
    data = yaml.safe_load(search_path.read_text(encoding="utf-8")) or {}
    data["tracks"] = selected
    loc = data.get("location") or {}
    loc["modes"] = chosen_modes
    data["location"] = loc
    search_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        example = ROOT / ".env.example"
        if example.is_file():
            env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            env_path.write_text(
                "# Optional — discovery and deterministic ranking work without keys\n"
                "# ANTHROPIC_API_KEY=\n"
                "# OPENAI_API_KEY=\n"
                "# SERPAPI_KEY=\n"
                "# GITHIRED_RANK_LLM=0\n",
                encoding="utf-8",
            )

    os.environ.setdefault("JOBSEEK_CONFIG_DIR", str(cfg_target.resolve()))
    settings = Settings.from_env()
    # Prefer local data dir
    if not os.environ.get("JOBSEEK_DB_PATH"):
        local_db = Path.cwd() / "data" / "jobseek.db"
        local_db.parent.mkdir(parents=True, exist_ok=True)
        settings.db_path = local_db

    db = Database(settings.db_path)
    try:
        n_companies = db.seed_companies_from_yaml(load_companies())
        n_seen = db.import_seen_jobs_json(seen_jobs_path())
        n_tracker = db.import_tracker_csv(tracker_path())
    finally:
        db.close()

    result = {
        "config_dir": str(cfg_target.resolve()),
        "tracks": selected,
        "location_modes": chosen_modes,
        "db": str(settings.db_path),
        "seeded_companies": n_companies,
        "imported_seen_jobs": n_seen,
        "imported_tracker_rows": n_tracker,
        "env": str(env_path),
        "next": [
            f"{_prog_name()} discover",
            f"{_prog_name()} rank",
            f"{_prog_name()} jobs",
            f"{_prog_name()} doctor",
        ],
    }
    _print_json(result)
    return 0


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    prog = prog or _prog_name()
    p = argparse.ArgumentParser(
        prog=prog,
        description="Canada-remote engineering job discovery & ranking (local-first)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("setup", help="Interactive initial configuration")
    s.add_argument("--config-dir", default=None)
    s.add_argument("--force", action="store_true", help="Overwrite existing config files")
    s.add_argument("--non-interactive", action="store_true")
    s.add_argument("--tracks", nargs="*", default=None)
    s.add_argument("--modes", nargs="*", default=None)
    s.set_defaults(func=cmd_setup)

    d = sub.add_parser("discover", help="Run ATS + compliant LinkedIn discovery")
    d.add_argument("--no-detect", action="store_true", help="Skip ATS auto-detect")
    d.add_argument("--import-tracker", action="store_true", help="Print tracker import count")
    d.set_defaults(func=cmd_discover)

    r = sub.add_parser("rank", help="Deterministic score (optional --llm)")
    r.add_argument("--limit", type=int, default=25)
    r.add_argument("--re-rank", action="store_true")
    r.add_argument(
        "--llm",
        action="store_true",
        help="Enable optional LLM stage-2 scoring (requires API key)",
    )
    r.set_defaults(func=cmd_rank)

    j = sub.add_parser("jobs", help="List scored shortlist from SQLite")
    j.add_argument("--min-score", type=float, default=None)
    j.add_argument("--status", default=None)
    j.add_argument("--limit", type=int, default=25)
    j.add_argument("--score-kind", default="deterministic", choices=["deterministic", "llm", "hard_filter"])
    j.add_argument("--json", action="store_true")
    j.set_defaults(func=cmd_jobs)

    g = sub.add_parser("digest", help="Print top-N digest")
    g.add_argument("--since", default=None)
    g.add_argument("--json", action="store_true")
    g.add_argument("--save", action="store_true")
    g.set_defaults(func=cmd_digest)

    src = sub.add_parser("sources", help="Company registry + source enablement")
    src.add_argument("--json", action="store_true")
    src.set_defaults(func=cmd_sources)

    doc = sub.add_parser("doctor", help="Environment and source-health diagnostics")
    doc.add_argument("--json", action="store_true")
    doc.set_defaults(func=cmd_doctor)

    e = sub.add_parser("email-digest", help="Email the digest via SMTP or Resend")
    e.add_argument("--since", default=None)
    e.set_defaults(func=cmd_email_digest)

    daily = sub.add_parser("run-daily", help="discover → rank → digest → optional email")
    daily.add_argument("--limit", type=int, default=40)
    daily.add_argument("--email", action="store_true")
    daily.add_argument("--quiet", action="store_true")
    daily.add_argument("--llm", action="store_true")
    daily.add_argument(
        "--companies",
        action="store_true",
        help="Run company discovery/validation before job discover (off by default)",
    )
    daily.set_defaults(func=cmd_run_daily)

    co = sub.add_parser("companies", help="Company registry discovery and validation")
    co_sub = co.add_subparsers(dest="companies_command", required=True)

    co_d = co_sub.add_parser("discover", help="Discover and validate company boards")
    co_d.add_argument("--no-validate", action="store_true")
    co_d.set_defaults(func=cmd_companies)

    co_v = co_sub.add_parser("validate", help="Re-validate registry boards")
    co_v.add_argument("--ats", default=None)
    co_v.add_argument("--status", default=None)
    co_v.add_argument("--force", action="store_true")
    co_v.set_defaults(func=cmd_companies)

    co_l = co_sub.add_parser("list", help="List companies in SQLite registry")
    co_l.add_argument("--ats", default=None)
    co_l.add_argument("--status", default=None)
    co_l.add_argument("--enabled", choices=["true", "false"], default=None)
    co_l.add_argument("--json", action="store_true")
    co_l.set_defaults(func=cmd_companies)

    co_s = co_sub.add_parser("stats", help="Company registry statistics")
    co_s.set_defaults(func=cmd_companies)

    co_e = co_sub.add_parser("export", help="Export companies in community YAML shape")
    co_e.add_argument("--validated", action="store_true")
    co_e.add_argument("--out", default=None)
    co_e.set_defaults(func=cmd_companies)

    co_i = co_sub.add_parser("import", help="Import community/user company YAML into SQLite")
    co_i.add_argument("path")
    co_i.set_defaults(func=cmd_companies)

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

    mig = sub.add_parser("migrate", help="Import legacy seen_jobs + tracker into SQLite")
    mig.add_argument("--seen", default=None)
    mig.add_argument("--tracker", default=None)
    mig.set_defaults(func=cmd_migrate)

    sa = sub.add_parser("sync-application", help="Record an application into SQLite")
    sa.add_argument("--company", required=True)
    sa.add_argument("--role", required=True)
    sa.add_argument("--status", default="applied")
    sa.add_argument("--notes", default="")
    sa.add_argument("--write-tracker", action="store_true")
    sa.set_defaults(func=cmd_sync_application)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        _err(f"error: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        _err(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
