"""Time-to-first-N confirmed match helpers (TTF10)."""

from __future__ import annotations

from typing import Any

from jobseek.db.store import Database


def count_confirmed_matches(
    db: Database,
    *,
    min_score: float | None = None,
) -> int:
    """Count ELIGIBLE + complete + deterministic scores (confirmed shortlist)."""
    rows = db.list_jobs(
        min_score=min_score,
        limit=10_000,
        score_kind="deterministic",
        eligibility="ELIGIBLE",
        require_complete=True,
    )
    return len(rows)


def ttf_snapshot(
    db: Database,
    *,
    t0: float,
    now: float,
    milestones: dict[str, float | None],
    target: int = 10,
    min_score: float | None = None,
) -> dict[str, Any]:
    """Update milestone timestamps when confirmed-match counts cross 1/5/10."""
    n = count_confirmed_matches(db, min_score=min_score)
    elapsed = round(now - t0, 2)
    for threshold, key in ((1, "ttf1_s"), (5, "ttf5_s"), (10, "ttf10_s")):
        if n >= threshold and milestones.get(key) is None:
            milestones[key] = elapsed
    out = {
        "confirmed_matches": n,
        "target": target,
        "elapsed_s": elapsed,
        **{k: milestones.get(k) for k in ("ttf1_s", "ttf5_s", "ttf10_s")},
    }
    if n < target:
        out["note"] = f"Only {n} confirmed matches found."
    return out
