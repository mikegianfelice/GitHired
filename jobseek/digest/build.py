"""Build daily top-N digests from scored jobs."""

from __future__ import annotations

import json
from typing import Any

from jobseek.config_loader import load_search
from jobseek.db.store import Database


def build_digest(
    db: Database,
    *,
    since: str | None = None,
    eligibility: str = "ELIGIBLE",
) -> dict[str, Any]:
    search = load_search()
    digest_cfg = search.get("digest") or {}
    top_n = int(digest_cfg.get("top_n") or 10)
    min_score = float(digest_cfg.get("min_score") or 60)
    uncertain_n = int(digest_cfg.get("uncertain_top_n") or 15)
    since = since if since is not None else db.last_digest_at()
    jobs = db.top_new_scored(
        limit=top_n,
        min_score=min_score,
        since=since,
        eligibility=eligibility,
    )
    uncertain_jobs = db.top_new_scored(
        limit=uncertain_n,
        min_score=0,
        since=None,
        eligibility="UNCERTAIN",
    )
    counts = db.count_scored_by_eligibility(min_score=None)
    uncertain = int(counts.get("UNCERTAIN") or 0)
    return {
        "count": len(jobs),
        "min_score": min_score,
        "since": since,
        "eligibility": eligibility,
        "confirmed_matches": len(jobs),
        "uncertain_opportunities": uncertain,
        "uncertain_shortlist": uncertain_jobs,
        "eligibility_counts": counts,
        "jobs": jobs,
        "next": (
            f"githired jobs --eligibility uncertain"
            if uncertain
            else None
        ),
    }


def render_digest_markdown(digest: dict[str, Any]) -> str:
    confirmed = int(digest.get("confirmed_matches") or digest.get("count") or 0)
    uncertain = int(digest.get("uncertain_opportunities") or 0)
    lines = [
        "# Daily job digest",
        "",
        f"Found {confirmed} confirmed match"
        + ("es" if confirmed != 1 else "")
        + (
            f" since {digest['since']}"
            if digest.get("since")
            else " (geographically compatible, current scores)"
        )
        + ".",
        "",
    ]
    if uncertain:
        cmd = digest.get("next") or "githired jobs --eligibility uncertain"
        lines.append(
            f"There are {uncertain} additional opportunities with unverified "
            f"Canadian eligibility. Run `{cmd}` to review them."
        )
        lines.append("")
    if not digest.get("jobs"):
        lines.append("_No confirmed high-ranked opportunities._")
        if uncertain:
            lines.append(
                f"_Use `{digest.get('next') or 'githired jobs --eligibility uncertain'}` "
                "to inspect uncertain roles retained in the database._"
            )
        return "\n".join(lines)

    for idx, job in enumerate(digest["jobs"], 1):
        strengths = job.get("strengths_json")
        gaps = job.get("gaps_json")
        try:
            strengths_l = json.loads(strengths) if isinstance(strengths, str) else strengths or []
        except json.JSONDecodeError:
            strengths_l = []
        try:
            gaps_l = json.loads(gaps) if isinstance(gaps, str) else gaps or []
        except json.JSONDecodeError:
            gaps_l = []
        kind = job.get("score_kind") or "deterministic"
        model = job.get("model") or kind
        elig = None
        hf = job.get("hard_filter_json")
        if isinstance(hf, str):
            try:
                elig = (json.loads(hf) or {}).get("eligibility")
            except json.JSONDecodeError:
                elig = None
        elif isinstance(hf, dict):
            elig = hf.get("eligibility")
        lines.append(
            f"## {idx}. {job.get('title')} @ {job.get('company')} — {job.get('overall')}/100"
        )
        lines.append(f"- Score: {kind} ({model})")
        if elig:
            lines.append(f"- Canada eligibility: {elig}")
        lines.append(f"- Location: {job.get('location_raw') or 'n/a'}")
        lines.append(f"- URL: {job.get('url')}")
        if strengths_l:
            lines.append("- Strengths: " + "; ".join(strengths_l))
        if gaps_l:
            lines.append("- Gaps: " + "; ".join(gaps_l))
        evidence = job.get("evidence_json")
        try:
            evidence_l = json.loads(evidence) if isinstance(evidence, str) else evidence or []
        except json.JSONDecodeError:
            evidence_l = []
        if evidence_l:
            lines.append("- Evidence: " + "; ".join(str(x) for x in evidence_l[:4]))
        lines.append("")
    uncertain_jobs = digest.get("uncertain_shortlist") or []
    if uncertain_jobs:
        lines.append("---")
        lines.append("")
        lines.append(
            f"## Top uncertain opportunities ({len(uncertain_jobs)} shown; "
            "not promoted to confirmed)"
        )
        lines.append("")
        lines.append(
            "_These roles scored well on fit but lack clear Canada-eligibility "
            "evidence. Review manually — they are never auto-confirmed._"
        )
        lines.append("")
        for idx, job in enumerate(uncertain_jobs, 1):
            why = _uncertain_why(job)
            lines.append(
                f"### U{idx}. {job.get('title')} @ {job.get('company')} — "
                f"{job.get('overall')}/100"
            )
            lines.append(f"- Location: {job.get('location_raw') or 'n/a'}")
            lines.append(f"- Why uncertain: {why}")
            lines.append(f"- URL: {job.get('url')}")
            lines.append("")

    lines.append(
        "_Resume generation and application submission require explicit approval "
        "(`githired prepare <id>` then `/apply`)._"
    )
    return "\n".join(lines)


def _uncertain_why(job: dict[str, Any]) -> str:
    """Explain why a listing is UNCERTAIN (missing evidence vs restriction)."""
    hf = job.get("hard_filter_json")
    reasons: list[str] = []
    if isinstance(hf, str):
        try:
            data = json.loads(hf) or {}
            reasons = list(data.get("reasons") or [])
        except json.JSONDecodeError:
            reasons = []
    elif isinstance(hf, dict):
        reasons = list(hf.get("reasons") or [])
    evidence = job.get("evidence_json")
    try:
        ev = json.loads(evidence) if isinstance(evidence, str) else evidence or []
    except json.JSONDecodeError:
        ev = []
    for item in ev:
        s = str(item)
        if s.startswith("uncertain_reason:"):
            return s.split(":", 1)[1].strip()
    for r in reasons:
        low = r.casefold()
        if "uncertain" in low or "not evidenced" in low or "ambiguous" in low:
            return r
        if "missing" in low and ("location" in low or "canada" in low):
            return f"Missing location evidence: {r}"
        if "restrict" in low or "us-only" in low or "united states" in low:
            return f"Geographic restriction signal (still uncertain): {r}"
    loc = job.get("location_raw") or ""
    if not loc.strip():
        return "Missing location evidence in posting"
    return "Canada eligibility not clearly evidenced from posting text"
