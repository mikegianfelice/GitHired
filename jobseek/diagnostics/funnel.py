from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from jobseek.filters.apply_url import select_actionable_apply_url
from jobseek.filters.hard import apply_hard_filters
from jobseek.filters.tracks import match_track
from jobseek.public_shortlist.export import PUBLIC_SEARCH
from jobseek.showcase.top_paying import is_job_specific_apply_url, is_valid_apply_url, parse_iso_date


@dataclass
class GateDrop:
    name: str
    count: int
    samples: List[Dict[str, Any]]


def _sample(rows: List[dict[str, Any]], k: int = 30) -> List[dict[str, Any]]:
    if not rows:
        return []
    if len(rows) <= k:
        return rows
    return random.sample(rows, k)


def build_funnel(
    jobs: List[dict[str, Any]],
    *,
    max_age_days: int = 21,
    search_cfg: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute gate-by-gate dropoff and sample removed rows per gate."""
    cfg = search_cfg or PUBLIC_SEARCH
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(0, int(max_age_days)))

    totals = {"raw": len(jobs)}

    stages: Dict[str, List[dict[str, Any]]] = {}
    removed: Dict[str, List[dict[str, Any]]] = defaultdict(list)

    current = list(jobs)
    # removed_at filter
    keep = []
    for j in current:
        if j.get("removed_at"):
            removed["removed_at"].append(j)
        else:
            keep.append(j)
    stages["after_removed"] = keep
    current = keep

    # title/company presence
    keep = []
    for j in current:
        title = (j.get("title") or "").strip()
        company = (j.get("company") or "").strip()
        if title and company:
            keep.append(j)
        else:
            removed["missing_title_or_company"].append(j)
    stages["after_title_company"] = keep
    current = keep

    # completeness
    keep = []
    for j in current:
        if int(j.get("description_complete") or 0):
            keep.append(j)
        else:
            removed["incomplete_description"].append(j)
    stages["after_complete"] = keep
    current = keep

    # track match
    keep = []
    for j in current:
        if match_track(j.get("title") or "", cfg).matched:
            keep.append(j)
        else:
            removed["off_track_title"].append(j)
    stages["after_track"] = keep
    current = keep

    # freshness
    keep = []
    for j in current:
        last_seen = parse_iso_date(j.get("last_seen") or j.get("posted_date"))
        if last_seen is None or last_seen < cutoff:
            removed["stale_older_than_cutoff"].append(j)
        else:
            keep.append(j)
    stages["after_freshness"] = keep
    current = keep

    # apply_url gate
    keep = []
    for j in current:
        apply_url, verdict = select_actionable_apply_url(primary=j.get("apply_url") or j.get("url"), fallbacks=[j.get("url")])
        if not apply_url or not verdict.actionable or verdict.kind != "direct":
            removed["apply_url_unactionable"].append(j)
            continue
        if not is_valid_apply_url(apply_url) or not is_job_specific_apply_url(apply_url):
            removed["apply_url_invalid_or_generic"].append(j)
            continue
        j["_apply_url_selected"] = apply_url
        keep.append(j)
    stages["after_apply_url"] = keep
    current = keep

    # hard filters
    keep = []
    for j in current:
        hf = apply_hard_filters(j, cfg)
        if hf.verdict != "PASS" or hf.eligibility != "ELIGIBLE" or hf.relevance == "NO_MATCH" or not hf.title_match:
            removed["hard_filters"].append(j)
        else:
            keep.append(j)
    stages["after_hard"] = keep
    current = keep

    # Final shortlist before dedupe
    finals = current

    # Dedupe on apply_url for API parity
    by_apply = {}
    for j in finals:
        url = j.get("_apply_url_selected") or j.get("apply_url") or j.get("url")
        key = (url or "").split("?")[0]
        if not key:
            continue
        if key not in by_apply:
            by_apply[key] = j
    deduped = list(by_apply.values())

    # Per-gate totals
    drops = []
    baseline = totals["raw"]
    cursor = baseline
    for gate in (
        "removed_at",
        "missing_title_or_company",
        "incomplete_description",
        "off_track_title",
        "stale_older_than_cutoff",
        "apply_url_unactionable",
        "apply_url_invalid_or_generic",
        "hard_filters",
    ):
        c = len(removed.get(gate) or [])
        drops.append(GateDrop(gate, c, _sample(removed.get(gate) or [], 30)).__dict__)
        cursor -= c
    totals.update(
        {
            "after_removed": len(stages["after_removed"]),
            "after_title_company": len(stages["after_title_company"]),
            "after_complete": len(stages["after_complete"]),
            "after_track": len(stages["after_track"]),
            "after_freshness": len(stages["after_freshness"]),
            "after_apply_url": len(stages["after_apply_url"]),
            "after_hard": len(stages["after_hard"]),
            "final_before_dedupe": len(finals),
            "final_after_dedupe": len(deduped),
        }
    )

    # Canada-eligible removed breakdown by company and gate
    ce_removed_by_gate_company: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    ce_set = []
    for j in jobs:
        hf = apply_hard_filters(j, cfg)
        if hf.verdict == "PASS" and hf.eligibility == "ELIGIBLE" and hf.relevance != "NO_MATCH" and hf.title_match:
            ce_set.append(j)
    ce_ids = set(id(j) for j in ce_set)
    passed_ids = set(id(j) for j in finals)
    removed_ce = [j for j in ce_set if id(j) not in passed_ids]
    for j in removed_ce:
        company = (j.get("company") or "").strip() or "(unknown)"
        # Find which gate removed it (first matching)
        for gate in (
            "incomplete_description",
            "stale_older_than_cutoff",
            "apply_url_unactionable",
            "apply_url_invalid_or_generic",
        ):
            if j in (removed.get(gate) or []):
                ce_removed_by_gate_company[gate][company] += 1
                break

    return {
        "totals": totals,
        "drops": drops,
        "canada_eligible_removed_by_gate_company": {g: dict(Counter(comp).items()) for g, comp in ce_removed_by_gate_company.items()},
        "samples_per_gate": {g: _sample(v, 30) for g, v in removed.items()},
    }

