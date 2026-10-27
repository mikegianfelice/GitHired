"""Compliant LinkedIn discovery: search-index queries and alert import.

Does not call LinkedIn jobs-guest endpoints. Scheduled discovery should use
search-engine indexing (optional SerpAPI) and/or imported saved-alert HTML/email.
"""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any
from jobseek.adapters.base import AdapterResult
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob

_HREF = re.compile(
    r'href=["\'](https?://(?:www\.)?linkedin\.com/jobs/view/[^"\']+)["\']',
    re.I,
)
_TITLE_COMPANY = re.compile(
    r"<title>\s*(?P<title>[^|<]+)\s*(?:\||-|at)\s*(?P<company>[^<]+)</title>",
    re.I,
)
_VIEW_ID = re.compile(r"linkedin\.com/jobs/view/(?:[\w-]+-)?(\d+)", re.I)


class LinkedInSearchIndexAdapter:
    """Fetch LinkedIn job URLs via a search API (SerpAPI Google) when configured."""

    name = "linkedin_search_index"

    def __init__(
        self,
        *,
        api_key: str = "",
        client: RateLimitedClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.client = client or RateLimitedClient()

    def search(self, queries: list[str], *, limit_per_query: int = 10) -> AdapterResult:
        result = AdapterResult(request_key="linkedin_search_index")
        if not self.api_key:
            result.errors.append(
                "linkedin_search_index: SERPAPI_KEY not set; skipping live search "
                "(configure key or use jobseek import-alerts)"
            )
            return result
        seen_urls: set[str] = set()
        for query in queries:
            try:
                resp = self.client.get(
                    "https://serpapi.com/search.json",
                    params={
                        "engine": "google",
                        "q": query,
                        "api_key": self.api_key,
                        "num": limit_per_query,
                    },
                )
                result.raw_status = resp.status_code
                if resp.status_code != 200:
                    result.errors.append(f"serpapi HTTP {resp.status_code} for query={query!r}")
                    continue
                payload = resp.json()
                organic = payload.get("organic_results") or []
                for item in organic:
                    if not isinstance(item, dict):
                        continue
                    link = (item.get("link") or "").strip()
                    if "linkedin.com/jobs" not in link:
                        continue
                    if link in seen_urls:
                        continue
                    seen_urls.add(link)
                    title = (item.get("title") or "LinkedIn role").split("|")[0].strip()
                    company = "Unknown"
                    # Titles often look like "Role - Company | LinkedIn"
                    if " - " in title:
                        parts = title.split(" - ", 1)
                        title, company = parts[0].strip(), parts[1].strip()
                    job_id = None
                    m = _VIEW_ID.search(link)
                    if m:
                        job_id = m.group(1)
                    result.jobs.append(
                        RawJob(
                            company=company,
                            title=title,
                            url=link,
                            source="linkedin_search_index",
                            ats_provider="linkedin",
                            ats_job_id=job_id,
                            location_raw=None,
                            description=item.get("snippet") or "",
                            raw_payload=item,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"serpapi query {query!r}: {exc}")
        return result


def parse_alert_html(text: str, *, source_name: str = "linkedin_alert") -> list[RawJob]:
    """Extract LinkedIn job links from saved-alert email/HTML drops."""
    jobs: list[RawJob] = []
    seen: set[str] = set()
    for match in _HREF.finditer(text):
        url = unescape(match.group(1)).split("?")[0]
        if url in seen:
            continue
        seen.add(url)
        job_id = None
        m = _VIEW_ID.search(url)
        if m:
            job_id = m.group(1)
        # Try nearby text for title — fall back to job id
        title = f"LinkedIn job {job_id or 'unknown'}"
        company = "Unknown"
        jobs.append(
            RawJob(
                company=company,
                title=title,
                url=url,
                source=source_name,
                ats_provider="linkedin",
                ats_job_id=job_id,
                description="",
            )
        )
    # Title tag fallback for single-job pages
    tm = _TITLE_COMPANY.search(text)
    if tm and jobs:
        jobs[0].title = tm.group("title").strip()
        jobs[0].company = tm.group("company").strip()
    return jobs


def import_alert_file(path: Path) -> AdapterResult:
    result = AdapterResult(request_key=f"import-alerts:{path.name}")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".json":
            data = json.loads(text)
            items = data if isinstance(data, list) else data.get("jobs", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                url = (item.get("url") or "").strip()
                title = (item.get("title") or "").strip()
                company = (item.get("company") or "Unknown").strip()
                if not url or not title:
                    continue
                result.jobs.append(
                    RawJob(
                        company=company,
                        title=title,
                        url=url,
                        source="linkedin_alert",
                        ats_provider="linkedin",
                        ats_job_id=str(item.get("id") or "") or None,
                        location_raw=item.get("location"),
                        description=item.get("description") or "",
                        raw_payload=item,
                    )
                )
        else:
            result.jobs = parse_alert_html(text)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(str(exc))
    return result
