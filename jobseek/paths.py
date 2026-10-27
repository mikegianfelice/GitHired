"""Repository and config path helpers."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    override = os.environ.get("JOBSEEK_CONFIG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return ROOT / "config"


def db_path() -> Path:
    override = os.environ.get("JOBSEEK_DB_PATH", "data/jobseek.db")
    path = Path(override).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def tracker_path() -> Path:
    return ROOT / "job_search_tracker.csv"


def seen_jobs_path() -> Path:
    return ROOT / "job_scraper" / "seen_jobs.json"
