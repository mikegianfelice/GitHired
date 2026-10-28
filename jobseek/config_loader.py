"""Load YAML config and environment settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from jobseek.paths import db_path, resolve_config_file


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config must be a mapping: {path}")
    return data


def load_search(path: Path | None = None) -> dict[str, Any]:
    return _load_yaml(path or resolve_config_file("search.yaml"))


def load_profile(path: Path | None = None) -> dict[str, Any]:
    return _load_yaml(path or resolve_config_file("profile.yaml"))


def load_companies(path: Path | None = None) -> list[dict[str, Any]]:
    data = _load_yaml(path or resolve_config_file("companies.yaml"))
    companies = data.get("companies", [])
    if not isinstance(companies, list):
        raise ValueError("companies.yaml: companies must be a list")
    return [c for c in companies if isinstance(c, dict)]


@dataclass
class Settings:
    db_path: Path = field(default_factory=db_path)
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-4o"
    serpapi_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    smtp_use_tls: bool = True
    resend_api_key: str = ""
    resend_from: str = ""
    resend_to: str = ""
    log_level: str = "INFO"
    rank_llm: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        rank_llm_env = os.environ.get("GITHIRED_RANK_LLM", os.environ.get("JOBSEEK_RANK_LLM", "")).strip().lower()
        return cls(
            db_path=db_path(),
            llm_provider=os.environ.get("LLM_PROVIDER", "anthropic").strip().lower(),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514").strip(),
            openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
            openai_base_url=os.environ.get("OPENAI_BASE_URL", "").strip(),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o").strip(),
            serpapi_key=os.environ.get("SERPAPI_KEY", "").strip(),
            smtp_host=os.environ.get("SMTP_HOST", "").strip(),
            smtp_port=int(os.environ.get("SMTP_PORT", "587") or "587"),
            smtp_user=os.environ.get("SMTP_USER", "").strip(),
            smtp_pass=os.environ.get("SMTP_PASS", "").strip(),
            smtp_from=os.environ.get("SMTP_FROM", "").strip(),
            smtp_to=os.environ.get("SMTP_TO", "").strip(),
            smtp_use_tls=os.environ.get("SMTP_USE_TLS", "true").strip().lower()
            in ("1", "true", "yes"),
            resend_api_key=os.environ.get("RESEND_API_KEY", "").strip(),
            resend_from=os.environ.get("RESEND_FROM", "").strip(),
            resend_to=os.environ.get("RESEND_TO", "").strip(),
            log_level=os.environ.get("JOBSEEK_LOG_LEVEL", os.environ.get("GITHIRED_LOG_LEVEL", "INFO")).strip().upper(),
            rank_llm=rank_llm_env in ("1", "true", "yes"),
        )


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (no dependency). Does not override existing env."""
    candidates = []
    if path is not None:
        candidates.append(path)
    else:
        candidates.append(Path.cwd() / ".env")
        candidates.append(Path(__file__).resolve().parent.parent / ".env")
    for env_path in candidates:
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value
        return
