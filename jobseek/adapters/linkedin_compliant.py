"""Compliant LinkedIn discovery: free search, SerpAPI, and alert import.

Does not call LinkedIn jobs-guest endpoints. Scheduled discovery should use
search-engine indexing and/or imported saved-alert HTML/email.
"""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from jobseek.adapters.base import AdapterResult
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob

_HREF = re.compile(
    r'href=["\'](https?://(?:www\.)?linkedin\.com/jobs/view/[^"\']+)["\']',
    re.I,
)
_VIEW_ID = re.compile(r"linkedin\.com/jobs/view/(?:[\w-]+-)?(\d+)", re.I)
_DDG_RESULT = re.compile(
    r'href="(https?://(?:www\.)?linkedin\.com/jobs/[^"]+)"[^>]*>?\s*([^<]{0,200})',
    re.I,
)


def _job_from_link(
    link: str,
    *,
    title: str | None = None,
    company: str | None = None,
    snippet: str | None = None,
    source: str = "linkedin_search_index",
    raw: Any = None,
) -> RawJob:
    job_id = None
    m = _VIEW_ID.search(link)
    if m:
        job_id = m.group(1)
    clean_title = (title or f"LinkedIn job {job_id or 'unknown'}").strip()
    clean_company = (company or "Unknown").strip() or "Unknown"
    description = (snippet or clean_title).strip() or clean_title
    return RawJob(
        company=clean_company,
        title=clean_title,
        url=link.split("?")[0],
        source=source,
        ats_provider="linkedin",
        ats_job_id=job_id,
        location_raw=None,
        description=description,
        raw_payload=raw,
    )


class LinkedInSearchIndexAdapter:
    """Fetch LinkedIn job URLs via SerpAPI (paid) or free DuckDuckGo HTML."""

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
        if self.api_key:
            return self._search_serpapi(queries, limit_per_query=limit_per_query, result=result)
        free = self._search_free(queries, limit_per_query=limit_per_query, result=result)
        if free.jobs:
            return free
        if not free.errors:
            free.errors.append(
                "linkedin_search_index: no SERPAPI_KEY; free search returned no results "
                "(use githired import-alerts <file> for LinkedIn alert HTML/JSON)"
            )
        # Warnings only — caller should not treat as hard discover failure
        free.raw_status = None
        return free

    def _search_serpapi(
        self, queries: list[str], *, limit_per_query: int, result: AdapterResult
    ) -> AdapterResult:
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
                    if " - " in title:
                        parts = title.split(" - ", 1)
                        title, company = parts[0].strip(), parts[1].strip()
                    result.jobs.append(
                        _job_from_link(
                            link,
                            title=title,
                            company=company,
                            snippet=item.get("snippet") or "",
                            source="linkedin_search_index",
                            raw=item,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"serpapi query {query!r}: {exc}")
        return result

    def _search_free(
        self, queries: list[str], *, limit_per_query: int, result: AdapterResult
    ) -> AdapterResult:
        """Best-effort free discovery via duckduckgo-search or DDG HTML."""
        # Prefer optional duckduckgo-search package
        try:
            from duckduckgo_search import DDGS  # type: ignore

            seen: set[str] = set()
            with DDGS() as ddgs:
                for query in queries:
                    try:
                        for item in ddgs.text(query, max_results=limit_per_query):
                            link = (item.get("href") or item.get("link") or "").strip()
                            if "linkedin.com/jobs" not in link or link in seen:
                                continue
                            seen.add(link)
                            title = (item.get("title") or "LinkedIn role").split("|")[0].strip()
                            company = "Unknown"
                            if " - " in title:
                                parts = title.split(" - ", 1)
                                title, company = parts[0].strip(), parts[1].strip()
                            result.jobs.append(
                                _job_from_link(
                                    link,
                                    title=title,
                                    company=company,
                                    snippet=item.get("body") or item.get("snippet") or "",
                                    source="linkedin_search_free",
                                    raw=item,
                                )
                            )
                    except Exception as exc:  # noqa: BLE001
                        result.errors.append(f"duckduckgo query {query!r}: {exc}")
            result.raw_status = 200 if result.jobs else None
            return result
        except ImportError:
            pass

        # Fallback: DuckDuckGo HTML (fragile; treated as best-effort)
        seen_urls: set[str] = set()
        for query in queries:
            try:
                url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
                resp = self.client.get(url, headers={"User-Agent": "GitHired/0.2 (+local)"})
                result.raw_status = resp.status_code
                if resp.status_code != 200:
                    result.errors.append(f"duckduckgo html HTTP {resp.status_code} for {query!r}")
                    continue
                for match in _DDG_RESULT.finditer(resp.text):
                    link = unescape(match.group(1)).split("?")[0]
                    if "linkedin.com/jobs" not in link or link in seen_urls:
                        continue
                    seen_urls.add(link)
                    title = unescape(re.sub(r"<[^>]+>", "", match.group(2) or "")).strip()
                    result.jobs.append(
                        _job_from_link(
                            link,
                            title=title or None,
                            snippet=title,
                            source="linkedin_search_free",
                        )
                    )
                    if len(result.jobs) >= limit_per_query * max(len(queries), 1):
                        break
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"duckduckgo html {query!r}: {exc}")
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
        title = f"LinkedIn job {job_id or 'unknown'}"
        jobs.append(
            _job_from_link(url, title=title, snippet=title, source=source_name)
        )
    return jobs


def parse_alert_json(data: Any, *, source_name: str = "linkedin_alert") -> list[RawJob]:
    jobs: list[RawJob] = []
    items = data if isinstance(data, list) else (data.get("jobs") or data.get("items") or [])
    if not isinstance(items, list):
        return jobs
    for item in items:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or item.get("link") or "").strip()
        if not url or "linkedin.com/jobs" not in url:
            continue
        jobs.append(
            _job_from_link(
                url,
                title=item.get("title"),
                company=item.get("company"),
                snippet=item.get("description") or item.get("snippet") or item.get("title"),
                source=source_name,
                raw=item,
            )
        )
    return jobs


def import_alert_file(path: Path) -> AdapterResult:
    result = AdapterResult(request_key=f"linkedin_alert:{path.name}")
    if not path.is_file():
        result.errors.append(f"alert file not found: {path}")
        return result
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            result.errors.append(f"invalid JSON: {exc}")
            return result
        result.jobs = parse_alert_json(data)
    else:
        result.jobs = parse_alert_html(text)
    result.raw_status = 200
    if not result.jobs:
        result.errors.append("no LinkedIn job links found in alert file")
    return result
