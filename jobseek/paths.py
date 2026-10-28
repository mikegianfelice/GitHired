"""Repository and config path helpers."""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def packaged_defaults_dir() -> Path | None:
    """Return path to shipped default YAML files, if available on disk."""
    try:
        root = resources.files("jobseek").joinpath("data/defaults")
        # Prefer filesystem path when installed from a wheel/editable tree
        if hasattr(root, "joinpath"):
            as_path = Path(str(root))
            if as_path.is_dir():
                return as_path
    except (ModuleNotFoundError, TypeError, AttributeError):
        pass
    fallback = Path(__file__).resolve().parent / "data" / "defaults"
    return fallback if fallback.is_dir() else None


def config_dir() -> Path:
    override = os.environ.get("JOBSEEK_CONFIG_DIR") or os.environ.get("GITHIRED_CONFIG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local = Path.cwd() / "config"
    if local.is_dir():
        return local.resolve()
    repo = ROOT / "config"
    if repo.is_dir():
        return repo.resolve()
    packaged = packaged_defaults_dir()
    if packaged is not None:
        return packaged
    return repo


def resolve_config_file(name: str) -> Path:
    """Resolve a config YAML: JOBSEEK_CONFIG_DIR / ./config / packaged defaults."""
    override = os.environ.get("JOBSEEK_CONFIG_DIR") or os.environ.get("GITHIRED_CONFIG_DIR")
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser().resolve() / name)
    candidates.append(Path.cwd() / "config" / name)
    candidates.append(ROOT / "config" / name)
    packaged = packaged_defaults_dir()
    if packaged is not None:
        candidates.append(packaged / name)
    for path in candidates:
        if path.is_file():
            return path
    # Last resort: first candidate for error messages
    return candidates[0]


def db_path() -> Path:
    override = os.environ.get("JOBSEEK_DB_PATH") or os.environ.get("GITHIRED_DB_PATH") or "data/jobseek.db"
    path = Path(override).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
        if not path.parent.exists() and (ROOT / "data").exists():
            path = ROOT / override
    return path.resolve()


def tracker_path() -> Path:
    return ROOT / "job_search_tracker.csv"


def seen_jobs_path() -> Path:
    return ROOT / "job_scraper" / "seen_jobs.json"
