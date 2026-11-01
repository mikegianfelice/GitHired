"""HTTP client with retries, backoff, and simple rate limiting."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class HttpResponse:
    status_code: int
    text: str
    url: str

    def json(self) -> Any:
        import json

        return json.loads(self.text)


class RateLimitedClient:
    """Thread-safe HTTP client with a process-wide per-instance throttle.

    Each instance has its own throttle lock. Concurrent Workday companies should
    use separate clients so pagination is not serialized across boards.
    """

    def __init__(
        self,
        *,
        min_interval_s: float = 0.35,
        max_retries: int = 4,
        timeout_s: float = 30.0,
        user_agent: str = "GitHired-jobseek/0.2 (+personal job search)",
        max_connections: int = 16,
        max_keepalive: int = 8,
    ) -> None:
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self.timeout_s = timeout_s
        self.user_agent = user_agent
        self._last_request_at = 0.0
        self._lock = threading.Lock()
        self._request_count = 0
        self._client = httpx.Client(
            timeout=timeout_s,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
            },
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive,
            ),
        )

    @property
    def request_count(self) -> int:
        return self._request_count

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.min_interval_s:
                time.sleep(self.min_interval_s - elapsed)
            self._last_request_at = time.monotonic()

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        return self._request("GET", url, params=params, headers=headers)

    def post(
        self,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        return self._request("POST", url, json_body=json_body, headers=headers)

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self._client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                )
                with self._lock:
                    self._request_count += 1
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    delay = (
                        float(retry_after)
                        if retry_after and retry_after.isdigit()
                        else (2**attempt)
                    )
                    time.sleep(min(delay, 30))
                    continue
                return HttpResponse(resp.status_code, resp.text, str(resp.url))
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(2**attempt)
        raise RuntimeError(f"{method} failed for {url}: {last_exc}")


def workday_http_client() -> RateLimitedClient:
    """Dedicated client for one Workday company (keeps connection pool warm).

    Per-company clients avoid cross-board throttle starvation. Interval stays
    polite (~6–7 req/s peak per host) while allowing pagination to proceed.
    """
    return RateLimitedClient(
        min_interval_s=0.15,
        max_connections=12,
        max_keepalive=8,
        timeout_s=45.0,
    )
