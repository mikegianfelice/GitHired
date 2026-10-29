"""Shared candidate type for company discovery providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompanyCandidate:
    name: str | None
    domain: str | None = None
    careers_url: str | None = None
    ats: str | None = None
    board_token: str | None = None
    discovery_source: str = "unknown"
    evidence: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None

    def as_company_dict(self) -> dict[str, Any]:
        enable = bool(
            self.evidence.get("enabled_in_yaml")
            or self.evidence.get("enable")
            or self.evidence.get("validation_status") == "ok"
        )
        return {
            "name": self.name or self.domain or self.board_token or "unknown",
            "domain": self.domain,
            "careers_url": self.careers_url,
            "ats": self.ats or "unknown",
            "board_token": self.board_token,
            "discovery_source": self.discovery_source,
            "source": self.discovery_source,
            "enabled": enable,
            "notes": self.notes,
            "evidence": self.evidence,
        }
