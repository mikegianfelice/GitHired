"""Interactive / non-interactive first-time configuration (no YAML editing required)."""

from __future__ import annotations

from typing import Any

import yaml

from jobseek.filters.location import normalize_province_list
from jobseek.filters.tracks import DEFAULT_TRACK_ALIASES, TRACK_LABELS

# YAML 1.1 country-code footguns when unquoted
_YAML_BOOLISH = {"on", "off", "yes", "no", "true", "false", "y", "n"}

_PROVINCE_CHOICES = [
    ("ON", "Ontario"),
    ("QC", "Quebec"),
    ("BC", "British Columbia"),
    ("AB", "Alberta"),
    ("MB", "Manitoba"),
    ("SK", "Saskatchewan"),
    ("NS", "Nova Scotia"),
    ("NB", "New Brunswick"),
    ("NL", "Newfoundland and Labrador"),
    ("PE", "Prince Edward Island"),
    ("YT", "Yukon"),
    ("NT", "Northwest Territories"),
    ("NU", "Nunavut"),
]

_MODE_HELP = [
    ("remote_canada", "Remote roles that hire in Canada"),
    ("remote_province", "Remote within selected province(s)"),
    ("hybrid", "Hybrid in selected Canadian cities"),
    ("onsite", "On-site in selected Canadian cities"),
]


class _Quoted(str):
    """Force YAML single-quoted scalars (keeps ON as a string)."""


class _SafeDumper(yaml.SafeDumper):
    pass


def _represent_quoted(dumper: yaml.Dumper, data: _Quoted) -> Any:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="'")


_SafeDumper.add_representer(_Quoted, _represent_quoted)


def quote_for_yaml(value: str) -> str | _Quoted:
    if value.casefold() in _YAML_BOOLISH or (len(value) <= 2 and value.isupper()):
        return _Quoted(value)
    return value


def dump_search_yaml(data: dict[str, Any]) -> str:
    """Dump search config with province codes safely quoted."""
    payload = dict(data)
    loc = dict(payload.get("location") or {})
    if "provinces" in loc:
        loc["provinces"] = [quote_for_yaml(str(p)) for p in normalize_province_list(loc.get("provinces"))]
    if "cities" in loc:
        loc["cities"] = [str(c) for c in (loc.get("cities") or []) if c is not None and not isinstance(c, bool)]
    payload["location"] = loc
    return yaml.dump(payload, Dumper=_SafeDumper, sort_keys=False, allow_unicode=True)


def dump_profile_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _parse_csv_numbers(raw: str, n: int) -> list[int]:
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= n:
            out.append(int(part))
    return out


def _parse_skills(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def collect_setup_answers(
    *,
    non_interactive: bool,
    tracks: list[str] | None = None,
    modes: list[str] | None = None,
    province: str | None = None,
    city: str | None = None,
    salary_cad: int | None = None,
    skills: list[str] | None = None,
    years: int | None = None,
    name: str | None = None,
    seniority_include: list[str] | None = None,
) -> dict[str, Any]:
    """Return normalized setup answers from flags or interactive prompts."""
    track_ids = list(DEFAULT_TRACK_ALIASES.keys())

    if non_interactive:
        selected_tracks = list(tracks) if tracks else [
            "software_engineering",
            "ai_engineering",
            "data_engineering",
            "forward_deployed",
        ]
        invalid = [t for t in selected_tracks if t not in DEFAULT_TRACK_ALIASES]
        if invalid:
            raise ValueError(f"unknown tracks: {invalid}; choose from {track_ids}")
        chosen_modes = list(modes) if modes else ["remote_canada"]
        prov = (province or "ON").upper() if province else "ON"
        if len(prov) > 2:
            # full name → code if known
            for code, label in _PROVINCE_CHOICES:
                if label.casefold() == prov.casefold() or code == prov.upper():
                    prov = code
                    break
        return {
            "country": "Canada",
            "province": prov,
            "city": city or "Toronto",
            "modes": chosen_modes,
            "tracks": selected_tracks,
            "salary_cad": int(salary_cad) if salary_cad is not None else 120000,
            "skills": list(skills or []),
            "years": int(years) if years is not None else None,
            "name": name or "",
            "seniority_include": seniority_include
            or ["mid", "senior", "staff", "principal", "lead"],
        }

    print("GitHired setup — Canadian engineering job discovery")
    print("Country is fixed to Canada for this release.\n")

    print("Province (number, Enter for Ontario):")
    for i, (code, label) in enumerate(_PROVINCE_CHOICES, 1):
        print(f"  {i}. {label} ({code})")
    raw = input("> ").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(_PROVINCE_CHOICES):
        prov = _PROVINCE_CHOICES[int(raw) - 1][0]
    else:
        prov = "ON"

    city_in = input("City (Enter for Toronto): ").strip() or "Toronto"

    print("\nWork preference (comma-separated numbers, Enter for remote Canada + hybrid):")
    for i, (mid, help_text) in enumerate(_MODE_HELP, 1):
        print(f"  {i}. {mid} — {help_text}")
    raw_m = input("> ").strip()
    if not raw_m:
        chosen_modes = ["remote_canada", "hybrid"]
    else:
        idxs = _parse_csv_numbers(raw_m, len(_MODE_HELP))
        chosen_modes = [_MODE_HELP[i - 1][0] for i in idxs] or ["remote_canada"]

    print("\nEngineering tracks (comma-separated numbers, Enter for software/AI/data/FDE):")
    for i, tid in enumerate(track_ids, 1):
        label = TRACK_LABELS.get(tid, tid)
        print(f"  {i}. {label} [{tid}]")
    raw_t = input("> ").strip()
    if not raw_t:
        selected_tracks = [
            "software_engineering",
            "ai_engineering",
            "data_engineering",
            "forward_deployed",
        ]
    else:
        idxs = _parse_csv_numbers(raw_t, len(track_ids))
        selected_tracks = [track_ids[i - 1] for i in idxs] or track_ids[:]

    print("\nSeniority include (comma-separated: mid,senior,staff,principal,lead — Enter for mid+):")
    raw_s = input("> ").strip()
    if raw_s:
        sen = [x.strip().casefold() for x in raw_s.split(",") if x.strip()]
    else:
        sen = ["mid", "senior", "staff", "principal", "lead"]

    raw_sal = input("Minimum salary CAD (Enter for 120000): ").strip()
    if raw_sal:
        try:
            salary = int(raw_sal.replace(",", "").replace("$", ""))
        except ValueError as exc:
            raise ValueError("salary must be an integer CAD amount") from exc
    else:
        salary = 120000
    if salary < 0 or salary > 2_000_000:
        raise ValueError("salary out of expected range (0–2000000 CAD)")

    name_in = input("Your name (optional): ").strip()
    raw_years = input("Years of experience (optional integer): ").strip()
    years_val = None
    if raw_years:
        years_val = int(raw_years)
        if years_val < 0 or years_val > 60:
            raise ValueError("years of experience out of range")

    print("\nTechnical skills (comma-separated, e.g. Python, SQL, Spark):")
    skills_in = _parse_skills(input("> ").strip())

    return {
        "country": "Canada",
        "province": prov,
        "city": city_in,
        "modes": chosen_modes,
        "tracks": selected_tracks,
        "salary_cad": salary,
        "skills": skills_in,
        "years": years_val,
        "name": name_in,
        "seniority_include": sen,
    }


def apply_answers_to_search(data: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    out["tracks"] = list(answers["tracks"])
    loc = dict(out.get("location") or {})
    loc["modes"] = list(answers["modes"])
    # Keep full province name + quoted code for matching + human readability
    code = str(answers["province"]).upper()
    label = next((lab for c, lab in _PROVINCE_CHOICES if c == code), code)
    loc["provinces"] = [label, code]
    loc["cities"] = [answers["city"]]
    # Preserve broader Canadian city defaults as secondary preferred list under preferred_cities
    existing_cities = [str(c) for c in (data.get("location") or {}).get("cities") or [] if c]
    if answers["city"] not in existing_cities:
        loc["cities"] = [answers["city"], *[c for c in existing_cities if c != answers["city"]]]
    out["location"] = loc
    salary = dict(out.get("salary") or {})
    floors = dict(salary.get("floors") or {})
    floors["CAD"] = int(answers["salary_cad"])
    floors.setdefault("USD", 90000)
    salary["floors"] = floors
    salary.setdefault("reject_missing", False)
    out["salary"] = salary
    sen = dict(out.get("seniority") or {})
    if not isinstance(sen, dict):
        sen = {}
    include = [str(s).casefold() for s in answers["seniority_include"]]
    sen["include"] = include
    exclude = [str(s).casefold() for s in (sen.get("exclude") or [
        "intern", "coop", "student", "new_grad", "junior",
    ])]
    # Never exclude a band the user explicitly included (e.g. junior profiles).
    exclude = [e for e in exclude if e not in include]
    # Junior-focused profiles should hard-exclude senior+ unless included.
    if "junior" in include and "senior" not in include:
        for band in ("senior", "staff", "principal", "lead"):
            if band not in include and band not in exclude:
                exclude.append(band)
    sen["exclude"] = exclude
    out["seniority"] = sen
    return out


def apply_answers_to_profile(data: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    identity = dict(out.get("identity") or {})
    if answers.get("name"):
        identity["name"] = answers["name"]
    identity["location"] = f"{answers['city']}, {answers['province']}, Canada"
    identity["work_authorization"] = "Canada"
    out["identity"] = identity
    skills = dict(out.get("skills") or {})
    if answers.get("skills"):
        skills["primary"] = list(answers["skills"])
        skills.setdefault("secondary", [])
        skills.setdefault("domain", [])
    out["skills"] = skills
    exp = dict(out.get("experience") or {})
    if answers.get("years") is not None:
        exp["years"] = int(answers["years"])
    out["experience"] = exp
    return out


def validate_search_config(search: dict[str, Any]) -> list[str]:
    """Return doctor issues for search.yaml."""
    issues: list[str] = []
    tracks = search.get("tracks") or []
    if not isinstance(tracks, list) or not tracks:
        issues.append("search.tracks missing or empty")
    else:
        for t in tracks:
            if t not in DEFAULT_TRACK_ALIASES:
                issues.append(f"unsupported track: {t}")
    loc = search.get("location") or {}
    if not isinstance(loc, dict):
        issues.append("search.location must be a mapping")
    else:
        provinces = loc.get("provinces")
        if provinces is not None:
            if not isinstance(provinces, list):
                issues.append("search.location.provinces must be a list")
            else:
                for p in provinces:
                    if isinstance(p, bool):
                        issues.append(
                            "search.location.provinces contains a boolean "
                            "(quote Ontario as 'ON' in YAML — unquoted ON becomes true)"
                        )
                        break
        cities = loc.get("cities")
        if cities is not None and not isinstance(cities, list):
            issues.append("search.location.cities must be a list")
        modes = loc.get("modes")
        if modes is not None and not isinstance(modes, list):
            issues.append("search.location.modes must be a list")
    salary = search.get("salary") or {}
    floors = (salary.get("floors") if isinstance(salary, dict) else None) or {}
    if not isinstance(floors, dict):
        issues.append("search.salary.floors must be a mapping")
    else:
        for cur, val in floors.items():
            try:
                num = float(val)
            except (TypeError, ValueError):
                issues.append(f"search.salary.floors.{cur} must be a number (got {val!r})")
                continue
            if num < 0 or num > 2_000_000:
                issues.append(f"search.salary.floors.{cur}={num} outside expected range")
    return issues


def validate_profile_config(profile: dict[str, Any]) -> list[str]:
    from jobseek.profile_util import profile_warnings

    return profile_warnings(profile)
