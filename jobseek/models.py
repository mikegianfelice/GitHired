"""Normalized job and score models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RawJob:
    """A job as returned by an adapter before persistence."""

    company: str
    title: str
    url: str
    source: str
    ats_provider: str | None = None
    ats_job_id: str | None = None
    location_raw: str | None = None
    apply_url: str | None = None
    description: str | None = None
    salary_raw: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    posted_date: str | None = None
    raw_payload: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HardFilterResult:
    verdict: str  # PASS | FAIL | FLAG
    reasons: list[str] = field(default_factory=list)
    title_match: bool = False
    location_verdict: str = "FLAG"
    salary_verdict: str = "PASS"
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreResult:
    overall: float
    scores: dict[str, float]
    strengths: list[str]
    gaps: list[str]
    salary_alignment: str
    rejection_reasons: list[str]
    evidence: list[str]
    model: str
    score_kind: str = "deterministic"  # deterministic | llm | hard_filter
    hard_filter: HardFilterResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
