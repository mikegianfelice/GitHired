"""Canonical domain helpers for company deduplication."""

from __future__ import annotations

from urllib.parse import urlsplit


def canonical_domain(url_or_host: str) -> str | None:
    """Return a registrable-ish host (lowercase, no leading www.)."""
    raw = (url_or_host or "").strip().lower()
    if not raw:
        return None
    if "://" not in raw and "/" not in raw and " " not in raw:
        host = raw
    else:
        if "://" not in raw:
            raw = "https://" + raw
        host = (urlsplit(raw).hostname or "").lower()
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None
