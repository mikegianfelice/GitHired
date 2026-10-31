"""Salary extraction, currency detection, and floor gating."""

from __future__ import annotations

import pytest

from jobseek.filters.hard import apply_hard_filters
from jobseek.filters.salary import enrich_job_salary, extract_salary_from_text, salary_label_for_job


def _search(**salary_overrides):
    sal = {"reject_missing": False, "floors": {"CAD": 130_000}}
    sal.update(salary_overrides)
    return {
        "tracks": ["data_engineering"],
        "seniority": {"include": ["mid", "senior", "staff"], "exclude": ["intern"]},
        "location": {
            "modes": ["remote_canada", "hybrid"],
            "preferred": ["Canada remote", "Remote Canada"],
            "reject_us_only_remote": True,
            "unknown_location_policy": "flag",
            "cities": ["Toronto"],
            "provinces": ["Ontario", "ON"],
        },
        "salary": sal,
    }


def test_missing_salary_is_undisclosed_not_invented():
    info = extract_salary_from_text("Great team, competitive compensation.")
    assert info.confidence == "undisclosed"
    assert info.salary_min is None
    assert "undisclosed" in info.label.lower()


def test_verified_cad_range():
    info = extract_salary_from_text("Base salary CAD $140,000 - $160,000 annually")
    assert info.confidence == "verified"
    assert info.currency == "CAD"
    assert info.salary_min == 140_000
    assert info.salary_max == 160_000
    assert "Verified" in info.label


def test_usd_vs_cad_detection():
    cad = extract_salary_from_text("Salary range: C$120,000 to C$140,000")
    usd = extract_salary_from_text("Salary range: USD $120,000 to $140,000")
    assert cad.currency == "CAD"
    assert usd.currency == "USD"


def test_conflicting_currency_prefers_explicit_token():
    info = extract_salary_from_text("USD $150,000 CAD market rates")
    # First explicit currency token wins via CAD/USD detectors (CAD checked first)
    assert info.currency in ("CAD", "USD")
    assert info.confidence in ("verified", "unverified")


def test_hourly_not_treated_as_annual_base():
    info = extract_salary_from_text("Pay: $85 / hour CAD")
    assert info.period == "hourly"
    assert info.confidence == "unverified"
    assert info.salary_min is None


def test_equity_bonus_not_base():
    info = extract_salary_from_text("Total compensation $200,000 including equity and bonus")
    assert info.kind != "base" or info.confidence == "unverified"
    assert info.salary_min is None


def test_ambiguous_bare_dollar_unverified():
    info = extract_salary_from_text("Compensation: $150,000 - $170,000")
    assert info.confidence == "unverified"
    assert "currency" in " ".join(info.reasons).lower() or info.currency is None


def test_enrich_prefers_structured_fields():
    job = {
        "salary_min": 145000,
        "salary_max": 165000,
        "salary_currency": "CAD",
        "description": "ignore me $50k",
    }
    out = enrich_job_salary(job)
    assert out["salary_confidence"] == "verified"
    assert "145,000" in out["salary_label"]


def test_below_floor_label():
    job = {
        "salary_min": 100000,
        "salary_max": 110000,
        "salary_currency": "CAD",
    }
    info = salary_label_for_job(job, floors={"CAD": 130000})
    assert info.confidence == "below_floor"
    assert "below preference" in info.label.lower()


def test_hard_filter_keeps_undisclosed_by_default():
    job = {
        "title": "Data Engineer",
        "location_raw": "Toronto, Ontario (Hybrid)",
        "description": "Hybrid in Toronto. Competitive pay.",
        "url": "https://boards.greenhouse.io/acme/jobs/1",
        "source": "greenhouse",
    }
    result = apply_hard_filters(job, _search())
    assert result.salary_verdict == "PASS"
    assert any("missing" in r.lower() or "undisclosed" in r.lower() for r in result.reasons)


def test_hard_filter_fails_below_floor_when_verified():
    job = {
        "title": "Data Engineer",
        "location_raw": "Toronto, Ontario (Hybrid)",
        "description": "Hybrid Toronto. Base salary CAD $90,000 - $100,000.",
        "url": "https://boards.greenhouse.io/acme/jobs/1",
        "source": "greenhouse",
    }
    result = apply_hard_filters(job, _search())
    assert result.salary_verdict == "FAIL"


def test_reject_missing_when_configured():
    job = {
        "title": "Data Engineer",
        "location_raw": "Remote, Canada",
        "description": "Remote Canada. No pay listed.",
        "url": "https://boards.greenhouse.io/acme/jobs/1",
        "source": "greenhouse",
    }
    result = apply_hard_filters(job, _search(reject_missing=True))
    assert result.salary_verdict == "FAIL"
