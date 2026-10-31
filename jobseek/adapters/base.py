"""Adapter protocol and shared result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from jobseek.models import RawJob


@dataclass
class AdapterResult:
    jobs: list[RawJob] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_status: int | None = None
    request_key: str = ""
    # Completeness signals — incomplete boards must not trigger removals.
    listing_complete: bool = True
    hydration_complete: bool = True
    details_requested: int = 0
    details_cached: int = 0
    details_fetched: int = 0
    list_pages: int = 0
    timing: dict[str, float] = field(default_factory=dict)


class JobAdapter(Protocol):
    name: str

    def fetch_company(self, company: dict) -> AdapterResult: ...
