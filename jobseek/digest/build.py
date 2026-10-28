"""Build daily top-N digests from scored jobs."""

from __future__ import annotations

import json
from typing import Any

from jobseek.config_loader import load_search
from jobseek.db.store import Database


def build_digest(db: Database, *, since: str | None = None) -> dict[str, Any]:
    search = load_search()
    digest_cfg = search.get("digest") or {}
    top_n = int(digest_cfg.get("top_n") or 10)
    min_score = float(digest_cfg.get("min_score") or 60)
    since = since if since is not None else db.last_digest_at()
    jobs = db.top_new_scored(limit=top_n, min_score=min_score, since=since)
    return {
        "count": len(jobs),
        "min_score": min_score,
        "since": since,
        "jobs": jobs,
    }


def render_digest_markdown(digest: dict[str, Any]) -> str:
    lines = [
        "# Daily job digest",
        "",
        f"Top {digest.get('count', 0)} opportunities"
        + (f" since {digest['since']}" if digest.get("since") else " (all unscored windows)"),
        "",
    ]
    if not digest.get("jobs"):
        lines.append("_No new high-ranked opportunities._")
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
        lines.append(
            f"## {idx}. {job.get('title')} @ {job.get('company')} — {job.get('overall')}/100"
        )
        lines.append(f"- Score: {kind} ({model})")
        lines.append(f"- Location: {job.get('location_raw') or 'n/a'}")
        lines.append(f"- URL: {job.get('url')}")
        if strengths_l:
            lines.append("- Strengths: " + "; ".join(strengths_l))
        if gaps_l:
            lines.append("- Gaps: " + "; ".join(gaps_l))
        lines.append("")
    lines.append(
        "_Resume generation and application submission require explicit approval "
        "(`githired prepare <id>` then `/apply`)._"
    )
    return "\n".join(lines)
