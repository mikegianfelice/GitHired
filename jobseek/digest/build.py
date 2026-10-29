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
    since = since if since is not None else db.last_digest_at()
    jobs = db.top_new_scored(
        limit=top_n,
        min_score=min_score,
        since=since,
        eligibility=eligibility,
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
    lines.append(
        "_Resume generation and application submission require explicit approval "
        "(`githired prepare <id>` then `/apply`)._"
    )
    return "\n".join(lines)
