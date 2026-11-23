"""Select and export a public Canada-eligible engineering shortlist.

Public listings are **not** personalized ranks. They reuse deterministic hard
filters + direct ATS URL checks. Never export profiles, credentials, scores,
or full job descriptions.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jobseek.filters.apply_url import select_actionable_apply_url
from jobseek.filters.hard import apply_hard_filters
from jobseek.filters.location import (
    _CANADA_HIRE,
    _CANADA_WORD,
    _US_GEO,
    find_any_canadian_province,
    find_any_canadian_cities,
    province_from_cities,
    infer_work_arrangement,
)
from jobseek.filters.tracks import detect_seniority, match_track
from jobseek.showcase.top_paying import (
    SHOWCASE_SEARCH,
    is_job_specific_apply_url,
    is_valid_apply_url,
    parse_iso_date,
)
from jobseek.skills.tech_extract import extract_technologies as _extract_technologies

SCHEMA_VERSION = 2
# Soft count ceiling only — publish all unique Canada-eligible jobs unless a
# payload-size safeguard trims (see api_snapshot.MAX_SNAPSHOT_BYTES).
DEFAULT_LIMIT = 10_000
DEFAULT_MAX_AGE_DAYS = 21
MIN_ANNUAL = 30_000.0
MAX_ANNUAL = 800_000.0
DEFAULT_USD_TO_CAD = 1.35

# Forbidden keys — never appear in public JSON (defense in depth).
_FORBIDDEN_SUBSTRINGS = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "token",
    "credential",
    "private_key",
    "email",
    "phone",
    "resume",
    "cv_path",
    "profile",
    "salary_alignment",
    "hard_filter",
    "fingerprint",
    "strengths",
    "gaps",
    "overall",
    "role_fit",
    "description",
)

PUBLIC_SEARCH: dict[str, Any] = {
    **SHOWCASE_SEARCH,
    "seniority": {
        "include": ["junior", "mid", "senior", "staff", "principal", "lead"],
        "exclude": ["intern", "coop", "student", "new_grad"],
    },
    "salary": {
        "policy": "none",
        "preferred_currency": "CAD",
        "floors_independent": False,
        "usd_to_cad": 1.35,
        "floors": {},
    },
    # Policy toggle: publish worldwide-remote roles without explicit Canada evidence.
    # Default true (approved 2026-11-23): label remote_scope='global', null province,
    # ranked below canada/province in search and match.
    "include_global_remote": True,
}


@dataclass(frozen=True)
class PublicJob:
    id: str
    title: str
    company: str
    location: str
    province: str | None
    work_arrangement: str
    remote_scope: str
    seniority: str | None
    track: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_available: bool
    salary_max_cad: float | None
    apply_url: str
    verified: bool
    first_seen: str
    last_verified: str
    discovered_today: bool
    technologies: list[str]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stable_id(company: str, title: str, apply_url: str) -> str:
    raw = f"{company.casefold()}|{title.casefold()}|{apply_url.casefold()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _salary_max_cad(
    salary_max: float | None,
    currency: str | None,
    *,
    fx_usd_cad: float = DEFAULT_USD_TO_CAD,
) -> float | None:
    if salary_max is None or not currency:
        return None
    cur = currency.upper()
    if cur == "CAD":
        return float(salary_max)
    if cur == "USD":
        return float(salary_max) * float(fx_usd_cad)
    return None


def _province_code(location: str) -> str | None:
    provinces = find_any_canadian_province(location)
    if not provinces:
        # Derive province from city names when province is absent.
        cities = find_any_canadian_cities(location)
        prov_name = province_from_cities(cities) if cities else None
        if not prov_name:
            return None
        provinces = [prov_name]
    # Prefer short codes when we can map
    name = provinces[0]
    mapping = {
        "Ontario": "ON",
        "British Columbia": "BC",
        "Quebec": "QC",
        "Alberta": "AB",
        "Manitoba": "MB",
        "Saskatchewan": "SK",
        "Nova Scotia": "NS",
        "New Brunswick": "NB",
        "Newfoundland and Labrador": "NL",
        "Prince Edward Island": "PE",
        "Yukon": "YT",
        "Northwest Territories": "NT",
        "Nunavut": "NU",
    }
    return mapping.get(name, name)


_US_ONLY_LOCATION = re.compile(
    r"""
    ^\s*(?:remote\s*[-–,()]+\s*)?(?:the\s+)?(?:united\s+states|u\.?s\.?a?\.?|usa)
    (?:\s*\(?\s*remote\s*\)?)?
    (?:\s*\([^)]*\))?
    \s*$
    |
    ^\s*united\s+states\s*\(\s*remote\s*\)\s*$
    |
    ^\s*remote\s*[-–—,]?\s*(?:united\s+states|u\.?s\.?a?\.?|usa)\s*$
    """,
    re.I | re.X,
)

_DUAL_CA_US_REMOTE = re.compile(
    r"""
    remote(?:ly)?\s+in\s+canada\s+or\s+(?:the\s+)?united\s+states |
    canada\s+or\s+(?:the\s+)?united\s+states |
    united\s+states\s+or\s+canada |
    (?:canada|canadian).{0,40}(?:united\s+states|u\.?s\.?a?\.?|usa) |
    (?:united\s+states|u\.?s\.?a?\.?|usa).{0,40}(?:canada|canadian)
    """,
    re.I | re.X,
)


def _structured_location_is_us_only(location: str) -> bool:
    """True when the ATS location field names the US with no Canada token."""
    loc = (location or "").strip()
    if not loc:
        return False
    if _CANADA_WORD.search(loc):
        return False
    if _US_ONLY_LOCATION.search(loc):
        return True
    return bool(_US_GEO.search(loc)) and not find_any_canadian_province(loc)


def public_location_label(location: str, description: str = "") -> str:
    """Public card location — never show exclusive US labels for Canada-eligible jobs.

    Some ATS boards set ``location`` to ``United States (Remote)`` while the body
    explicitly allows Canada. Eligibility may correctly PASS from description
    evidence; the displayed location must still reflect Canada eligibility.
    """
    loc = (location or "").strip() or "Canada"
    desc = description or ""
    if not _structured_location_is_us_only(loc):
        return loc[:120]
    if not _CANADA_HIRE.search(desc):
        return loc[:120]
    dual = _DUAL_CA_US_REMOTE.search(desc)
    if dual:
        label = re.sub(r"\s+", " ", dual.group(0)).strip()
        if not label.lower().startswith("remote"):
            label = f"Remote — {label}"
        return label[:120]
    hire = _CANADA_HIRE.search(desc)
    evidence = hire.group(0).strip() if hire else "Canada"
    return f"Remote — {evidence} (ATS location: {loc})"[:120]


# Location-field tokens that mean worldwide remote (not "Ukraine Anywhere").
_GLOBAL_REMOTE_LOCATION = re.compile(
    r"""
    ^\s*(?:remote\s*[-–—,/]?\s*)?(?:global|worldwide|anywhere)(?:\s*[-–—,/]?\s*remote)?\s*$ |
    \bremote\s*[-–—,/]?\s*(?:global|worldwide|anywhere)\b |
    \b(?:global|worldwide|anywhere)\s*[-–—,/]?\s*remote\b |
    \bwork\s+from\s+anywhere\b |
    \bhire\s+from\s+anywhere\b |
    \banywhere\s+in\s+the\s+world\b |
    \bremote\s*\(\s*anywhere\s*\) |
    ,\s*(?:global|worldwide)\s*$
    """,
    re.I | re.X,
)
# Description: require remote/WFA context — bare "global team" / "customers worldwide" do not count.
_GLOBAL_REMOTE_DESCRIPTION = re.compile(
    r"""
    \bwork\s+from\s+anywhere\b |
    \bhire\s+from\s+anywhere\b |
    \banywhere\s+in\s+the\s+world\b |
    \bremote\s*\(\s*anywhere\s*\) |
    \bremote\s*[-–—/]?\s*anywhere\b |
    \banywhere\s*[-–—/]?\s*remote\b |
    \b(?:worldwide|global)\s+remote\b |
    \bremote\s+(?:worldwide|global(?:ly)?)\b |
    \bremotely\s+(?:from\s+)?(?:anywhere|worldwide|globally)\b |
    \b(?:based|located|live)\s+anywhere\b |
    \bexecuted\s+from\s+anywhere\b |
    \bemployees?\s+(?:can\s+)?(?:work|be)\s+(?:from\s+)?anywhere\b |
    \bopen\s+to\s+(?:candidates?\s+)?(?:from\s+)?anywhere\b |
    \bglobal\s+team\b.{0,120}\bnot\s+your\s+location\b |
    \bprioritize\s+(?:your\s+)?talent,?\s+not\s+(?:your\s+)?location\b
    """,
    re.I | re.X,
)
_CANADA_SCOPED_ANYWHERE = re.compile(
    r"\banywhere\s+in\s+canada\b|\bacross\s+canada\b|\bcanada[-\s]?wide\b",
    re.I,
)
_OFFICES_WORLDWIDE_SCOPE = re.compile(
    r"\b(?:offices?|locations?|headquarters|hq|presence)\b.{0,40}\bworldwide\b|"
    r"\bworldwide\b.{0,40}\b(?:offices?|locations?|presence)\b",
    re.I,
)
_US_ONLY_REMOTE_LOCATION = re.compile(
    r"""
    \bremote\s*[-–—,]?\s*(?:united\s+states|\bu\.?s\.?a\.?\b|\bus\b)\b |
    \b(?:united\s+states|\bu\.?s\.?a\.?\b|\bus\b)\s*[-–—,]?\s*remote\b |
    \b(?:us|u\.s\.|usa)\s+only\b |
    \bunited\s+states\s+only\b
    """,
    re.I | re.X,
)


def _has_explicit_global_remote_signal(location: str, description: str = "") -> bool:
    """True when location/description explicitly claims global/worldwide/anywhere remote.

    Bare 'Remote' is not enough. Incidental 'global team' / 'offices worldwide' /
    'ideas from anywhere' is not enough. 'Anywhere in Canada' is Canada-scoped.
    """
    loc = location or ""
    desc = description or ""
    if _US_ONLY_REMOTE_LOCATION.search(loc):
        return False
    loc_check = loc
    desc_check = desc
    if _CANADA_SCOPED_ANYWHERE.search(loc_check):
        loc_check = _CANADA_SCOPED_ANYWHERE.sub(" ", loc_check)
    if _CANADA_SCOPED_ANYWHERE.search(desc_check):
        desc_check = _CANADA_SCOPED_ANYWHERE.sub(" ", desc_check)
    if _GLOBAL_REMOTE_LOCATION.search(loc_check):
        return True
    if _GLOBAL_REMOTE_DESCRIPTION.search(desc_check):
        return True
    return False


def _remote_scope(
    location: str,
    arrangement: str,
    provinces: list[str],
    description: str = "",
) -> str:
    """canada | province | americas | global | local | unspecified — never overclaim."""
    loc = (location or "").casefold()
    americas = bool(
        re.search(r"\b(?:americas|namer|north\s+america)\b", loc) and re.search(r"\bremote\b", loc)
    )
    nationwide = bool(
        re.search(
            r"\banywhere in canada\b|\bacross canada\b|\bcanada[-\s]?wide\b|"
            r"\bremote\s*[-–—]?\s*canada\b|\bcanada\s*\(?\s*remote|"
            r"\bremote\s+in\s+canada\b|\bcanada remote\b",
            loc,
        )
        or re.search(r"\bcanada\b", loc)
    )
    # Any structured Canadian province/city evidence beats worldwide marketing copy.
    province_remote = bool(provinces and re.search(r"\bremote\b", loc) and not nationwide)
    worldwide = _has_explicit_global_remote_signal(location, description)
    if arrangement == "remote":
        if americas:
            return "americas"
        # Canada-scoped remote must win over incidental global/anywhere tokens.
        if nationwide:
            return "canada"
        if province_remote or provinces:
            return "province"
        if worldwide:
            return "global"
        return "unspecified"
    if arrangement in ("hybrid", "onsite"):
        return "local" if (provinces or re.search(r"\bcanada\b", loc)) else "unspecified"
    return "unspecified"


def _salary_fields(job: dict[str, Any]) -> tuple[float | None, float | None, str | None, bool]:
    amin = job.get("salary_min")
    amax = job.get("salary_max")
    currency = (job.get("salary_currency") or "").strip().upper() or None
    try:
        vals = [float(v) for v in (amin, amax) if v is not None]
    except (TypeError, ValueError):
        return None, None, None, False
    if not vals or currency not in ("CAD", "USD"):
        return None, None, None, False
    if any(v < MIN_ANNUAL or v > MAX_ANNUAL for v in vals):
        return None, None, None, False
    lo, hi = min(vals), max(vals)
    return lo, hi, currency, True


def select_public_jobs(
    jobs: list[dict[str, Any]],
    *,
    limit: int = DEFAULT_LIMIT,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    now: datetime | None = None,
    search_cfg: dict[str, Any] | None = None,
    require_complete: bool = True,
) -> list[PublicJob]:
    """Return confirmed Canada-eligible engineering jobs for the public site."""
    now = now or datetime.now(timezone.utc)
    cfg = search_cfg or PUBLIC_SEARCH
    cutoff = now - timedelta(days=max(0, int(max_age_days)))
    today = now.astimezone(timezone.utc).date()
    out: list[PublicJob] = []

    for job in jobs:
        if job.get("removed_at"):
            continue
        title = str(job.get("title") or "").strip()
        company = str(job.get("company") or "").strip()
        if not title or not company:
            continue
        if require_complete and not int(job.get("description_complete") or 0):
            # Still allow list rows with substantial location evidence via hard filter
            # only when description_complete — public "verified" requires completeness.
            continue

        track = match_track(title, cfg)
        if not track.matched:
            continue

        last_seen = parse_iso_date(job.get("last_seen") or job.get("posted_date"))
        if last_seen is None or last_seen < cutoff:
            continue

        apply_url, verdict = select_actionable_apply_url(
            primary=job.get("apply_url") or job.get("url"),
            fallbacks=[job.get("url")],
        )
        if not apply_url or not verdict.actionable or verdict.kind != "direct":
            continue
        if not is_valid_apply_url(apply_url) or not is_job_specific_apply_url(apply_url):
            continue

        hard = apply_hard_filters(job, cfg)
        if hard.relevance == "NO_MATCH" or not hard.title_match:
            continue
        # Hard FAIL (INELIGIBLE / salary floor / etc.) never publishes.
        # FLAG is allowed only for the optional global-remote include path below.
        if hard.verdict == "FAIL":
            continue

        raw_location = str(job.get("location_raw") or "").strip() or "Canada"
        description = str(job.get("description") or "")
        location = public_location_label(raw_location, description)
        arrangement = infer_work_arrangement(
            raw_location, description
        ) or infer_work_arrangement(location, description)
        # Public cards: never invent arrangement. City-only locations may still
        # be Canada-eligible under onsite mode (eligibility gate), but cards stay
        # unspecified unless remote/hybrid/onsite is evidenced.
        work = arrangement if arrangement in ("remote", "hybrid", "onsite") else "unspecified"
        provinces = find_any_canadian_province(location) or find_any_canadian_province(raw_location)
        scope = _remote_scope(
            location,
            work if work != "unspecified" else arrangement,
            provinces,
            description,
        )
        # Description-backed Canada remote when ATS location was US-only.
        if (
            scope == "unspecified"
            and work == "remote"
            and _CANADA_HIRE.search(description)
            and _structured_location_is_us_only(raw_location)
        ):
            scope = "canada"
        # Province-restricted remote must not be labeled canada-wide
        if scope == "province" and work == "remote":
            pass  # explicit province scope kept

        include_global = (
            bool(cfg.get("include_global_remote"))
            and work == "remote"
            and scope == "global"
            and hard.eligibility == "UNCERTAIN"
            and hard.verdict in ("PASS", "FLAG")
        )
        # Eligibility gate: confirmed ELIGIBLE (PASS), or optional global-remote include.
        if hard.eligibility == "ELIGIBLE" and hard.verdict == "PASS":
            pass
        elif include_global:
            pass
        else:
            continue

        lo, hi, currency, salary_ok = _salary_fields(job)
        max_cad = _salary_max_cad(hi, currency) if salary_ok else None
        first_seen_dt = parse_iso_date(job.get("first_seen")) or last_seen
        first_seen = first_seen_dt.astimezone(timezone.utc).date().isoformat()
        last_verified = last_seen.astimezone(timezone.utc).date().isoformat()
        discovered_today = first_seen_dt.astimezone(timezone.utc).date() == today
        clean_url = apply_url.split("?")[0] if "utm_" in apply_url.casefold() else apply_url
        # Analyze full description for skill tags, but export labels only (never description text).
        tech = _extract_technologies(title, location, description)
        # Global remote: never invent a province.
        province = None if scope == "global" else (
            _province_code(location) or _province_code(raw_location)
        )

        out.append(
            PublicJob(
                id=_stable_id(company, title, clean_url),
                title=title,
                company=company,
                location=location[:120],
                province=province,
                work_arrangement=work,
                remote_scope=scope,
                seniority=detect_seniority(title),
                track=(track.tracks[0] if getattr(track, "tracks", None) else None),
                salary_min=lo,
                salary_max=hi,
                salary_currency=currency,
                salary_available=salary_ok,
                salary_max_cad=max_cad,
                apply_url=clean_url,
                verified=True,  # only after hard PASS + ELIGIBLE + direct posting URL + complete
                first_seen=first_seen,
                last_verified=last_verified,
                discovered_today=bool(discovered_today),
                technologies=tech,
                source=str(job.get("source") or job.get("ats_provider") or ""),
            )
        )

    def _scope_rank(j: PublicJob) -> int:
        s = (j.remote_scope or "").casefold()
        if s == "canada":
            return 0
        if s == "province" or (j.province and s != "global"):
            return 1
        if s == "global":
            return 3
        return 2

    out.sort(
        key=lambda j: (
            _scope_rank(j),
            0 if j.salary_available else 1,
            -(j.salary_max or 0),
            j.company.casefold(),
            j.title.casefold(),
        )
    )
    deduped: list[PublicJob] = []
    seen: set[tuple[str, str]] = set()
    for job in out:
        key = (job.company.casefold(), job.title.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(job)
        if len(deduped) >= max(0, int(limit)):
            break
    return deduped


def build_public_snapshot(
    jobs: list[PublicJob],
    *,
    generated_at: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    repo_url: str = "https://github.com/mikegianfelice/GitHired",
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "githired-public-shortlist",
        "limit": int(limit),
        "count": len(jobs),
        "usd_to_cad": DEFAULT_USD_TO_CAD,
        "repo_url": repo_url,
        "disclaimer": (
            "Public Canada-eligible engineering listings from employer ATS boards. "
            "Not personalized ranks. Salaries shown only when employers advertise them. "
            "Province-restricted remote is labeled as such — never implied Canada-wide. "
            "Client-side Find My Matches uses deterministic relevance scoring — not an LLM."
        ),
        "jobs": [j.to_dict() for j in jobs],
    }
    assert_public_payload_safe(payload)
    return payload


_BLOCKED_KEYS = frozenset(
    {
        "password",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "private_key",
        "credential",
        "credentials",
        "email",
        "phone",
        "resume",
        "cv_path",
        "profile",
        "hard_filter",
        "hard_filter_json",
        "config_fingerprint",
        "fingerprint",
        "strengths",
        "gaps",
        "strengths_json",
        "gaps_json",
        "overall",
        "role_fit",
        "salary_alignment",
        "description",
        "description_html",
    }
)


def assert_public_payload_safe(payload: dict[str, Any]) -> None:
    """Raise if the snapshot appears to contain secrets or personal fields."""

    def walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = str(k).casefold()
                if key in _BLOCKED_KEYS or key.endswith("_password") or key.endswith("_secret"):
                    raise ValueError(f"forbidden field at {path}.{k}")
                walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk(item, f"{path}[{i}]")

    walk(payload)


def write_public_site(
    snapshot: dict[str, Any],
    site_dir: Path,
    *,
    preserve_on_empty: bool = True,
) -> dict[str, Any]:
    """Write ``jobs.json`` into ``site_dir``. Returns write status metadata.

    When ``preserve_on_empty`` is true and the new snapshot has zero jobs while
    a previous non-empty ``jobs.json`` exists, the previous file is kept and
    ``preserved_previous`` is set — callers should treat this as a soft failure
    for deployment decisions.
    """
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    target = site_dir / "jobs.json"
    meta: dict[str, Any] = {
        "path": str(target),
        "count": int(snapshot.get("count") or 0),
        "written": False,
        "preserved_previous": False,
    }
    previous: dict[str, Any] | None = None
    if target.is_file():
        try:
            previous = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None

    new_count = int(snapshot.get("count") or 0)
    prev_count = int((previous or {}).get("count") or 0) if previous else 0
    if preserve_on_empty and new_count == 0 and prev_count > 0:
        meta["preserved_previous"] = True
        meta["count"] = prev_count
        return meta

    assert_public_payload_safe(snapshot)
    target.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    meta["written"] = True
    return meta


def load_jobs_from_db(db: Any) -> list[dict[str, Any]]:
    """Load job rows suitable for public export from a Database instance."""
    conn = getattr(db, "_conn", None)
    if conn is None:
        raise RuntimeError("Database connection is not available")
    rows = conn.execute(
        """
        SELECT id, company, title, location_raw, description, description_complete,
               salary_min, salary_max, salary_currency, salary_raw,
               url, apply_url, source, ats_provider, first_seen, last_seen,
               posted_date, removed_at
        FROM jobs
        WHERE removed_at IS NULL
        """
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        if hasattr(r, "keys"):
            out.append({k: r[k] for k in r.keys()})
        else:
            out.append(dict(r))
    return out
