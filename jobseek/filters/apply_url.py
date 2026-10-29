"""Application URL quality: prefer direct employer ATS links; reject affiliates.

Affiliate / aggregator redirects (e.g. WhatJobs) must not appear as confirmed
actionable recommendations. We classify hostnames only — no automatic redirect
following and no fabricated employer URLs.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

# Confirmed affiliate / job-board aggregators that are not employer apply pages.
_AFFILIATE_SUFFIXES = (
    "whatjobs.com",
    "whatjobs.ca",
    "jooble.org",
    "talent.com",
    "jobrapido.com",
    "neuvoo.ca",
    "neuvoo.com",
    "adzuna.ca",
    "adzuna.com",
    "ziprecruiter.com",
    "simplyhired.com",
    "glassdoor.com",
    "glassdoor.ca",
    "indeed.com",
    "indeed.ca",
)

# First-party / known ATS hosts we treat as direct employer application URLs.
_DIRECT_ATS_SUFFIXES = (
    "greenhouse.io",
    "boards.greenhouse.io",
    "lever.co",
    "jobs.lever.co",
    "ashbyhq.com",
    "jobs.ashbyhq.com",
    "myworkdayjobs.com",
    "workday.com",
    "workable.com",
    "apply.workable.com",
    "rippling.com",
    "ats.rippling.com",
    "smartrecruiters.com",
    "jobs.smartrecruiters.com",
    "bamboohr.com",
    "icims.com",
    "successfactors.com",
    "oraclecloud.com",
    "taleo.net",
    "jobvite.com",
    "greenhouse-boards.com",
    "dayforcehcm.com",
    "myworkdaysite.com",
    "ultipro.com",
    "recruiting.ultipro.com",
)

_AGGREGATOR_HOSTS = (
    "freehire.me",
    "www.freehire.me",
    "linkedin.com",
    "www.linkedin.com",
)


@dataclass(frozen=True)
class ApplyUrlVerdict:
    kind: str  # direct | affiliate | aggregator | unverified | missing
    host: str | None
    actionable: bool
    reason: str


def _host(url: str | None) -> str | None:
    if not url or not str(url).strip():
        return None
    try:
        parsed = urlparse(str(url).strip())
    except Exception:  # noqa: BLE001
        return None
    host = (parsed.hostname or "").lower().strip(".")
    return host or None


def _matches_suffix(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


def classify_application_url(url: str | None) -> ApplyUrlVerdict:
    """Classify a single application / posting URL by hostname."""
    host = _host(url)
    if not host:
        return ApplyUrlVerdict("missing", None, False, "missing application URL")
    if _matches_suffix(host, _AFFILIATE_SUFFIXES):
        return ApplyUrlVerdict(
            "affiliate",
            host,
            False,
            f"affiliate/aggregator host ({host})",
        )
    if host in _AGGREGATOR_HOSTS or host.endswith(".linkedin.com"):
        return ApplyUrlVerdict(
            "aggregator",
            host,
            False,
            f"aggregator listing host ({host}) — not a direct employer apply URL",
        )
    if _matches_suffix(host, _DIRECT_ATS_SUFFIXES):
        return ApplyUrlVerdict("direct", host, True, f"direct employer ATS host ({host})")
    # First-party employer career hosts (not affiliate / not known aggregator).
    # Still never invent URLs; we only accept the host Freehire already returned.
    return ApplyUrlVerdict(
        "direct",
        host,
        True,
        f"employer application host ({host})",
    )


def select_actionable_apply_url(
    *,
    primary: str | None,
    fallbacks: list[str | None] | None = None,
) -> tuple[str | None, ApplyUrlVerdict]:
    """Prefer a direct ATS URL; never invent URLs; never follow redirects.

    Returns (url_or_none, best_verdict). Affiliate-only sets are rejected for
    confirmed recommendations (actionable=False).
    """
    candidates: list[str] = []
    for raw in [primary, *(fallbacks or [])]:
        if not raw:
            continue
        text = str(raw).strip()
        if text and text not in candidates:
            candidates.append(text)

    if not candidates:
        return None, ApplyUrlVerdict("missing", None, False, "missing application URL")

    best_non_actionable: ApplyUrlVerdict | None = None
    for cand in candidates:
        verdict = classify_application_url(cand)
        if verdict.kind == "direct":
            return cand, verdict
        if best_non_actionable is None or (
            best_non_actionable.kind == "missing"
            and verdict.kind != "missing"
        ):
            best_non_actionable = verdict
        # Prefer recording affiliate over unverified when that is what we have
        if verdict.kind == "affiliate":
            best_non_actionable = verdict

    assert best_non_actionable is not None
    # Return the first candidate for provenance, but mark non-actionable.
    return candidates[0], best_non_actionable


def is_affiliate_url(url: str | None) -> bool:
    return classify_application_url(url).kind == "affiliate"
