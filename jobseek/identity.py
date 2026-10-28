"""Dedup identities: canonical key, ATS id, URL, company+title."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jobseek.util.job_key import make_key

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gh_src",
    "lever-source",
    "source",
    "ref",
    "referrer",
}


def canonical_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), "")
    )


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.strip().casefold())


@dataclass(frozen=True)
class JobIdentity:
    canonical_key: str
    ats_provider: str | None
    ats_job_id: str | None
    url: str
    company_norm: str
    title_norm: str

    @classmethod
    def from_fields(
        cls,
        *,
        company: str,
        title: str,
        url: str,
        ats_provider: str | None = None,
        ats_job_id: str | None = None,
    ) -> "JobIdentity":
        clean_url = canonical_url(url)
        return cls(
            canonical_key=make_key(company, title, clean_url),
            ats_provider=(ats_provider or "").strip().lower() or None,
            ats_job_id=(str(ats_job_id).strip() if ats_job_id else None) or None,
            url=clean_url,
            company_norm=normalize_text(company),
            title_norm=normalize_text(title),
        )
