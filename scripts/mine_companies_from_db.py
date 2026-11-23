#!/usr/bin/env python3
"""
Mine net-new Canadian tech employers from the local DB and add to companies.yaml.

Heuristics:
- Company has at least 1 job with a URL that classifies to a supported ATS
- Company is not already present in companies.yaml (by normalized name)
- At least 1 job appears Canada-eligible by location string (Canada or a known Canadian city/province)

Writes new entries and re-sorts/dedupes companies.yaml.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPANIES_PATH = ROOT / "config" / "companies.yaml"


def _norm_name(name: str) -> str:
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def load_companies() -> list[dict[str, Any]]:
    data = yaml.safe_load(COMPANIES_PATH.read_text(encoding="utf-8")) or {}
    return [c for c in (data.get("companies") or []) if isinstance(c, dict)]


def canada_signal(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    if re.search(r"\bcanada\b", s, re.I):
        return True
    # Provinces and major cities
    if re.search(
        r"\b(ontario|british columbia|quebec|alberta|manitoba|saskatchewan|nova scotia|new brunswick|"
        r"toronto|ottawa|vancouver|montreal|calgary|edmonton|waterloo|kitchener|mississauga|markham|"
        r"burnaby|laval|kanata|halifax|winnipeg)\b",
        s,
        re.I,
    ):
        return True
    return False


def main() -> None:
    from jobseek.config_loader import Settings
    from jobseek.db.store import Database
    from jobseek.adapters.detector import classify_host

    settings = Settings.from_env()
    db = Database(settings.db_path)
    try:
        rows = db._conn.execute(
            """
            SELECT DISTINCT company, url, apply_url, location_raw
            FROM jobs
            WHERE removed_at IS NULL
            """
        ).fetchall()
    finally:
        db.close()
    present = {c["name"]: c for c in load_companies()}
    present_norm = {_norm_name(n) for n in present}
    # Collect candidates by company name
    seen_tokens: set[tuple[str, str]] = set()
    candidates: dict[str, dict[str, Any]] = {}
    for r in rows:
        company = str(r["company"] or "").strip()
        if not company or _norm_name(company) in present_norm:
            continue
        url = str(r["apply_url"] or r["url"] or "").strip()
        loc = str(r["location_raw"] or "")
        if not url:
            continue
        det = classify_host(url)
        if not det or not det.ats or not det.board_token:
            continue
        if (det.ats, det.board_token.lower()) in seen_tokens:
            continue
        if not canada_signal(loc):
            continue
        seen_tokens.add((det.ats, det.board_token.lower()))
        candidates[company] = {
            "name": company,
            "careers_url": url,
            "ats": det.ats,
            "board_token": det.board_token,
            "enabled": True,
            "notes": "Discovered from local DB; Canada location evidence present",
        }
    if not candidates:
        print("no new companies found")
        return
    # Merge and write
    merged = load_companies() + sorted(candidates.values(), key=lambda c: c["name"].casefold())
    COMPANIES_PATH.write_text(yaml.safe_dump({"companies": merged}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    # Re-sort and dedupe canonically
    import subprocess, sys

    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "sort_companies_yaml.py")])
    print(f"added {len(candidates)} new companies")


if __name__ == "__main__":
    main()

