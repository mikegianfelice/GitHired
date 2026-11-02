"""Classify why a scored job is geographically UNCERTAIN (not inventing certainty)."""

from __future__ import annotations

from typing import Any

from jobseek.shortlist import parse_hard_filter


def classify_uncertainty(
    row: dict[str, Any],
    *,
    hard_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a structured uncertainty diagnosis for CLI / digests.

    Categories:
      - missing_incomplete_description
      - geographic_ambiguity
      - remote_eligibility_ambiguity
      - province_or_city_restriction
      - us_primary_without_canada_evidence
      - apply_url
      - other
    """
    hf = hard_filter if hard_filter is not None else parse_hard_filter(row)
    elig = str(hf.get("eligibility") or "").upper()
    if elig != "UNCERTAIN":
        return {
            "category": "not_uncertain",
            "summary": f"eligibility={elig or 'n/a'}",
            "enrichable": False,
            "reasons": list(hf.get("reasons") or []),
        }

    reasons = [str(r) for r in (hf.get("reasons") or [])]
    blob = " | ".join(reasons).casefold()
    loc = str(row.get("location_raw") or "").casefold()
    complete = bool(int(row.get("description_complete") or 0))
    dlen = len(str(row.get("description") or ""))

    category = "other"
    if not complete or dlen < 120:
        category = "missing_incomplete_description"
    elif "us-primary remote without explicit canadian" in blob:
        category = "us_primary_without_canada_evidence"
    elif any(
        x in blob
        for x in (
            "hub-remote",
            "city match alone",
            "off-city",
            "province",
            "candidate city",
        )
    ):
        category = "province_or_city_restriction"
    elif any(
        x in blob
        for x in (
            "work arrangement not evidenced",
            "remote role; canada eligibility not evidenced",
            "north america",
            "namer",
            "work-from-anywhere",
        )
    ):
        category = "remote_eligibility_ambiguity"
    elif any(
        x in blob
        for x in (
            "location/canada eligibility not evidenced",
            "location not evidenced",
            "unknown",
        )
    ) or not loc.strip():
        category = "geographic_ambiguity"
    elif "application url" in blob or "affiliate" in blob:
        category = "apply_url"

    # Enrichment can help when the listing lacks a body or is a multi-location stub.
    multi_stub = bool(__import__("re").match(r"^\d+\s+locations?$", loc.strip()))
    enrichable = (not complete or multi_stub) and (
        hf.get("title_match") is True
        or str(hf.get("relevance") or "").upper() == "MATCH"
        or category == "missing_incomplete_description"
    )
    # Already-complete US-primary postings will not become ELIGIBLE via re-fetch alone.
    if category == "us_primary_without_canada_evidence" and complete:
        enrichable = False

    summaries = {
        "missing_incomplete_description": (
            "Full job description is missing or too short to verify Canada eligibility."
        ),
        "geographic_ambiguity": (
            "Location text does not clearly evidence Canadian eligibility."
        ),
        "remote_eligibility_ambiguity": (
            "Remote/hybrid arrangement is ambiguous for a Canadian candidate."
        ),
        "province_or_city_restriction": (
            "City/province evidence does not match this candidate's location policy."
        ),
        "us_primary_without_canada_evidence": (
            "US-primary remote posting without explicit Canadian eligibility."
        ),
        "apply_url": "Application URL is not confirmed-actionable (e.g. affiliate).",
        "other": "Hard filters left geographic eligibility unverified.",
    }
    next_action = (
        "Run `githired enrich` then `githired rank` — description may resolve geography."
        if enrichable
        else (
            "Enrichment is unlikely to help; Canada eligibility is not evidenced in the posting."
            if category == "us_primary_without_canada_evidence"
            else "Review the posting manually or broaden location modes if appropriate."
        )
    )
    return {
        "category": category,
        "summary": summaries.get(category, summaries["other"]),
        "enrichable": enrichable,
        "next_action": next_action,
        "reasons": reasons,
    }


def uncertainty_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        cat = classify_uncertainty(row)["category"]
        counts[cat] = counts.get(cat, 0) + 1
    return counts
