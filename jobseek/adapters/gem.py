"""Gem jobs board adapter — HTML listing when a stable public page exists."""

from __future__ import annotations

import re

from jobseek.adapters.base import AdapterResult
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob

_JOB_HREF = re.compile(
    r'href=["\'](https?://jobs\.gem\.com/[^"\']+/jobs/[^"\']+)["\']',
    re.I,
)
_TITLE_NEAR = re.compile(
    r'href=["\'](https?://jobs\.gem\.com/[^"\']+/jobs/[^"\']+)["\'][^>]*>([^<]{3,120})<',
    re.I,
)


class GemAdapter:
    name = "gem"

    def __init__(self, client: RateLimitedClient | None = None) -> None:
        self.client = client or RateLimitedClient()

    def fetch_company(self, company: dict) -> AdapterResult:
        token = (company.get("board_token") or company.get("site_slug") or "").strip()
        if not token:
            return AdapterResult(errors=[f"gem: missing board_token for {company.get('name')}"])
        url = f"https://jobs.gem.com/{token}"
        result = AdapterResult(request_key=f"gem:{token}")
        try:
            resp = self.client.get(url)
            result.raw_status = resp.status_code
            if resp.status_code != 200:
                result.errors.append(f"gem {token}: HTTP {resp.status_code}")
                return result
            html = resp.text or ""
            # Prefer title-bearing anchors; fall back to unique hrefs
            seen: set[str] = set()
            company_name = company.get("name") or token
            for match in _TITLE_NEAR.finditer(html):
                job_url, title = match.group(1).strip(), match.group(2).strip()
                if job_url in seen or not title:
                    continue
                seen.add(job_url)
                job_id = job_url.rstrip("/").rsplit("/", 1)[-1]
                result.jobs.append(
                    RawJob(
                        company=str(company_name),
                        title=title,
                        url=job_url,
                        apply_url=job_url,
                        source="gem",
                        ats_provider="gem",
                        ats_job_id=job_id,
                        raw_payload={"url": job_url, "title": title},
                    )
                )
            if not result.jobs:
                for match in _JOB_HREF.finditer(html):
                    job_url = match.group(1).strip()
                    if job_url in seen:
                        continue
                    seen.add(job_url)
                    job_id = job_url.rstrip("/").rsplit("/", 1)[-1]
                    result.jobs.append(
                        RawJob(
                            company=str(company_name),
                            title=job_id.replace("-", " ").title(),
                            url=job_url,
                            apply_url=job_url,
                            source="gem",
                            ats_provider="gem",
                            ats_job_id=job_id,
                            raw_payload={"url": job_url},
                        )
                    )
            if not result.jobs and "gem.com" in html.lower():
                # Page loaded but no extractable jobs — treat as empty board structure OK
                return result
            if not result.jobs:
                result.errors.append(
                    f"gem {token}: no job links found (unsupported markup)"
                )
                # Mark structure failure distinctly for validation
                result.raw_status = result.raw_status or 200
            return result
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"gem {token}: {exc}")
            return result
