"""Two-stage job scoring: deterministic (no API) then optional LLM."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable

from jobseek.config_loader import Settings
from jobseek.filters.hard import apply_hard_filters
from jobseek.filters.tracks import (
    DEFAULT_SENIORITY_INCLUDE,
    detect_seniority,
    match_track,
    title_matches_selected_tracks,
)
from jobseek.models import HardFilterResult, ScoreResult
from jobseek.profile_util import is_profile_complete_for_skills, profile_warnings
from jobseek.rank.weights import WEIGHTS

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")

# Bump when deterministic scoring / eligibility logic changes so stale rows re-rank.
SCORER_VERSION = "v2"
DETERMINISTIC_MODEL = f"deterministic/{SCORER_VERSION}"
HARD_FILTER_MODEL = f"hard_filter/{SCORER_VERSION}"
# A job is "current" for Stage-1 ranking if it has either model from this run.
STAGE1_MODELS = (DETERMINISTIC_MODEL, HARD_FILTER_MODEL)


def _rubric_from_profile(profile: dict[str, Any]) -> str:
    skills = profile.get("skills") or {}
    return json.dumps(
        {
            "primary_skills": skills.get("primary"),
            "secondary_skills": skills.get("secondary"),
            "domain": skills.get("domain"),
            "experience": profile.get("experience"),
            "behavioral": profile.get("behavioral"),
            "career_goals": profile.get("career_goals"),
            "deal_breakers": profile.get("deal_breakers"),
            "work_authorization": (profile.get("identity") or {}).get("work_authorization"),
            "languages": (profile.get("identity") or {}).get("languages"),
            "weights": WEIGHTS,
        },
        ensure_ascii=False,
        indent=2,
    )


def _build_prompt(job: dict[str, Any], profile: dict[str, Any], hard: HardFilterResult) -> str:
    return f"""You are scoring a job posting for a Canada-based engineering candidate.

RULES:
- Score ONLY from the job description and structured profile provided.
- Never invent qualifications the candidate does not list.
- Never infer Canadian hiring eligibility without quoting evidence from the posting.
- If Canada eligibility is not evidenced, say so in gaps / rejection_reasons.
- Return a single JSON object (no markdown) with keys:
  scores: {{technical, experience, behavioral, career}} each 0-100
  overall: 0-100 weighted using technical 0.30, experience 0.25, behavioral 0.15, career 0.30
  strengths: 1-3 short bullets grounded in the posting
  gaps: 1-3 honest gaps
  salary_alignment: short string
  rejection_reasons: list (empty if still recommendable)
  evidence: short quotes from the posting that support location/salary/fit claims

Hard filter result (deterministic, already applied):
{json.dumps(hard.to_dict(), ensure_ascii=False)}

Candidate profile rubric:
{_rubric_from_profile(profile)}

Job:
company: {job.get('company')}
title: {job.get('title')}
location: {job.get('location_raw')}
salary_raw: {job.get('salary_raw')}
url: {job.get('url')}

Description:
{(job.get('description') or '')[:12000]}
"""


def _parse_llm_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(text)
        if not match:
            raise
        return json.loads(match.group(0))


def _weighted_overall(scores: dict[str, float]) -> float:
    total = 0.0
    for key, weight in WEIGHTS.items():
        total += float(scores.get(key, 0)) * float(weight)
    return round(total)


def _skill_tokens(profile: dict[str, Any]) -> list[str]:
    skills = profile.get("skills") or {}
    tokens: list[str] = []
    for key in ("primary", "secondary", "domain"):
        val = skills.get(key) or []
        if isinstance(val, str):
            tokens.append(val)
        elif isinstance(val, list):
            tokens.extend(str(x) for x in val)
    exp = profile.get("experience") or {}
    for key in ("strong_domains", "adjacent_domains"):
        val = exp.get(key) or []
        if isinstance(val, list):
            tokens.extend(str(x) for x in val)
    return [t.strip() for t in tokens if t and str(t).strip()]


def _freshness_score(job: dict[str, Any], search_cfg: dict[str, Any]) -> tuple[float, str]:
    recency_days = int(search_cfg.get("recency_days") or 30)
    stamp = job.get("posted_date") or job.get("first_seen") or job.get("last_seen")
    if not stamp:
        return 50.0, "no verifiable posting date"
    try:
        raw = str(stamp).replace("Z", "+00:00")
        if "T" not in raw and len(raw) == 10:
            dt = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).days
    except ValueError:
        return 50.0, "unparseable posting date"
    if age <= 7:
        return 100.0, f"posted/seen {age}d ago"
    if age <= recency_days:
        return 75.0, f"posted/seen {age}d ago (within {recency_days}d)"
    if age <= recency_days * 2:
        return 45.0, f"posted/seen {age}d ago (stale)"
    return 20.0, f"posted/seen {age}d ago (very stale)"


def score_deterministic(
    job: dict[str, Any],
    *,
    search_cfg: dict[str, Any],
    profile: dict[str, Any],
    hard: HardFilterResult | None = None,
) -> ScoreResult:
    """Transparent Stage-1 score. Never labeled as AI-generated."""
    hard = hard or apply_hard_filters(job, search_cfg)
    if hard.verdict == "FAIL":
        return ScoreResult(
            overall=0,
            scores={
                "canada_eligibility": 0,
                "track_match": 0,
                "seniority": 0,
                "skills": 0,
                "location": 0,
                "salary": 0,
                "freshness": 0,
            },
            strengths=[],
            # Hard-filter reasons are rejections — never candidate skill gaps
            gaps=[],
            salary_alignment="n/a",
            rejection_reasons=hard.reasons,
            evidence=hard.evidence,
            model=HARD_FILTER_MODEL,
            score_kind="hard_filter",
            hard_filter=hard,
        )

    track = match_track(job.get("title") or "", search_cfg)
    elig = hard.eligibility or "UNCERTAIN"
    canada = {"ELIGIBLE": 100.0, "UNCERTAIN": 40.0, "INELIGIBLE": 0.0}.get(elig, 40.0)

    # Exact selected-track titles outrank adjacent / weak keyword noise.
    if track.matched and track.match_strength == "exact":
        track_score = 98.0
        track_note = f"exact track title: {track.matched_alias}"
    elif track.match_strength == "adjacent":
        track_score = 55.0
        track_note = f"adjacent family only: {track.primary_family}"
    else:
        track_score = 15.0
        track_note = "title outside selected tracks"

    seniority = detect_seniority(job.get("title") or "")
    sen_cfg = search_cfg.get("seniority")
    if isinstance(sen_cfg, dict):
        preferred = [str(s).casefold() for s in (sen_cfg.get("include") or DEFAULT_SENIORITY_INCLUDE)]
    elif isinstance(sen_cfg, list):
        preferred = [str(s).casefold() for s in sen_cfg] or list(DEFAULT_SENIORITY_INCLUDE)
    else:
        preferred = list(DEFAULT_SENIORITY_INCLUDE)
    if seniority and seniority.casefold() in preferred:
        seniority_score = 95.0
        sen_note = f"seniority {seniority} preferred"
    elif seniority is None:
        seniority_score = 75.0
        sen_note = "seniority unknown — not penalized harshly"
    else:
        seniority_score = 50.0
        sen_note = f"seniority {seniority} outside preferred {preferred}"

    desc = f"{job.get('title') or ''}\n{job.get('description') or ''}".casefold()
    tokens = _skill_tokens(profile)
    hits = [t for t in tokens if t.casefold() in desc]
    title_on_track = title_matches_selected_tracks(job.get("title") or "", search_cfg)
    if not is_profile_complete_for_skills(profile):
        skills_score = 50.0
        skills_note = "incomplete profile — skill score neutral (title/location still ranked)"
    elif not title_on_track:
        # Do not let generic keyword overlap rescue off-track roles into the top tier.
        skills_score = 25.0
        skills_note = "skills ignored for ranking — title outside selected tracks"
        hits = []
    else:
        ratio = len(hits) / max(len(tokens), 1)
        skills_score = round(min(100.0, 35.0 + ratio * 65.0), 1)
        skills_note = f"matched {len(hits)}/{len(tokens)} profile skill tokens"

    location_score = canada
    # Missing salary must not look like a strong positive signal.
    if hard.salary_verdict == "PASS" and any(
        "salary missing" in r.casefold() for r in hard.reasons
    ):
        salary_score = 50.0
        sal_note = "salary not disclosed — neutral"
    else:
        sal_map = {"PASS": 90.0, "FLAG": 55.0, "FAIL": 15.0}
        salary_score = sal_map.get(hard.salary_verdict, 50.0)
        sal_note = hard.salary_verdict
    freshness, fresh_note = _freshness_score(job, search_cfg)

    components = {
        "canada_eligibility": canada,
        "track_match": track_score,
        "seniority": seniority_score,
        "skills": skills_score,
        "location": location_score,
        "salary": salary_score,
        "freshness": freshness,
    }
    weights = {
        "canada_eligibility": 0.28,
        "track_match": 0.26,
        "seniority": 0.08,
        "skills": 0.16,
        "location": 0.08,
        "salary": 0.06,
        "freshness": 0.08,
    }
    overall = round(sum(components[k] * weights[k] for k in weights))
    # Confirmed Canada ranks above uncertain when otherwise comparable.
    if elig == "ELIGIBLE":
        overall = min(100, overall + 4)
    elif elig == "UNCERTAIN":
        overall = min(overall, 62)
        overall = max(0, overall - 15)

    strengths = []
    if track.matched and track.matched_alias:
        strengths.append(f"Track match: {track.matched_alias}")
    if elig == "ELIGIBLE" and hard.evidence:
        strengths.append(f"Canada eligibility evidence: {hard.evidence[0]}")
    if hits:
        strengths.append(f"Skill overlap: {', '.join(hits[:5])}")

    gaps: list[str] = []
    if title_on_track and tokens and not hits:
        gaps.append("no overlap with configured profile skills in posting text")
    elif title_on_track and tokens and len(hits) < max(1, len(tokens) // 3):
        gaps.append(f"limited skill overlap ({len(hits)}/{len(tokens)} tokens)")
    for w in profile_warnings(profile):
        if "placeholder" in w or "empty" in w:
            gaps.append("profile incomplete for skill matching")
            break

    evidence = list(hard.evidence)[:8] + [track_note, skills_note, sen_note, sal_note, fresh_note]
    if elig == "UNCERTAIN":
        evidence.append("eligibility=UNCERTAIN — ranking penalty applied; not auto-rejected")
    elif elig == "ELIGIBLE":
        evidence.append("eligibility=ELIGIBLE — ranking boost applied")

    return ScoreResult(
        overall=float(overall),
        scores=components,
        strengths=strengths[:5],
        gaps=gaps[:5],
        salary_alignment="; ".join(
            r for r in hard.reasons if "salary" in r.casefold()
        )
        or sal_note,
        rejection_reasons=[],
        evidence=evidence,
        model=DETERMINISTIC_MODEL,
        score_kind="deterministic",
        hard_filter=hard,
    )


def _call_anthropic(prompt: str, settings: Settings) -> tuple[dict[str, Any], str]:
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic package not installed; pip install 'githired[llm-anthropic]'") from exc
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in msg.content if hasattr(block, "text"))
    return _parse_llm_json(text), settings.anthropic_model


def _call_openai(prompt: str, settings: Settings) -> tuple[dict[str, Any], str]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package not installed; pip install 'githired[llm-openai]'") from exc
    kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    client = OpenAI(**kwargs)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    text = resp.choices[0].message.content or "{}"
    return _parse_llm_json(text), settings.openai_model


def score_llm(
    job: dict[str, Any],
    *,
    search_cfg: dict[str, Any],
    profile: dict[str, Any],
    settings: Settings,
    hard: HardFilterResult | None = None,
    llm_caller: Callable[[str], tuple[dict[str, Any], str]] | None = None,
) -> ScoreResult:
    hard = hard or apply_hard_filters(job, search_cfg)
    if llm_caller is not None:
        data, model = llm_caller(_build_prompt(job, profile, hard))
    else:
        provider = settings.llm_provider
        use_anthropic = provider == "anthropic" and settings.anthropic_api_key
        use_openai = provider in ("openai", "openai_compatible") and settings.openai_api_key
        if not use_anthropic and not use_openai:
            if settings.anthropic_api_key:
                use_anthropic = True
            elif settings.openai_api_key:
                use_openai = True
            else:
                raise RuntimeError("No LLM API key configured for stage-2 scoring")
        prompt = _build_prompt(job, profile, hard)
        if use_anthropic:
            data, model = _call_anthropic(prompt, settings)
        else:
            data, model = _call_openai(prompt, settings)

    scores = {
        "technical": float((data.get("scores") or {}).get("technical", 0)),
        "experience": float((data.get("scores") or {}).get("experience", 0)),
        "behavioral": float((data.get("scores") or {}).get("behavioral", 0)),
        "career": float((data.get("scores") or {}).get("career", 0)),
    }
    overall = data.get("overall")
    try:
        overall_f = float(overall) if overall is not None else _weighted_overall(scores)
    except (TypeError, ValueError):
        overall_f = _weighted_overall(scores)

    return ScoreResult(
        overall=overall_f,
        scores=scores,
        strengths=list(data.get("strengths") or [])[:5],
        gaps=list(data.get("gaps") or [])[:5],
        salary_alignment=str(data.get("salary_alignment") or ""),
        rejection_reasons=list(data.get("rejection_reasons") or []),
        evidence=list(data.get("evidence") or [])[:8],
        model=model,
        score_kind="llm",
        hard_filter=hard,
    )


def score_job(
    job: dict[str, Any],
    *,
    search_cfg: dict[str, Any],
    profile: dict[str, Any],
    settings: Settings | None = None,
    llm_caller: Callable[[str], tuple[dict[str, Any], str]] | None = None,
    skip_fail: bool = True,
    use_llm: bool | None = None,
) -> ScoreResult:
    """Score a job. Default is deterministic Stage 1; LLM only when requested."""
    settings = settings or Settings.from_env()
    hard = apply_hard_filters(job, search_cfg)

    if hard.verdict == "FAIL" and skip_fail:
        return ScoreResult(
            overall=0,
            scores={"technical": 0, "experience": 0, "behavioral": 0, "career": 0},
            strengths=[],
            gaps=hard.reasons,
            salary_alignment="n/a",
            rejection_reasons=hard.reasons,
            evidence=hard.evidence,
            model=HARD_FILTER_MODEL,
            score_kind="hard_filter",
            hard_filter=hard,
        )

    want_llm = use_llm if use_llm is not None else bool(settings.rank_llm)
    if want_llm or llm_caller is not None:
        try:
            return score_llm(
                job,
                search_cfg=search_cfg,
                profile=profile,
                settings=settings,
                hard=hard,
                llm_caller=llm_caller,
            )
        except RuntimeError:
            if os.environ.get("JOBSEEK_ALLOW_HEURISTIC", "1") == "1" and llm_caller is None:
                # Fall back to deterministic rather than inventing AI scores
                return score_deterministic(
                    job, search_cfg=search_cfg, profile=profile, hard=hard
                )
            raise

    return score_deterministic(job, search_cfg=search_cfg, profile=profile, hard=hard)
