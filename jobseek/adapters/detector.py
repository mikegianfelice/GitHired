"""Detect ATS provider from a company careers URL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from jobseek.adapters.rss import discover_feed_url
from jobseek.http_client import RateLimitedClient

KNOWN_ATS_APEXES = {
    "greenhouse.io": "greenhouse",
    "lever.co": "lever",
    "ashbyhq.com": "ashby",
    "myworkdayjobs.com": "workday",
    "workday.com": "workday",
    "smartrecruiters.com": "smartrecruiters",
    "workable.com": "workable",
    "rippling.com": "rippling",
    "gem.com": "gem",
}

_GH_BOARD = re.compile(
    r"(?:boards(?:-api)?|job-boards)\.greenhouse\.io/([a-zA-Z0-9_-]+)", re.I
)
_LEVER_BOARD = re.compile(r"jobs\.lever\.co/([a-zA-Z0-9_-]+)", re.I)
_ASHBY_BOARD = re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)", re.I)
_WORKABLE_BOARD = re.compile(
    r"(?:apply|jobs)\.workable\.com/([a-zA-Z0-9_-]+)/?", re.I
)
_RIPPLING_BOARD = re.compile(
    r"ats\.rippling\.com/(?:api/v2/board/)?([a-zA-Z0-9_-]+)", re.I
)
_GEM_BOARD = re.compile(r"jobs\.gem\.com/([a-zA-Z0-9_-]+)/?", re.I)


@dataclass
class Detection:
    ats: str
    board_token: str | None
    evidence_url: str
    confidence: str  # high | medium | low


def _token_from_url(provider: str, url: str) -> str | None:
    patterns = {
        "greenhouse": _GH_BOARD,
        "lever": _LEVER_BOARD,
        "ashby": _ASHBY_BOARD,
        "workable": _WORKABLE_BOARD,
        "rippling": _RIPPLING_BOARD,
        "gem": _GEM_BOARD,
    }
    pattern = patterns.get(provider)
    if not pattern:
        return None
    match = pattern.search(url)
    return match.group(1) if match else None


def classify_host(url: str) -> Detection | None:
    parts = urlsplit(url.strip())
    host = (parts.netloc or "").lower()
    if not host:
        return None
    for apex, provider in KNOWN_ATS_APEXES.items():
        # Exact apex or real subdomain. Reject lookalikes.
        if not (host == apex or host.endswith("." + apex)):
            continue
        token = _token_from_url(provider, url)
        confidence = "high" if token else "low"
        return Detection(provider, token, url, confidence)
    return None


def detect_from_html(html: str, base_url: str) -> Detection | None:
    direct = classify_host(base_url)
    if direct and direct.board_token:
        return direct
    patterns = [
        (_GH_BOARD, "greenhouse"),
        (_LEVER_BOARD, "lever"),
        (_ASHBY_BOARD, "ashby"),
        (_WORKABLE_BOARD, "workable"),
        (_RIPPLING_BOARD, "rippling"),
        (_GEM_BOARD, "gem"),
    ]
    for pattern, provider in patterns:
        match = pattern.search(html) or pattern.search(base_url)
        if match:
            return Detection(provider, match.group(1), match.group(0), "medium")
    feed = discover_feed_url(html, base_url)
    if feed:
        return Detection("rss", feed, feed, "medium")
    # iframe / script hints (host only — low confidence, never auto-enable)
    hints = (
        ("greenhouse.io", "greenhouse"),
        ("lever.co", "lever"),
        ("ashbyhq.com", "ashby"),
        ("workable.com", "workable"),
        ("rippling.com", "rippling"),
        ("jobs.gem.com", "gem"),
    )
    for needle, provider in hints:
        if needle in html:
            return Detection(provider, None, base_url, "low")
    return classify_host(base_url)


def detect_careers_page(
    careers_url: str, client: RateLimitedClient | None = None
) -> Detection | None:
    owned = client is None
    client = client or RateLimitedClient()
    try:
        immediate = classify_host(careers_url)
        if immediate and immediate.board_token:
            return immediate
        resp = client.get(careers_url)
        # Followed redirects: classify final URL
        final = classify_host(resp.url)
        if final and (final.board_token or final.confidence == "high"):
            return final
        return detect_from_html(resp.text, resp.url or careers_url)
    finally:
        if owned:
            client.close()
