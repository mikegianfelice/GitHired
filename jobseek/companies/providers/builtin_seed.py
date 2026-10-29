"""Emit builtin + community seed companies as discovery candidates."""

from __future__ import annotations

from typing import Any

from jobseek.companies.domain_util import canonical_domain
from jobseek.companies.providers.base import CompanyCandidate
from jobseek.companies.registry import load_community_companies
from jobseek.config_loader import load_companies


def collect_builtin_candidates(
    *,
    include_community: bool = True,
) -> list[CompanyCandidate]:
    out: list[CompanyCandidate] = []
    for row in load_companies():
        if not row.get("name"):
            continue
        out.append(
            CompanyCandidate(
                name=str(row["name"]),
                domain=row.get("domain")
                or canonical_domain(str(row.get("careers_url") or "")),
                careers_url=row.get("careers_url"),
                ats=row.get("ats"),
                board_token=row.get("board_token") or row.get("site_slug"),
                discovery_source="builtin",
                notes=row.get("notes"),
                evidence={"enabled_in_yaml": bool(row.get("enabled", True))},
            )
        )
    if include_community:
        for row in load_community_companies():
            token = row.get("board_token")
            status = (row.get("validation_status") or "").lower()
            # Pre-validated community boards with tokens are safe to enable.
            enable = bool(token) and status in ("ok", "", "unvalidated")
            out.append(
                CompanyCandidate(
                    name=str(row.get("name")),
                    domain=row.get("domain")
                    or canonical_domain(str(row.get("careers_url") or "")),
                    careers_url=row.get("careers_url"),
                    ats=row.get("ats"),
                    board_token=token,
                    discovery_source="community",
                    notes=row.get("notes"),
                    evidence={
                        "validation_status": status or "ok",
                        "enable": enable,
                        "last_validated_at": row.get("last_validated_at"),
                        "contributor": row.get("contributor"),
                    },
                )
            )
    return out
