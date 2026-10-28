"""Three-layer company registry: builtin → community → SQLite → local overrides."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from jobseek.companies.domain_util import canonical_domain
from jobseek.config_loader import load_companies
from jobseek.identity import normalize_text
from jobseek.paths import ROOT, resolve_config_file


def community_registry_path() -> Path:
    return ROOT / "registry" / "community" / "companies.v1.yaml"


def local_overrides_path() -> Path:
    """User overrides — never written by automatic discovery."""
    try:
        cfg = resolve_config_file("companies.yaml").parent
    except Exception:  # noqa: BLE001
        cfg = ROOT / "config"
    return cfg / "companies.local.yaml"


def load_community_companies(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or community_registry_path()
    if not target.is_file():
        return []
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    companies = data.get("companies", [])
    if not isinstance(companies, list):
        return []
    out = []
    for row in companies:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        item = dict(row)
        item.setdefault("discovery_source", "community")
        item.setdefault("source", "community")
        out.append(item)
    return out


def load_local_overrides(path: Path | None = None) -> dict[str, Any]:
    target = path or local_overrides_path()
    if not target.is_file():
        return {"companies": [], "exclude": []}
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {"companies": [], "exclude": []}
    companies = data.get("companies") or []
    exclude = data.get("exclude") or []
    return {
        "companies": [c for c in companies if isinstance(c, dict)],
        "exclude": [e for e in exclude if isinstance(e, (dict, str))],
    }


def _company_key(company: dict[str, Any]) -> tuple[str, ...]:
    ats = (company.get("ats") or "").strip().lower()
    token = (company.get("board_token") or company.get("site_slug") or "").strip().lower()
    if ats and token and ats not in ("unknown",):
        # Include feed URL tokens for rss; never invent tokens elsewhere.
        return ("ats", ats, token)
    # Prefer name identity when ATS board is unknown — domain alone must not
    # collapse distinct employers that share a careers host.
    return ("name", normalize_text(str(company.get("name") or "")))


def _normalize_row(company: dict[str, Any], *, layer: str) -> dict[str, Any]:
    row = dict(company)
    name = str(row.get("name") or "").strip()
    row["name"] = name
    row["name_norm"] = normalize_text(name)
    row["ats"] = (row.get("ats") or "unknown")
    if row.get("site_slug") and not row.get("board_token"):
        row["board_token"] = row.get("site_slug")
    domain = row.get("domain") or canonical_domain(str(row.get("careers_url") or ""))
    row["domain"] = domain
    row.setdefault("discovery_source", layer)
    row.setdefault("source", layer)
    row.setdefault("enabled", True)
    row.setdefault("excluded", False)
    return row


def _merge_row(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if value is None:
            continue
        if key in ("name_norm",):
            continue
        merged[key] = value
    if overlay.get("domain"):
        merged["domain"] = overlay["domain"]
    elif not merged.get("domain"):
        merged["domain"] = canonical_domain(str(merged.get("careers_url") or ""))
    return merged


def _matches_exclude(company: dict[str, Any], rule: dict[str, Any] | str) -> bool:
    if isinstance(rule, str):
        needle = normalize_text(rule)
        return needle and (
            needle == company.get("name_norm")
            or needle == normalize_text(str(company.get("domain") or ""))
        )
    if rule.get("name") and normalize_text(str(rule["name"])) == company.get("name_norm"):
        return True
    if rule.get("domain"):
        dom = canonical_domain(str(rule["domain"])) or str(rule["domain"]).lower()
        if dom and dom == (company.get("domain") or "").lower():
            return True
    ats = (rule.get("ats") or "").lower()
    token = (rule.get("board_token") or rule.get("site_slug") or "").lower()
    if ats and token:
        if (company.get("ats") or "").lower() == ats and (
            company.get("board_token") or ""
        ).lower() == token:
            return True
    return False


def load_merged_companies(
    *,
    builtin: list[dict[str, Any]] | None = None,
    community: list[dict[str, Any]] | None = None,
    db_rows: list[dict[str, Any]] | None = None,
    overrides: dict[str, Any] | None = None,
    include_excluded: bool = False,
) -> list[dict[str, Any]]:
    """Merge registry layers. Later layers win field-by-field; exclude rules last."""
    layers: list[tuple[str, list[dict[str, Any]]]] = [
        ("builtin", builtin if builtin is not None else load_companies()),
        ("community", community if community is not None else load_community_companies()),
        ("db", db_rows or []),
    ]
    by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    order: list[tuple[str, ...]] = []

    name_index: dict[str, tuple[str, ...]] = {}

    def _find_existing_key(row: dict[str, Any]) -> tuple[str, ...] | None:
        key = _company_key(row)
        if key in by_key:
            return key
        name_norm = row.get("name_norm") or ""
        if name_norm and name_norm in name_index:
            return name_index[name_norm]
        # Domain match only when the existing row shares the same name
        # (shared careers hosts must not collapse distinct employers).
        domain = row.get("domain")
        if domain and name_norm:
            for existing_key, existing in by_key.items():
                if (
                    existing.get("domain") == domain
                    and existing.get("name_norm") == name_norm
                ):
                    return existing_key
        return None

    for layer_name, rows in layers:
        for raw in rows:
            if not raw.get("name"):
                continue
            row = _normalize_row(raw, layer=layer_name)
            existing_key = _find_existing_key(row)
            if existing_key is None:
                key = _company_key(row)
                by_key[key] = row
                order.append(key)
                name_index[row["name_norm"]] = key
            else:
                by_key[existing_key] = _merge_row(by_key[existing_key], row)
                name_index[row["name_norm"]] = existing_key
                # If ATS identity improved, also index under the new key
                new_key = _company_key(by_key[existing_key])
                if new_key != existing_key and new_key not in by_key:
                    by_key[new_key] = by_key.pop(existing_key)
                    order[order.index(existing_key)] = new_key
                    name_index[row["name_norm"]] = new_key
                    existing_key = new_key
                name_index[by_key[existing_key]["name_norm"]] = existing_key

    ov = overrides if overrides is not None else load_local_overrides()
    for raw in ov.get("companies") or []:
        if not raw.get("name") and not (raw.get("ats") and raw.get("board_token")):
            # Allow matching existing by ats/token only
            if raw.get("ats") and raw.get("board_token"):
                key = (
                    "ats",
                    str(raw["ats"]).lower(),
                    str(raw["board_token"]).lower(),
                )
                if key in by_key:
                    by_key[key] = _merge_row(by_key[key], _normalize_row({**by_key[key], **raw}, layer="override"))
                continue
            continue
        row = _normalize_row(raw, layer="override")
        key = _company_key(row)
        if key not in by_key:
            # Try name match against existing
            name_key = ("name", row["name_norm"])
            matched = None
            for existing_key, existing in by_key.items():
                if existing.get("name_norm") == row["name_norm"]:
                    matched = existing_key
                    break
            if matched is not None:
                by_key[matched] = _merge_row(by_key[matched], row)
            else:
                by_key[key] = row
                order.append(key)
        else:
            by_key[key] = _merge_row(by_key[key], row)

    exclude_rules = ov.get("exclude") or []
    out: list[dict[str, Any]] = []
    for key in order:
        company = by_key[key]
        excluded = bool(company.get("excluded"))
        for rule in exclude_rules:
            if _matches_exclude(company, rule):
                excluded = True
                break
        company["excluded"] = excluded
        if excluded and not include_excluded:
            continue
        out.append(company)
    return out


def company_to_community_export(company: dict[str, Any]) -> dict[str, Any]:
    """Strip local/private fields for community export."""
    return {
        "name": company.get("name"),
        "domain": company.get("domain")
        or canonical_domain(str(company.get("careers_url") or "")),
        "careers_url": company.get("careers_url"),
        "ats": company.get("ats"),
        "board_token": company.get("board_token"),
        "notes": company.get("notes"),
        "validation_status": company.get("validation_status"),
        "last_validated_at": company.get("last_validated_at"),
    }


def parse_community_document(text: str) -> list[dict[str, Any]]:
    data = yaml.safe_load(text) or {}
    if isinstance(data, list):
        return [c for c in data if isinstance(c, dict)]
    if isinstance(data, dict):
        companies = data.get("companies", [])
        if isinstance(companies, list):
            return [c for c in companies if isinstance(c, dict)]
    raise ValueError("community document must be a mapping with companies: []")


def validate_community_shape(companies: list[dict[str, Any]]) -> list[str]:
    """Lightweight schema check (no jsonschema dependency)."""
    errors: list[str] = []
    seen_keys: set[tuple[str, ...]] = set()
    for i, company in enumerate(companies):
        if not company.get("name"):
            errors.append(f"companies[{i}]: name is required")
            continue
        ats = company.get("ats")
        if not ats:
            errors.append(f"companies[{i}] ({company.get('name')}): ats is required")
        token = company.get("board_token")
        if ats in ("greenhouse", "lever", "ashby", "workable", "rippling", "gem") and not token:
            errors.append(
                f"companies[{i}] ({company.get('name')}): board_token required for ats={ats}"
            )
        key = _company_key(_normalize_row(company, layer="community"))
        if key in seen_keys:
            errors.append(f"companies[{i}] ({company.get('name')}): duplicate of {key}")
        seen_keys.add(key)
    return errors


def evidence_dumps(evidence: dict[str, Any]) -> str:
    return json.dumps(evidence, ensure_ascii=False, sort_keys=True)
