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


class JobAdapter(Protocol):
    name: str

    def fetch_company(self, company: dict) -> AdapterResult: ...
