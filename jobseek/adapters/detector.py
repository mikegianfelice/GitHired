"""Detect ATS provider from a company careers URL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from jobseek.http_client import RateLimitedClient

KNOWN_ATS_APEXES = {
    "greenhouse.io": "greenhouse",
    "lever.co": "lever",
    "ashbyhq.com": "ashby",
    "myworkdayjobs.com": "workday",
    "workday.com": "workday",
    "smartrecruiters.com": "smartrecruiters",
    "workable.com": "workable",
}

_GH_BOARD = re.compile(
    r"(?:boards(?:-api)?|job-boards)\.greenhouse\.io/([a-zA-Z0-9_-]+)", re.I
)
_LEVER_BOARD = re.compile(r"jobs\.lever\.co/([a-zA-Z0-9_-]+)", re.I)
_ASHBY_BOARD = re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)", re.I)


@dataclass
class Detection:
    ats: str
    board_token: str | None
    evidence_url: str
    confidence: str  # high | medium | low


def classify_host(url: str) -> Detection | None:
    parts = urlsplit(url.strip())
    host = (parts.netloc or "").lower()
    if not host:
        return None
    for apex, provider in KNOWN_ATS_APEXES.items():
        # Exact apex or real subdomain (boards.greenhouse.io). Reject
        # lookalikes like evil-greenhouse.io and greenhouse.io.evil.com.
        if not (host == apex or host.endswith("." + apex)):
            continue
        token = None
        if provider == "greenhouse":
            m = _GH_BOARD.search(url)
            token = m.group(1) if m else None
        elif provider == "lever":
            m = _LEVER_BOARD.search(url)
            token = m.group(1) if m else None
        elif provider == "ashby":
            m = _ASHBY_BOARD.search(url)
            token = m.group(1) if m else None
        return Detection(provider, token, url, "high")
    return None


def detect_from_html(html: str, base_url: str) -> Detection | None:
    direct = classify_host(base_url)
    if direct and direct.board_token:
        return direct
    patterns = [
        (_GH_BOARD, "greenhouse"),
        (_LEVER_BOARD, "lever"),
        (_ASHBY_BOARD, "ashby"),
    ]
    for pattern, provider in patterns:
        match = pattern.search(html) or pattern.search(base_url)
        if match:
            return Detection(provider, match.group(1), match.group(0), "medium")
    # iframe / script hints
    if "greenhouse.io" in html:
        return Detection("greenhouse", None, base_url, "low")
    if "lever.co" in html:
        return Detection("lever", None, base_url, "low")
    if "ashbyhq.com" in html:
        return Detection("ashby", None, base_url, "low")
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
