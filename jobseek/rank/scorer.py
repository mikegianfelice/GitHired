"""LLM-backed structured job scoring with hard filters first."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

from jobseek.config_loader import Settings
from jobseek.filters.hard import apply_hard_filters
from jobseek.models import HardFilterResult, ScoreResult

# Reuse upstream weights
_TOOLS = Path(__file__).resolve().parent.parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
from rank_state import WEIGHTS  # noqa: E402

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


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


def _heuristic_score(job: dict[str, Any], hard: HardFilterResult) -> ScoreResult:
    """Offline fallback when no LLM key is configured (tests / dry runs)."""
    base = 55.0
    if hard.verdict == "PASS":
        base = 70.0
    elif hard.verdict == "FAIL":
        base = 25.0
    desc = (job.get("description") or "").casefold()
    bumps = 0
    for token in ("python", "llm", "machine learning", "data engineer", "pytorch", "rag"):
        if token in desc:
            bumps += 3
    overall = max(0, min(100, base + bumps))
    scores = {
        "technical": overall,
        "experience": max(0, overall - 5),
        "behavioral": 60.0,
        "career": overall,
    }
    return ScoreResult(
        overall=_weighted_overall(scores),
        scores=scores,
        strengths=["Heuristic score — configure ANTHROPIC_API_KEY or OPENAI_API_KEY for LLM scoring"],
        gaps=hard.reasons[:3],
        salary_alignment="unknown without LLM",
        rejection_reasons=hard.reasons if hard.verdict == "FAIL" else [],
        evidence=hard.evidence,
        model="heuristic",
        hard_filter=hard,
    )


def _call_anthropic(prompt: str, settings: Settings) -> tuple[dict[str, Any], str]:
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic package not installed; pip install 'jobseek[llm-anthropic]'") from exc
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
        raise RuntimeError("openai package not installed; pip install 'jobseek[llm-openai]'") from exc
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


def score_job(
    job: dict[str, Any],
    *,
    search_cfg: dict[str, Any],
    profile: dict[str, Any],
    settings: Settings | None = None,
    llm_caller: Callable[[str], tuple[dict[str, Any], str]] | None = None,
    skip_fail: bool = True,
) -> ScoreResult:
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
            model="hard_filter",
            hard_filter=hard,
        )

    if llm_caller is not None:
        data, model = llm_caller(_build_prompt(job, profile, hard))
    else:
        provider = settings.llm_provider
        use_anthropic = provider == "anthropic" and settings.anthropic_api_key
        use_openai = provider in ("openai", "openai_compatible") and settings.openai_api_key
        # Prefer configured provider; fall back across keys
        if not use_anthropic and not use_openai:
            if settings.anthropic_api_key:
                use_anthropic = True
            elif settings.openai_api_key:
                use_openai = True
            else:
                # Allow explicit heuristic mode for CI
                if os.environ.get("JOBSEEK_ALLOW_HEURISTIC", "1") == "1":
                    return _heuristic_score(job, hard)
                raise RuntimeError("No LLM API key configured")
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
        hard_filter=hard,
    )
