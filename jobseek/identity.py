"""Dedup identities: canonical key, ATS id, URL, company+title."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jobseek.util.job_key import make_key, slugify

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

# Path segments that uniquely identify a posting when ats_job_id is absent.
_URL_JOB_ID = re.compile(
    r"(?:"
    r"/jobs/(\d{5,})"  # Greenhouse
    r"|/job/[^/]*?_([Rr]?\d{5,})"  # Workday req in path
    r"|/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"  # Lever UUID
    r")",
    re.I,
)


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


def _disambiguator(
    *,
    ats_provider: str | None,
    ats_job_id: str | None,
    clean_url: str,
) -> str | None:
    """Stable suffix so same company+title twins (NY vs Toronto) stay distinct.

    ``make_key`` ignores URL for ASCII titles, which previously collapsed
    multi-geo postings into one row and produced Canada false positives.
    """
    if ats_provider and ats_job_id:
        id_slug = slugify(ats_job_id) or hashlib.sha1(
            ats_job_id.encode("utf-8")
        ).hexdigest()[:8]
        return f"{ats_provider}_{id_slug}"
    if clean_url:
        match = _URL_JOB_ID.search(clean_url)
        if match:
            for g in match.groups():
                if g:
                    return f"url_{slugify(g) or g.lower()}"
        digest = hashlib.sha1(clean_url.encode("utf-8")).hexdigest()[:8]
        return f"url_{digest}"
    return None


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
        provider = (ats_provider or "").strip().lower() or None
        job_id = (str(ats_job_id).strip() if ats_job_id else None) or None
        base = make_key(company, title, clean_url)
        suffix = _disambiguator(
            ats_provider=provider, ats_job_id=job_id, clean_url=clean_url
        )
        canonical = f"{base}__{suffix}" if suffix else base
        return cls(
            canonical_key=canonical,
            ats_provider=provider,
            ats_job_id=job_id,
            url=clean_url,
            company_norm=normalize_text(company),
            title_norm=normalize_text(title),
        )
