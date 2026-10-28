"""Generic RSS / Atom job-feed adapter."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urljoin, urlsplit

from jobseek.adapters.base import AdapterResult
from jobseek.http_client import RateLimitedClient
from jobseek.models import RawJob

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_LINK_FEED = re.compile(
    r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>',
    re.I,
)
_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _find_child(parent: ET.Element, names: set[str]) -> ET.Element | None:
    for child in parent:
        if _local(child.tag).lower() in names:
            return child
    return None


def _cdata_text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(_cdata_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).strip()


def parse_feed_xml(body: str, *, company_name: str, source_url: str) -> list[RawJob]:
    root = ET.fromstring(body)
    jobs: list[RawJob] = []
    root_name = _local(root.tag).lower()

    # Shopify-style careers feed: <source><job>…</job></source>
    job_els = [c for c in root if _local(c.tag).lower() == "job"]
    if root_name == "source" or job_els:
        for item in job_els or [c for c in root.iter() if _local(c.tag).lower() == "job"]:
            title = _cdata_text(_find_child(item, {"title"}))
            apply = _cdata_text(_find_child(item, {"applyurl"}))
            job_id = _cdata_text(_find_child(item, {"partnerjobid"}))
            company = _cdata_text(_find_child(item, {"company"})) or company_name
            desc = _cdata_text(_find_child(item, {"description"}))
            loc = _cdata_text(_find_child(item, {"location"}))
            workplace = _cdata_text(_find_child(item, {"workplacetypes"}))
            listed = _cdata_text(_find_child(item, {"listdate"}))
            if workplace and loc:
                loc = f"{loc} ({workplace})"
            elif workplace and not loc:
                loc = workplace
            if not title or not (apply or job_id):
                continue
            url = apply or f"{source_url}#{job_id}"
            jobs.append(
                RawJob(
                    company=company,
                    title=title,
                    url=url,
                    apply_url=apply or url,
                    source="rss",
                    ats_provider="rss",
                    ats_job_id=job_id or url,
                    location_raw=loc or None,
                    description=desc or None,
                    posted_date=listed or None,
                    raw_payload={"title": title, "applyUrl": apply, "partnerJobId": job_id},
                )
            )
        if jobs:
            return jobs

    if root_name == "rss" or _find_child(root, {"channel"}) is not None:
        channel = _find_child(root, {"channel"}) or root
        for item in channel:
            if _local(item.tag).lower() != "item":
                continue
            title = _text(_find_child(item, {"title"}))
            link = _text(_find_child(item, {"link"}))
            guid = _text(_find_child(item, {"guid"}))
            desc = _text(_find_child(item, {"description"}))
            pub = _text(_find_child(item, {"pubdate"}))
            if not title or not (link or guid):
                continue
            url = link or guid
            jobs.append(
                RawJob(
                    company=company_name,
                    title=title,
                    url=url,
                    apply_url=url,
                    source="rss",
                    ats_provider="rss",
                    ats_job_id=guid or url,
                    description=desc or None,
                    posted_date=pub or None,
                    location_raw=None,
                    raw_payload={"title": title, "link": link, "guid": guid},
                )
            )
        return jobs

    # Atom
    entries = [c for c in root if _local(c.tag).lower() == "entry"]
    if not entries:
        entries = list(root.findall("atom:entry", _ATOM_NS))
    for entry in entries:
        title = _text(_find_child(entry, {"title"}))
        link_el = _find_child(entry, {"link"})
        href = ""
        if link_el is not None:
            href = (link_el.attrib.get("href") or _text(link_el)).strip()
        if not href:
            for child in entry:
                if _local(child.tag).lower() == "link":
                    href = (child.attrib.get("href") or "").strip()
                    if href:
                        break
        entry_id = _text(_find_child(entry, {"id"}))
        summary = _text(_find_child(entry, {"summary"})) or _text(
            _find_child(entry, {"content"})
        )
        updated = _text(_find_child(entry, {"updated"})) or _text(
            _find_child(entry, {"published"})
        )
        if not title or not (href or entry_id):
            continue
        url = href or entry_id
        jobs.append(
            RawJob(
                company=company_name,
                title=title,
                url=url,
                apply_url=url,
                source="rss",
                ats_provider="rss",
                ats_job_id=entry_id or url,
                description=summary or None,
                posted_date=updated or None,
                raw_payload={"title": title, "link": href, "id": entry_id},
            )
        )
    return jobs


def discover_feed_url(html: str, base_url: str) -> str | None:
    for match in _LINK_FEED.finditer(html or ""):
        tag = match.group(0)
        href_m = _HREF.search(tag)
        if href_m:
            return urljoin(base_url, href_m.group(1))
    # Common convention
    parts = urlsplit(base_url)
    if parts.scheme and parts.netloc:
        for path in ("/careers/feed.xml", "/careers/jobs.rss", "/jobs.rss", "/feed.xml"):
            # Prefer relative to careers host
            candidate = f"{parts.scheme}://{parts.netloc}{path}"
            if path in (html or ""):
                return candidate
    return None


class RssAdapter:
    name = "rss"

    def __init__(self, client: RateLimitedClient | None = None) -> None:
        self.client = client or RateLimitedClient()

    def fetch_company(self, company: dict) -> AdapterResult:
        token = (company.get("board_token") or company.get("site_slug") or "").strip()
        careers = (company.get("careers_url") or "").strip()
        feed_url = token if token.startswith("http") else ""
        result = AdapterResult(request_key=f"rss:{feed_url or company.get('name')}")
        try:
            if not feed_url and careers:
                page = self.client.get(careers)
                if page.status_code == 200:
                    found = discover_feed_url(page.text, page.url or careers)
                    if found:
                        feed_url = found
                if not feed_url:
                    # Try conventional Shopify-style path
                    parts = urlsplit(careers)
                    guess = f"{parts.scheme}://{parts.netloc}/careers/feed.xml"
                    feed_url = guess
            if not feed_url:
                result.errors.append(
                    f"rss: missing feed URL (board_token) for {company.get('name')}"
                )
                return result
            result.request_key = f"rss:{feed_url}"
            resp = self.client.get(feed_url)
            result.raw_status = resp.status_code
            if resp.status_code != 200:
                result.errors.append(f"rss {feed_url}: HTTP {resp.status_code}")
                return result
            body = resp.text or ""
            lower = body.lower()
            if (
                "<rss" not in lower
                and "<feed" not in lower
                and "<source" not in lower
                and "<job" not in lower
            ):
                result.errors.append(f"rss {feed_url}: response is not RSS/Atom/job XML")
                return result
            company_name = str(company.get("name") or urlsplit(feed_url).hostname or "rss")
            try:
                result.jobs = parse_feed_xml(body, company_name=company_name, source_url=feed_url)
            except ET.ParseError as exc:
                result.errors.append(f"rss {feed_url}: XML parse error ({exc})")
                return result
            return result
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"rss: {exc}")
            return result
