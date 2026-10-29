"""Select top advertised-salary Canada-eligible jobs for the public README.

Rules (explicit, no fabrication):
- Only jobs with numeric ``salary_min`` / ``salary_max`` already persisted by adapters.
- Treat values below ``MIN_ANNUAL`` as non-annual (hourly/contract noise) and exclude.
- Rank by annual base **high** end, converted to CAD for cross-currency comparison
  using a documented FX rate (display keeps the original currency).
- Require Canada geographic **ELIGIBLE** under the showcase location policy.
- Require a non-affiliate http(s) application URL.
- Require an engineering track match (repo focus).
- Exclude removed rows and listings whose ``last_seen`` is older than ``max_age_days``.
- Deduplicate by normalized company+title (keep highest salary).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from jobseek.filters.apply_url import classify_application_url
from jobseek.filters.location import classify_canada_eligibility
from jobseek.filters.tracks import match_track

DEFAULT_FX_USD_CAD = 1.35
MIN_ANNUAL = 30_000.0
DEFAULT_MAX_AGE_DAYS = 14
DEFAULT_LIMIT = 5

COMPARISON_RULE = (
    "Rank by advertised annual base salary high end, converted to CAD for sorting "
    f"only (USD×{DEFAULT_FX_USD_CAD:g}; other currencies excluded). "
    "Display the employer-stated currency and range unchanged. "
    "No estimates for undisclosed pay."
)

SHOWCASE_SEARCH: dict[str, Any] = {
    "tracks": [
        "software_engineering",
        "ai_engineering",
        "ml_engineering",
        "data_engineering",
        "analytics_engineering",
        "platform_engineering",
        "cloud_engineering",
        "devops_sre",
        "forward_deployed",
    ],
    # Broader than default search.yaml — showcase is marketing for the engineering
    # product surface, not a personal shortlist. Leadership + ML systems titles that
    # are unambiguously engineering IC/manager roles are included; FP&A / Legal / HR
    # remain unmatched.
    "track_aliases": {
        "software_engineering": [
            "Software Engineer",
            "Software Developer",
            "Full Stack Engineer",
            "Backend Engineer",
            "Frontend Engineer",
            "Full-Stack Engineer",
            "Head of Engineering",
            "Engineering Manager",
            "Director of Engineering",
            "Director, Software Engineering",
            "VP of Engineering",
            "VP Engineering",
        ],
        "ai_engineering": [
            "AI Engineer",
            "Applied AI Engineer",
            "Generative AI Engineer",
            "LLM Engineer",
            "AI Platform Engineer",
            "AI Solutions Architect",
        ],
        "ml_engineering": [
            "Machine Learning Engineer",
            "ML Engineer",
            "MLOps Engineer",
            "Deep Learning Engineer",
            "ML System Engineer",
            "ML Systems Engineer",
            "Machine Learning Systems Engineer",
        ],
        "data_engineering": [
            "Data Engineer",
            "Data Platform Engineer",
            "ETL Engineer",
        ],
        "analytics_engineering": [
            "Analytics Engineer",
        ],
        "platform_engineering": [
            "Platform Engineer",
            "Infrastructure Engineer",
            "Developer Experience Engineer",
        ],
        "cloud_engineering": [
            "Cloud Engineer",
            "Cloud Architect",
        ],
        "devops_sre": [
            "DevOps Engineer",
            "Site Reliability Engineer",
            "SRE",
            "Reliability Engineer",
        ],
        "forward_deployed": [
            "Forward Deployed Engineer",
        ],
    },
    "location": {
        "modes": ["remote_canada", "hybrid", "onsite", "remote_province"],
        "preferred": [
            "Canada remote",
            "Remote Canada",
            "Remote - Canada",
            "Canada (Remote)",
            "Anywhere in Canada",
        ],
        "cities": [
            "Toronto",
            "Vancouver",
            "Montreal",
            "Montréal",
            "Calgary",
            "Ottawa",
            "Mississauga",
            "Waterloo",
            "Kitchener",
            "Edmonton",
            "Winnipeg",
            "Halifax",
        ],
        "provinces": [
            "ON",
            "Ontario",
            "BC",
            "British Columbia",
            "QC",
            "Quebec",
            "AB",
            "Alberta",
            "MB",
            "Manitoba",
            "SK",
            "Saskatchewan",
            "NS",
            "Nova Scotia",
        ],
        "reject_us_only_remote": True,
        "unknown_location_policy": "flag",
        "allow_us_employer_remote_with_canada_evidence": True,
    },
}


@dataclass(frozen=True)
class ShowcaseJob:
    title: str
    company: str
    salary_min: float
    salary_max: float
    salary_currency: str
    location_raw: str
    eligibility_label: str
    apply_url: str
    verified_at: str  # ISO date YYYY-MM-DD (from last_seen)
    source: str
    rank_cad: float
    career_page_verified: bool = False
    discovered_today: bool = False
    first_seen: str = ""  # ISO date YYYY-MM-DD
    location_tag: str = ""
    work_mode_tag: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if len(text) == 10 and text[4] == "-":
            return datetime(int(text[:4]), int(text[5:7]), int(text[8:10]), tzinfo=timezone.utc)
        raw = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def verified_date_label(verified_at: str, *, today: datetime | None = None) -> str:
    """Fallback calendar label (never claims discovery-day freshness)."""
    _ = today
    return f"Verified {verified_at}"


def discovery_date_label(
    *,
    discovered_today: bool,
    verified_at: str,
    today: datetime | None = None,
) -> str:
    """Per-job freshness: 'Discovered Today' only when first_seen is today."""
    _ = today
    if discovered_today:
        return "Discovered Today"
    return f"Verified {verified_at}"


def infer_work_mode_tag(location_raw: str | None) -> str:
    text = (location_raw or "").casefold()
    if "hybrid" in text:
        return "Hybrid"
    if "remote" in text or "anywhere" in text:
        return "Remote"
    return "On-site"


def infer_location_tag(location_raw: str | None) -> str:
    loc = " ".join((location_raw or "").split()).strip() or "Canada"
    return loc[:40]


def is_career_page_verified(url: str | None) -> bool:
    """True only for direct employer ATS / career-page hosts (not affiliates)."""
    if not url or not str(url).strip():
        return False
    verdict = classify_application_url(str(url).strip())
    return verdict.kind == "direct" and verdict.actionable


def is_job_specific_apply_url(url: str | None) -> bool:
    """Reject generic careers listing hubs; require a posting-specific path.

    Accepts common ATS job-detail patterns (Greenhouse ``/jobs/<id>``, Lever
    posting UUIDs, Ashby job paths, Workday ``/job/…``, Workable ``/j/…``).
    """
    if not url or not str(url).strip():
        return False
    text = str(url).strip()
    try:
        parsed = urlparse(text)
    except Exception:  # noqa: BLE001
        return False
    path = (parsed.path or "").rstrip("/")
    if not path:
        return False
    host = (parsed.hostname or "").lower()
    lower_path = path.casefold()
    parts = [p for p in path.split("/") if p]

    # Board roots / generic hubs (no posting id)
    if lower_path in {
        "/careers",
        "/career",
        "/jobs",
        "/job",
        "/openings",
        "/positions",
        "/opportunities",
    }:
        return False
    if len(parts) == 1 and parts[0].casefold() in {
        "careers",
        "career",
        "jobs",
        "job",
        "openings",
        "positions",
        "opportunities",
    }:
        return False

    if "greenhouse.io" in host:
        return "/jobs/" in lower_path and bool(path.split("/jobs/")[-1])
    if "lever.co" in host:
        # /company/<posting-id>[/apply] — posting id required (not board root)
        return len(parts) >= 2 and parts[1].casefold() not in {"jobs", "careers", "job"}
    if "ashbyhq.com" in host:
        return len(parts) >= 2
    if "myworkdayjobs.com" in host or host.endswith("workday.com"):
        return "/job/" in lower_path
    if "workable.com" in host:
        return "/j/" in lower_path or "/jobs/" in lower_path
    if "rippling.com" in host:
        return len(parts) >= 2

    # Other direct hosts: need depth beyond a single “careers” segment
    return len(parts) >= 2


def annualize_for_rank(
    *,
    salary_min: float | None,
    salary_max: float | None,
    currency: str | None,
    fx_usd_cad: float = DEFAULT_FX_USD_CAD,
) -> float | None:
    """Return CAD-comparable annual high for ranking, or None if unusable."""
    cur = (currency or "").strip().upper()
    if cur not in ("CAD", "USD"):
        return None
    vals = [float(v) for v in (salary_min, salary_max) if v is not None]
    if not vals:
        return None
    if any(v < MIN_ANNUAL for v in vals):
        return None
    high = max(vals)
    if cur == "USD":
        return high * float(fx_usd_cad)
    return high


def format_salary_range(salary_min: float, salary_max: float, currency: str) -> str:
    cur = currency.upper()
    lo = int(round(salary_min))
    hi = int(round(salary_max))
    if lo == hi:
        return f"{cur} {lo:,}"
    return f"{cur} {lo:,}–{hi:,}"


def is_valid_apply_url(url: str | None) -> bool:
    """Showcase apply links must be direct, posting-specific employer ATS URLs."""
    if not url or not str(url).strip():
        return False
    text = str(url).strip()
    try:
        parsed = urlparse(text)
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    return is_career_page_verified(text) and is_job_specific_apply_url(text)


def eligibility_label(location_raw: str | None, eligibility: str) -> str:
    loc = (location_raw or "").strip() or "Canada-eligible"
    if eligibility != "ELIGIBLE":
        return loc
    # Keep employer location text; prefix for scannability
    return loc


def select_top_paying_jobs(
    jobs: list[dict[str, Any]],
    *,
    limit: int = DEFAULT_LIMIT,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    fx_usd_cad: float = DEFAULT_FX_USD_CAD,
    now: datetime | None = None,
    search_cfg: dict[str, Any] | None = None,
) -> list[ShowcaseJob]:
    """Filter and rank jobs; may return fewer than ``limit``."""
    now = now or datetime.now(timezone.utc)
    cfg = search_cfg or SHOWCASE_SEARCH
    cutoff = now - timedelta(days=max(0, int(max_age_days)))
    selected: list[ShowcaseJob] = []

    for job in jobs:
        if job.get("removed_at"):
            continue
        title = str(job.get("title") or "").strip()
        company = str(job.get("company") or "").strip()
        if not title or not company:
            continue

        track = match_track(title, cfg)
        if not track.matched:
            continue

        last_seen = parse_iso_date(job.get("last_seen") or job.get("posted_date"))
        if last_seen is None or last_seen < cutoff:
            continue

        amin = job.get("salary_min")
        amax = job.get("salary_max")
        try:
            amin_f = float(amin) if amin is not None else None
            amax_f = float(amax) if amax is not None else None
        except (TypeError, ValueError):
            continue
        if amin_f is None and amax_f is None:
            continue
        if amin_f is None:
            amin_f = amax_f
        if amax_f is None:
            amax_f = amin_f
        assert amin_f is not None and amax_f is not None

        currency = (job.get("salary_currency") or "").strip().upper()
        rank_cad = annualize_for_rank(
            salary_min=amin_f,
            salary_max=amax_f,
            currency=currency,
            fx_usd_cad=fx_usd_cad,
        )
        if rank_cad is None:
            continue

        apply_url = (job.get("apply_url") or job.get("url") or "").strip()
        if not is_valid_apply_url(apply_url):
            continue

        elig, _, _, _ = classify_canada_eligibility(job, cfg)
        if elig != "ELIGIBLE":
            continue

        verified_at = last_seen.date().isoformat()
        first_seen_dt = parse_iso_date(job.get("first_seen")) or last_seen
        first_seen = first_seen_dt.date().isoformat()
        today_date = now.astimezone(timezone.utc).date()
        discovered_today = first_seen_dt.astimezone(timezone.utc).date() == today_date
        clean_url = apply_url.split("?")[0] if "utm_" in apply_url else apply_url
        loc_raw = str(job.get("location_raw") or "").strip() or "Canada"
        selected.append(
            ShowcaseJob(
                title=title,
                company=company,
                salary_min=min(amin_f, amax_f),
                salary_max=max(amin_f, amax_f),
                salary_currency=currency,
                location_raw=loc_raw,
                eligibility_label=eligibility_label(job.get("location_raw"), elig),
                apply_url=clean_url,
                verified_at=verified_at,
                source=str(job.get("source") or ""),
                rank_cad=rank_cad,
                career_page_verified=is_career_page_verified(clean_url),
                discovered_today=discovered_today,
                first_seen=first_seen,
                location_tag=infer_location_tag(loc_raw),
                work_mode_tag=infer_work_mode_tag(loc_raw),
            )
        )

    # Highest CAD-equivalent high first; stable tie-breakers
    selected.sort(key=lambda j: (-j.rank_cad, j.company.casefold(), j.title.casefold()))

    deduped: list[ShowcaseJob] = []
    seen: set[tuple[str, str]] = set()
    for job in selected:
        key = (job.company.casefold(), job.title.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(job)
        if len(deduped) >= max(0, int(limit)):
            break
    return deduped


def snapshot_payload(
    jobs: list[ShowcaseJob],
    *,
    generated_at: datetime | None = None,
    fx_usd_cad: float = DEFAULT_FX_USD_CAD,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc)
    return {
        "generated_at": generated_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "comparison_rule": COMPARISON_RULE,
        "fx_usd_cad": fx_usd_cad,
        "count": len(jobs),
        "jobs": [j.to_dict() for j in jobs],
    }
