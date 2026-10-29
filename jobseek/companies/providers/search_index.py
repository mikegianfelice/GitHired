"""Optional search-index discovery of careers / ATS pages (graceful degrade)."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any
from urllib.parse import urlparse

from jobseek.adapters.detector import classify_host
from jobseek.companies.domain_util import canonical_domain
from jobseek.companies.providers.base import CompanyCandidate
from jobseek.http_client import RateLimitedClient

# Free DuckDuckGo / DDGS calls have no reliable client-side deadline and can
# stall `githired companies discover` for many minutes with no output.
_DDGS_TIMEOUT_S = 12.0

_ATS_QUERY_TEMPLATES = [
    'site:boards.greenhouse.io OR site:job-boards.greenhouse.io "{track}" Canada',
    'site:jobs.lever.co "{track}" Canada',
    'site:jobs.ashbyhq.com "{track}" Canada',
    'site:apply.workable.com "{track}" (Canada OR Remote)',
]


def _default_queries(search_cfg: dict[str, Any]) -> list[str]:
    tracks = search_cfg.get("tracks") or ["software engineering", "AI engineer"]
    aliases = search_cfg.get("track_aliases") or {}
    phrases: list[str] = []
    for track in tracks[:4]:
        if isinstance(track, str) and track in aliases and aliases[track]:
            phrases.append(str(aliases[track][0]))
        else:
            phrases.append(str(track).replace("_", " "))
    if not phrases:
        phrases = ["Software Engineer", "AI Engineer"]
    queries: list[str] = []
    for phrase in phrases[:3]:
        for tmpl in _ATS_QUERY_TEMPLATES:
            queries.append(tmpl.format(track=phrase))
    return queries


def _ddgs_text(query: str, *, max_results: int = 8) -> list[dict[str, str]]:
    from duckduckgo_search import DDGS  # type: ignore

    with DDGS() as ddgs:
        rows = list(ddgs.text(query, max_results=max_results))
    out: list[dict[str, str]] = []
    for row in rows:
        href = row.get("href") or row.get("link") or ""
        title = row.get("title") or ""
        if href:
            out.append({"url": href, "title": title})
    return out


def _ddg_results(query: str, client: RateLimitedClient) -> list[dict[str, str]]:
    """Best-effort DuckDuckGo results; empty on failure or timeout."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(_ddgs_text, query)
        try:
            return fut.result(timeout=_DDGS_TIMEOUT_S)
        except FuturesTimeout:
            fut.cancel()
            return []
    except Exception:  # noqa: BLE001
        pass
    finally:
        # Do not wait on a hung DDGS thread — fall through to HTML / empty.
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)
    # HTML fallback (httpx already has a request timeout)
    try:
        resp = client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
        )
        if resp.status_code != 200:
            return []
        links = re.findall(
            r'uddg=([^&"]+)|href="(https?://[^"]+)"',
            resp.text,
        )
        out: list[dict[str, str]] = []
        for a, b in links:
            url = a or b
            if "duckduckgo" in url:
                continue
            out.append({"url": url, "title": ""})
            if len(out) >= 8:
                break
        return out
    except Exception:  # noqa: BLE001
        return []


def _serpapi_results(query: str, api_key: str, client: RateLimitedClient) -> list[dict[str, str]]:
    try:
        resp = client.get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "api_key": api_key},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        out = []
        for row in data.get("organic_results") or []:
            link = row.get("link") or ""
            if link:
                out.append({"url": link, "title": row.get("title") or ""})
        return out
    except Exception:  # noqa: BLE001
        return []


def collect_search_index_candidates(
    search_cfg: dict[str, Any],
    client: RateLimitedClient,
    *,
    serpapi_key: str = "",
    max_queries: int = 8,
    use_serpapi: bool = True,
) -> tuple[list[CompanyCandidate], list[str]]:
    warnings: list[str] = []
    queries = _default_queries(search_cfg)[:max_queries]
    seen_tokens: set[tuple[str, str]] = set()
    out: list[CompanyCandidate] = []

    for query in queries:
        rows: list[dict[str, str]] = []
        if use_serpapi and serpapi_key:
            rows = _serpapi_results(query, serpapi_key, client)
            if not rows:
                warnings.append(f"search_index serpapi empty/failed for query: {query[:80]}")
        else:
            rows = _ddg_results(query, client)
            if not rows:
                warnings.append(
                    f"search_index free search unavailable/empty for query: {query[:80]}"
                )
                continue
        for row in rows:
            url = row.get("url") or ""
            detection = classify_host(url)
            if not detection or not detection.board_token:
                continue
            key = (detection.ats, detection.board_token.lower())
            if key in seen_tokens:
                continue
            seen_tokens.add(key)
            host = urlparse(url).hostname or detection.board_token
            out.append(
                CompanyCandidate(
                    name=row.get("title") or detection.board_token,
                    domain=canonical_domain(url) or host,
                    careers_url=url,
                    ats=detection.ats,
                    board_token=detection.board_token,
                    discovery_source="search_index",
                    evidence={"query": query, "title": row.get("title")},
                )
            )
    return out, warnings
