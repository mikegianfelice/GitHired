"""Company board validation pipeline (HTTP 200 alone is never enough)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from jobseek.companies.domain_util import canonical_domain
from jobseek.companies.registry import evidence_dumps
from jobseek.db.store import Database
from jobseek.http_client import RateLimitedClient
from jobseek.identity import normalize_text


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass
class ValidationResult:
    status: str  # ok | empty | invalid | unsupported | transient | excluded
    evidence: dict[str, Any] = field(default_factory=dict)
    enable: bool = False
    error: str | None = None


def _name_overlap(company_name: str, haystack: str) -> bool:
    left = normalize_text(company_name)
    right = normalize_text(haystack)
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    # Token overlap (ignore short tokens)
    lt = {t for t in left.replace("-", " ").split() if len(t) > 2}
    rt = {t for t in right.replace("-", " ").split() if len(t) > 2}
    return bool(lt & rt)


def should_skip_validation(
    company: dict[str, Any],
    *,
    force: bool = False,
    transient_cooldown_days: int = 7,
) -> str | None:
    if force:
        return None
    if company.get("excluded"):
        return "excluded"
    status = (company.get("validation_status") or "").lower()
    if status in ("invalid", "unsupported"):
        return f"skip_{status}"
    if status == "transient":
        last = _parse_ts(company.get("last_validated_at") or company.get("last_success_at"))
        if last and _utcnow() - last < timedelta(days=transient_cooldown_days):
            return "skip_transient_cooldown"
    return None


def validate_company(
    company: dict[str, Any],
    *,
    adapters: dict[str, Any],
    client: RateLimitedClient,
    auto_enable: bool = True,
) -> ValidationResult:
    """Probe a company board. Never invent tokens; never treat bare HTTP 200 as ok."""
    if company.get("excluded"):
        return ValidationResult(status="excluded", evidence={"reason": "excluded"}, enable=False)

    ats = (company.get("ats") or "unknown").lower()
    token = (company.get("board_token") or company.get("site_slug") or "").strip()
    careers = (company.get("careers_url") or "").strip()
    name = str(company.get("name") or "")
    evidence: dict[str, Any] = {
        "ats": ats,
        "board_token": token or None,
        "careers_url": careers or None,
        "checked_at": _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    domain = company.get("domain") or canonical_domain(careers)
    evidence["domain"] = domain
    if careers and domain:
        host = canonical_domain(careers)
        evidence["careers_domain"] = host
        evidence["domain_association"] = bool(host and domain and (host == domain or host.endswith("." + domain) or domain.endswith("." + host)))

    if ats in ("unknown", ""):
        return ValidationResult(
            status="unsupported",
            evidence={**evidence, "reason": "unknown ats"},
            enable=False,
            error="unknown ats",
        )

    adapter_cls = adapters.get(ats)
    if adapter_cls is None:
        return ValidationResult(
            status="unsupported",
            evidence={**evidence, "reason": f"no adapter for {ats}"},
            enable=False,
            error=f"no adapter for {ats}",
        )

    if not token and ats != "rss":
        return ValidationResult(
            status="invalid",
            evidence={**evidence, "reason": "missing board_token"},
            enable=False,
            error="missing board_token",
        )

    adapter = adapter_cls(client)
    try:
        result = adapter.fetch_company(company)
    except Exception as exc:  # noqa: BLE001
        return ValidationResult(
            status="transient",
            evidence={**evidence, "exception": str(exc)},
            enable=False,
            error=str(exc),
        )

    evidence["http_status"] = result.raw_status
    evidence["request_key"] = result.request_key
    evidence["job_count"] = len(result.jobs)
    evidence["adapter_errors"] = list(result.errors)

    if result.raw_status is None:
        return ValidationResult(
            status="transient",
            evidence=evidence,
            enable=False,
            error="; ".join(result.errors) or "no HTTP status",
        )

    if result.raw_status in (429, 500, 502, 503, 504):
        return ValidationResult(
            status="transient",
            evidence=evidence,
            enable=False,
            error=f"HTTP {result.raw_status}",
        )

    if result.raw_status == 404:
        return ValidationResult(
            status="invalid",
            evidence={**evidence, "reason": "missing board"},
            enable=False,
            error="HTTP 404",
        )

    if result.raw_status != 200:
        return ValidationResult(
            status="invalid",
            evidence=evidence,
            enable=False,
            error=f"HTTP {result.raw_status}",
        )

    # Structure: adapter must not report parse/structure errors on 200
    structure_errors = [
        e
        for e in result.errors
        if any(
            needle in e.lower()
            for needle in ("invalid json", "not a list", "xml parse", "not rss", "unexpected payload", "no job links", "unsupported markup")
        )
    ]
    if structure_errors:
        return ValidationResult(
            status="invalid",
            evidence={**evidence, "structure_errors": structure_errors},
            enable=False,
            error="; ".join(structure_errors),
        )

    # Ownership: when jobs exist, require name overlap with company or careers host
    if result.jobs:
        sample = " ".join(
            f"{j.company} {j.title} {j.url}" for j in result.jobs[:5]
        )
        host_bits = " ".join(
            filter(
                None,
                [
                    domain,
                    canonical_domain(careers) if careers else None,
                    urlsplit(result.jobs[0].url).hostname if result.jobs else None,
                ],
            )
        )
        owned = _name_overlap(name, sample) or _name_overlap(name, host_bits)
        evidence["ownership_match"] = owned
        if not owned and ats not in ("rss",):
            # Soft flag — still ok/empty if structure is valid, but do not auto-enable
            evidence["ownership_warning"] = "company name not found in sample jobs"
            return ValidationResult(
                status="ok" if result.jobs else "empty",
                evidence=evidence,
                enable=False,
                error=None,
            )

    if not result.jobs:
        return ValidationResult(
            status="empty",
            evidence=evidence,
            enable=auto_enable,
            error=None,
        )

    return ValidationResult(
        status="ok",
        evidence=evidence,
        enable=auto_enable,
        error=None,
    )


def persist_validation(
    db: Database,
    company: dict[str, Any],
    result: ValidationResult,
) -> None:
    now = _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    name = str(company.get("name") or "")
    existing = None
    from jobseek.identity import normalize_text as _norm

    row = db._conn.execute(
        "SELECT failure_count, enabled FROM companies WHERE name_norm = ?",
        (_norm(name),),
    ).fetchone()
    failures = int(row["failure_count"] or 0) if row else 0
    if result.status in ("invalid", "transient", "unsupported"):
        failures += 1
    elif result.status in ("ok", "empty"):
        failures = 0

    enabled = bool(company.get("enabled", True))
    if result.enable and result.status in ("ok", "empty"):
        enabled = True
    elif result.status == "excluded":
        enabled = False

    db.upsert_company(
        name=name,
        careers_url=company.get("careers_url"),
        ats=company.get("ats"),
        board_token=company.get("board_token") or company.get("site_slug"),
        validation_status=result.status,
        last_success_at=now if result.status in ("ok", "empty") else None,
        last_validated_at=now,
        last_error=result.error,
        enabled=enabled,
        notes=company.get("notes"),
        source=str(company.get("source") or "validate"),
        domain=company.get("domain") or canonical_domain(str(company.get("careers_url") or "")),
        discovery_source=company.get("discovery_source"),
        failure_count=failures,
        validation_evidence_json=evidence_dumps(result.evidence),
        excluded=bool(company.get("excluded")),
        preserve_enabled=not result.enable,
    )


def run_validate(
    db: Database,
    companies: list[dict[str, Any]],
    *,
    adapters: dict[str, Any],
    client: RateLimitedClient | None = None,
    force: bool = False,
    auto_enable: bool = True,
    transient_cooldown_days: int = 7,
) -> dict[str, Any]:
    owned = client is None
    client = client or RateLimitedClient()
    summary: dict[str, Any] = {
        "checked": 0,
        "skipped": [],
        "results": [],
        "ok": True,
    }
    try:
        for company in companies:
            reason = should_skip_validation(
                company,
                force=force,
                transient_cooldown_days=transient_cooldown_days,
            )
            if reason:
                summary["skipped"].append({"name": company.get("name"), "reason": reason})
                continue
            summary["checked"] += 1
            result = validate_company(
                company,
                adapters=adapters,
                client=client,
                auto_enable=auto_enable,
            )
            persist_validation(db, company, result)
            summary["results"].append(
                {
                    "name": company.get("name"),
                    "status": result.status,
                    "enable": result.enable,
                    "error": result.error,
                    "jobs": result.evidence.get("job_count"),
                }
            )
        return summary
    finally:
        if owned:
            client.close()
