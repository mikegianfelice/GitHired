"""Salary extraction and confidence labeling (never invent undisclosed pay)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_CURRENCY_CAD = re.compile(r"\b(?:CAD|C\$|CDN)\b", re.I)
_CURRENCY_USD = re.compile(r"\b(?:USD|US\$)\b", re.I)
_DOLLAR = re.compile(r"\$")

# Annual-looking ranges / singles (avoid matching years like 2024)
_RANGE = re.compile(
    r"(?P<a>\$?\s?\d{2,3}(?:,\d{3})?(?:k)?)\s*(?:-|–|—|to)\s*(?P<b>\$?\s?\d{2,3}(?:,\d{3})?(?:k)?)",
    re.I,
)
_SINGLE = re.compile(r"\$\s?(?P<a>\d{2,3}(?:,\d{3})?(?:k)?)\b", re.I)
_HOURLY = re.compile(
    r"\$\s?\d{1,3}(?:,\d{3})?(?:\.\d+)?\s*/\s*(?:hr|hour)\b|"
    r"\$\s?\d{1,3}(?:\.\d+)?\s+(?:per\s+)?hour\b|"
    r"\b\d{1,3}(?:\.\d+)?\s*(?:CAD|USD|C\$)?\s*/\s*(?:hr|hour)\b",
    re.I,
)
_EQUITY_BONUS = re.compile(
    r"\b(?:equity|RSU|stock\s+options?|bonus|OTE|on[\s-]?target\s+earnings|"
    r"total\s+compensation|total\s+comp|TCC)\b",
    re.I,
)
_BASE = re.compile(r"\b(?:base\s+salary|annual\s+(?:base\s+)?salary|salary\s+range)\b", re.I)

MIN_ANNUAL = 30_000.0
MAX_ANNUAL = 800_000.0


@dataclass(frozen=True)
class SalaryInfo:
    salary_min: float | None
    salary_max: float | None
    currency: str | None  # CAD | USD | None
    period: str  # annual | hourly | unknown
    kind: str  # base | total_comp | equity_bonus | undisclosed
    confidence: str  # verified | below_floor | undisclosed | unverified
    label: str
    raw: str
    reasons: list[str]


def _parse_amount(token: str) -> float | None:
    text = token.strip().lower().replace(",", "").replace("$", "").replace(" ", "")
    if not text:
        return None
    mult = 1.0
    if text.endswith("k"):
        mult = 1000.0
        text = text[:-1]
    try:
        return float(text) * mult
    except ValueError:
        return None


def _detect_currency(text: str, structured: str | None = None) -> str | None:
    blob = f"{structured or ''} {text}"
    if _CURRENCY_CAD.search(blob):
        return "CAD"
    if _CURRENCY_USD.search(blob):
        return "USD"
    # Bare $ with Canadian location cues left to caller; default None (unverified)
    if _DOLLAR.search(blob):
        return None
    return None


def extract_salary_from_text(text: str, *, currency_hint: str | None = None) -> SalaryInfo:
    """Extract employer-advertised annual base when evidence is clear; else undisclosed."""
    blob = text or ""
    reasons: list[str] = []
    if not blob.strip():
        return SalaryInfo(
            None, None, None, "unknown", "undisclosed", "undisclosed",
            "Salary undisclosed / unverified", "", ["no salary text"],
        )

    if _HOURLY.search(blob) and not _BASE.search(blob):
        return SalaryInfo(
            None, None, _detect_currency(blob, currency_hint), "hourly", "base",
            "unverified", "Salary undisclosed / unverified",
            _HOURLY.search(blob).group(0),  # type: ignore[union-attr]
            ["hourly compensation detected — not treated as annual base"],
        )

    currency = currency_hint or _detect_currency(blob)
    kind = "base"
    if _EQUITY_BONUS.search(blob) and not _BASE.search(blob):
        kind = "total_comp"
        reasons.append("compensation text mentions equity/bonus/OTE — not pure base")

    amin = amax = None
    raw = ""
    m = _RANGE.search(blob)
    if m:
        amin = _parse_amount(m.group("a"))
        amax = _parse_amount(m.group("b"))
        raw = m.group(0)
    else:
        m2 = _SINGLE.search(blob)
        if m2:
            amin = amax = _parse_amount(m2.group("a"))
            raw = m2.group(0)

    if amin is None and amax is None:
        return SalaryInfo(
            None, None, currency, "unknown", "undisclosed", "undisclosed",
            "Salary undisclosed / unverified", "",
            reasons or ["no numeric salary found"],
        )

    vals = [v for v in (amin, amax) if v is not None]
    if any(v < MIN_ANNUAL for v in vals) or any(v > MAX_ANNUAL for v in vals):
        return SalaryInfo(
            None, None, currency, "unknown", "undisclosed", "unverified",
            "Salary undisclosed / unverified", raw,
            reasons + ["numeric value outside plausible annual base range"],
        )

    if kind != "base":
        return SalaryInfo(
            None, None, currency, "annual", kind, "unverified",
            "Salary undisclosed / unverified", raw,
            reasons + ["refusing to treat non-base compensation as annual base"],
        )

    if currency is None:
        return SalaryInfo(
            min(vals), max(vals), None, "annual", "base", "unverified",
            "Salary undisclosed / unverified", raw,
            reasons + ["currency not evidenced (CAD/USD)"],
        )

    lo, hi = min(vals), max(vals)
    label = f"Verified salary range: {currency} {int(lo):,}–{int(hi):,}" if lo != hi else (
        f"Verified salary: {currency} {int(lo):,}"
    )
    return SalaryInfo(
        lo, hi, currency, "annual", "base", "verified", label, raw, reasons or ["extracted annual base"]
    )


def enrich_job_salary(job: dict[str, Any]) -> dict[str, Any]:
    """Return salary fields for a job dict without inventing missing pay.

    Prefers existing structured adapter fields; falls back to description/raw text.
    """
    out = dict(job)
    amin = job.get("salary_min")
    amax = job.get("salary_max")
    currency = (job.get("salary_currency") or "").strip().upper() or None
    raw = str(job.get("salary_raw") or "")

    if amin is not None or amax is not None:
        try:
            vals = [float(v) for v in (amin, amax) if v is not None]
        except (TypeError, ValueError):
            vals = []
        if vals and all(MIN_ANNUAL <= v <= MAX_ANNUAL for v in vals) and currency in ("CAD", "USD"):
            lo, hi = min(vals), max(vals)
            label = (
                f"Verified salary range: {currency} {int(lo):,}–{int(hi):,}"
                if lo != hi
                else f"Verified salary: {currency} {int(lo):,}"
            )
            out["salary_confidence"] = "verified"
            out["salary_label"] = label
            out["salary_period"] = "annual"
            return out

    blob = " ".join(
        x for x in (raw, str(job.get("description") or ""), str(job.get("title") or "")) if x
    )
    info = extract_salary_from_text(blob, currency_hint=currency)
    out["salary_confidence"] = info.confidence
    out["salary_label"] = info.label
    out["salary_period"] = info.period
    if info.confidence == "verified" and info.salary_min is not None:
        out["salary_min"] = info.salary_min
        out["salary_max"] = info.salary_max
        out["salary_currency"] = info.currency
        if info.raw and not out.get("salary_raw"):
            out["salary_raw"] = info.raw
    return out


def salary_label_for_job(
    job: dict[str, Any],
    *,
    floors: dict[str, Any] | None = None,
) -> SalaryInfo:
    """Classify display label including below-floor when verified pay exists."""
    enriched = enrich_job_salary(job)
    conf = enriched.get("salary_confidence") or "undisclosed"
    currency = (enriched.get("salary_currency") or "").upper() or None
    amin = enriched.get("salary_min")
    amax = enriched.get("salary_max")
    label = str(enriched.get("salary_label") or "Salary undisclosed / unverified")
    reasons: list[str] = []

    if conf == "verified" and floors and currency and currency in floors:
        try:
            floor = float(floors[currency])
            high = float(amax if amax is not None else amin)
            if high < floor:
                conf = "below_floor"
                label = f"Salary below preference: {currency} {int(float(amin or high)):,}–{int(high):,} (floor {int(floor):,})"
                reasons.append(f"high end {high} below floor {floor}")
        except (TypeError, ValueError):
            pass

    if conf == "undisclosed":
        label = "Salary undisclosed / unverified"
    elif conf == "unverified":
        label = "Salary undisclosed / unverified"

    return SalaryInfo(
        float(amin) if amin is not None else None,
        float(amax) if amax is not None else None,
        currency,
        str(enriched.get("salary_period") or "unknown"),
        "base" if conf in ("verified", "below_floor") else "undisclosed",
        conf,
        label,
        str(enriched.get("salary_raw") or ""),
        reasons,
    )
