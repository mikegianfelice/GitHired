"""Salary extraction and confidence labeling (never invent undisclosed pay).

Shared normalization used by ATS adapters and enrich/backfill. Prefer
structured employer fields; fall back to description text only when clear.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any

_CURRENCY_CAD = re.compile(r"\b(?:CAD|CDN)\b|C\$|CA\$", re.I)
_CURRENCY_USD = re.compile(r"\b(?:USD)\b|US\$", re.I)
_DOLLAR = re.compile(r"\$")

# Strip tags but keep spaces so "CAD$95,000" in HTML still parses.
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# Annual / range patterns — match FULL amounts (do not strip commas before matching).
# Supports: CAD $95,000–$135,000 | CA$95K–CA$135K | $120k–$160k CAD | 95000–135000
_CUR = r"(?:CAD|USD|CDN|C\$|CA\$|US\$|\$)"
_NUM = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,7}(?:\.\d+)?|\d{1,3}(?:\.\d+)?[Kk])"
_AMOUNT_TOKEN = rf"(?:{_CUR}\s*)?{_NUM}"
_RANGE = re.compile(
    rf"(?:(?P<cur_lead>{_CUR})\s*)?"
    rf"\$?\s*"
    rf"(?P<a>{_NUM})"
    rf"\s*(?:-|–|—|to)\s*"
    rf"(?:(?P<cur_mid>{_CUR})\s*)?"
    rf"\$?\s*"
    rf"(?P<b>{_NUM})"
    rf"(?:\s*(?P<cur_trail>CAD|USD|CDN))?",
    re.I,
)
# Also match CA$95K–CA$135K where currency sticks to the number
_RANGE_STUCK = re.compile(
    rf"(?P<a>{_AMOUNT_TOKEN})\s*(?:-|–|—|to)\s*(?P<b>{_AMOUNT_TOKEN})"
    rf"(?:\s*(?P<cur_trail>CAD|USD|CDN))?",
    re.I,
)
_SINGLE = re.compile(
    rf"(?:(?P<cur_lead>{_CUR})\s*)?"
    rf"\$?\s*"
    rf"(?P<a>{_NUM})"
    rf"(?:\s*(?P<cur_trail>CAD|USD|CDN))?"
    rf"(?=\s*(?:per\s+year|annually|/?\s*year|base|salary|market|\.|,|;|$))",
    re.I,
)
_HOURLY = re.compile(
    r"(?:"
    r"(?:CAD|USD|C\$|CA\$|US\$|\$)\s*\d{1,3}(?:,\d{3})?(?:\.\d+)?\s*(?:-|–|—|to)\s*"
    r"(?:CAD|USD|C\$|CA\$|US\$|\$)?\s*\d{1,3}(?:,\d{3})?(?:\.\d+)?\s*"
    r"(?:/\s*(?:hr|hour)|per\s+hour|\bh(?:ou)?r\b)"
    r"|"
    r"(?:CAD|USD|C\$|CA\$|US\$|\$)\s*\d{1,3}(?:,\d{3})?(?:\.\d+)?\s*"
    r"(?:/\s*(?:hr|hour)|per\s+hour|\bh(?:ou)?r\b)"
    r"|"
    r"\b\d{1,3}(?:\.\d+)?\s*(?:CAD|USD|C\$)?\s*(?:/\s*(?:hr|hour)|per\s+hour)"
    r")",
    re.I,
)
_EQUITY_BONUS = re.compile(
    r"\b(?:equity|RSU|stock\s+options?|bonus|OTE|on[\s-]?target\s+earnings|"
    r"total\s+compensation|total\s+comp|TCC)\b",
    re.I,
)
_BASE = re.compile(
    r"\b(?:base\s+(?:pay|salary)|annual\s+(?:base\s+)?(?:pay|salary)|"
    r"salary\s+range|pay\s+range|compensation\s+range)\b",
    re.I,
)
_ANNUAL_CUE = re.compile(r"\b(?:per\s+year|annually|/?\s*year|annual)\b", re.I)
_OTE_ONLY = re.compile(
    r"\b(?:OTE|on[\s-]?target\s+earnings|total\s+compensation|total\s+comp|TCC)\b",
    re.I,
)

MIN_ANNUAL = 30_000.0
MAX_ANNUAL = 800_000.0
MIN_HOURLY = 15.0
MAX_HOURLY = 500.0

# Lever / Workable / common ATS interval tokens → canonical period.
_ANNUAL_INTERVALS = frozenset(
    {
        "per-year-salary",
        "per-year",
        "per year",
        "year",
        "yearly",
        "annual",
        "annually",
        "1 year",
        "yr",
    }
)
_HOURLY_INTERVALS = frozenset(
    {
        "per-hour-salary",
        "per-hour",
        "per hour",
        "hour",
        "hourly",
        "hr",
        "1 hour",
    }
)
_MONTHLY_INTERVALS = frozenset(
    {
        "per-month-salary",
        "per-month",
        "per month",
        "month",
        "monthly",
        "1 month",
    }
)


@dataclass(frozen=True)
class SalaryInfo:
    salary_min: float | None
    salary_max: float | None
    currency: str | None  # CAD | USD | None
    period: str  # annual | hourly | monthly | unknown
    kind: str  # base | total_comp | equity_bonus | undisclosed
    confidence: str  # verified | below_floor | undisclosed | unverified
    label: str
    raw: str
    reasons: list[str]
    source: str = "unavailable"  # structured_ats | employer_description | unavailable
    interval: str | None = None  # original ATS interval token when known


def strip_html(text: str) -> str:
    plain = _TAG.sub(" ", html.unescape(text or ""))
    return _WS.sub(" ", plain).strip()


def _parse_amount(token: str) -> float | None:
    """Parse an amount token. Commas are thousands separators — never strip before matching digits."""
    text = (token or "").strip()
    if not text:
        return None
    # Drop currency prefixes from the amount token
    text = re.sub(r"^(?:CAD|USD|CDN|C\$|CA\$|US\$|\$)\s*", "", text, flags=re.I)
    text = text.strip().lower().replace(" ", "")
    mult = 1.0
    if text.endswith("k"):
        mult = 1000.0
        text = text[:-1]
    text = text.replace(",", "")
    try:
        return float(text) * mult
    except ValueError:
        return None


def _currency_from_token(token: str | None) -> str | None:
    if not token:
        return None
    t = token.strip().upper()
    if t in ("CAD", "CDN", "C$", "CA$") or t == "C$":
        return "CAD"
    if t in ("USD", "US$"):
        return "USD"
    if t == "$":
        return None  # ambiguous bare dollar
    if "CA$" in t or t.startswith("C"):
        return "CAD"
    return None


def _detect_currency(text: str, structured: str | None = None) -> str | None:
    blob = f"{structured or ''} {text}"
    if _CURRENCY_CAD.search(blob):
        return "CAD"
    if _CURRENCY_USD.search(blob):
        return "USD"
    if _DOLLAR.search(blob):
        return None
    return None


# Canadian geo tokens strong enough to hint CAD for bare `$` salary bands.
_CAD_LOCATION = re.compile(
    r"""
    \bcanada\b | \bcanadian\b |
    \b(?:ontario|quebec|alberta|manitoba|saskatchewan|
       newfoundland|labrador|nova\s+scotia|new\s+brunswick|
       prince\s+edward|british\s+columbia|yukon|nunavut|
       northwest\s+territories)\b |
    # Workday-style "Toronto, ON, CAN" — require province/country codes near a comma
    # or as a trailing ISO code so bare English words ("on", "can") do not match.
    (?:,\s*|\b)(?:ON|QC|AB|MB|SK|NL|NS|NB|PE|BC|YT|NU|NT|CAN)\b |
    \b(?:toronto|vancouver|montreal|ottawa|calgary|edmonton|
       winnipeg|halifax|victoria|mississauga|brampton|hamilton|
       kitchener|waterloo|quebec\s+city|gatineau)\b
    """,
    re.I | re.X,
)
_USD_LOCATION = re.compile(
    r"""
    \b(?:united\s+states|u\.?s\.?a?\.?|usa)\b |
    \b(?:remote[,\s-]+(?:usa|u\.?s\.?a?\.?)|(?:usa|u\.?s\.?a?\.?)[,\s-]+remote)\b |
    \b(?:new\s+york|san\s+francisco|seattle|austin|boston|chicago|
       denver|atlanta|miami|los\s+angeles|washington)\b |
    \b(?:ny|ca|wa|tx|ma|il|co|ga|fl|dc)\b
    """,
    re.I | re.X,
)
# US city/zone labels that must not be treated as a Canadian job's pay band.
_US_CITY_BAND = re.compile(
    r"""
    \b(?:menlo\s+park|new\s+york|bellevue|washington|denver|westlake|
       chicago|lake\s+mary|clearwater|gainesville|san\s+francisco|
       seattle|austin|boston|atlanta|miami|los\s+angeles)\b |
    \b(?:,\s*(?:NY|CA|WA|TX|IL|CO|FL|DC|MA|GA)\b)
    """,
    re.I | re.X,
)
_CAD_CITY_BAND = re.compile(
    r"""
    \b(?:toronto|vancouver|montreal|ottawa|calgary|edmonton|winnipeg|
       halifax|victoria|mississauga|canada|canadian)\b |
    \b(?:,\s*(?:ON|QC|AB|BC|MB|SK|NS|NB|PE|NL)\b) |
    \bCAD\b | \bCA\$ | \bC\$
    """,
    re.I | re.X,
)


def currency_hint_from_location(location: str | None) -> str | None:
    """Infer CAD/USD from a job's structured location — never invent amounts."""
    loc = (location or "").strip()
    if not loc:
        return None
    cad = bool(_CAD_LOCATION.search(loc))
    usd = bool(_USD_LOCATION.search(loc))
    if cad and not usd:
        return "CAD"
    if usd and not cad:
        return "USD"
    # Ambiguous dual-geo location: do not guess currency.
    return None


def _range_matches(blob: str) -> list[re.Match[str]]:
    """All non-overlapping annual range matches in text order."""
    matches: list[re.Match[str]] = []
    for pattern in (_RANGE, _RANGE_STUCK):
        for m in pattern.finditer(blob):
            if any(m.start() < prev.end() and m.end() > prev.start() for prev in matches):
                continue
            matches.append(m)
    matches.sort(key=lambda m: m.start())
    return matches


def _band_context(blob: str, match: re.Match[str], *, before: int = 220, after: int = 24) -> str:
    """Location labels almost always precede the pay figures — bias lookbehind."""
    return blob[max(0, match.start() - before) : match.end() + after]


def _match_currency(match: re.Match[str]) -> str | None:
    """Currency evidenced on the matched salary snippet itself."""
    raw = match.group(0)
    tokens = [raw]
    for g in ("cur_lead", "cur_mid", "cur_trail"):
        if match.groupdict().get(g):
            tokens.append(match.group(g))
    for tok in tokens:
        if re.search(r"CA\$|C\$|\bCAD\b|\bCDN\b", tok or "", re.I):
            return "CAD"
        if re.search(r"US\$|\bUSD\b", tok or "", re.I):
            return "USD"
    return _detect_currency(raw)


def _select_location_band(
    blob: str,
    matches: list[re.Match[str]],
    *,
    location_hint: str | None,
) -> re.Match[str] | None:
    """Pick the salary band that applies to the job's eligible location.

    Multi-geo postings often list several city/zone bands. Prefer the band whose
    nearby label matches the job location; refuse US-city-only bands for a
    Canadian location (and vice versa when CAD bands exist).
    """
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    loc = (location_hint or "").strip()
    loc_cad = bool(loc and _CAD_LOCATION.search(loc))
    loc_usd = bool(loc and _USD_LOCATION.search(loc) and not loc_cad)
    preferred_cur = currency_hint_from_location(loc)

    scored: list[tuple[int, re.Match[str]]] = []
    for m in matches:
        ctx = _band_context(blob, m)
        band_cur = _match_currency(m)
        score = 0
        if preferred_cur and band_cur == preferred_cur:
            score += 12
        elif preferred_cur and band_cur and band_cur != preferred_cur:
            score -= 12
        if loc:
            # Token overlap between location hint and preceding band label.
            for token in re.findall(r"[A-Za-z]{3,}", loc):
                if token.casefold() in {"remote", "hybrid", "onsite", "office"}:
                    continue
                if re.search(rf"\b{re.escape(token)}\b", ctx, re.I):
                    score += 4
        if loc_cad and _CAD_CITY_BAND.search(ctx):
            score += 5
        if loc_usd and _US_CITY_BAND.search(ctx):
            score += 5
        if loc_cad and _US_CITY_BAND.search(ctx) and not _CAD_CITY_BAND.search(ctx):
            score -= 8
        if loc_usd and _CAD_CITY_BAND.search(ctx) and not _US_CITY_BAND.search(ctx):
            score -= 8
        scored.append((score, m))

    scored.sort(key=lambda pair: (-pair[0], pair[1].start()))
    best_score, best = scored[0]
    if loc_cad and best_score < 0:
        # Canadian job, only US-city / USD bands → do not publish as Canadian pay.
        return None
    if best_score > 0 or not loc:
        return best
    # No location match among multi-bands: refuse rather than invent.
    if loc and len(matches) > 1:
        return None
    return best


def normalize_interval(interval: str | None) -> str:
    """Map ATS interval tokens to annual | hourly | monthly | unknown."""
    if not interval:
        return "unknown"
    key = str(interval).strip().lower()
    if key in _ANNUAL_INTERVALS:
        return "annual"
    if key in _HOURLY_INTERVALS:
        return "hourly"
    if key in _MONTHLY_INTERVALS:
        return "monthly"
    # Fuzzy
    if "hour" in key or key.endswith("/hr"):
        return "hourly"
    if "month" in key:
        return "monthly"
    if "year" in key or "annual" in key:
        return "annual"
    return "unknown"


def from_structured(
    *,
    amin: float | None,
    amax: float | None,
    currency: str | None,
    interval: str | None = None,
    raw: str | None = None,
    source: str = "structured_ats",
) -> SalaryInfo:
    """Normalize structured ATS compensation into SalaryInfo.

    Non-annual intervals are never promoted to verified annual base.
    """
    period = normalize_interval(interval)
    cur = (currency or "").strip().upper() or None
    if cur not in ("CAD", "USD"):
        cur = None
    reasons: list[str] = []
    try:
        vals = [float(v) for v in (amin, amax) if v is not None]
    except (TypeError, ValueError):
        vals = []

    if not vals:
        return SalaryInfo(
            None, None, cur, period or "unknown", "undisclosed", "undisclosed",
            "Salary undisclosed / unverified", raw or "",
            ["no structured amounts"], source="unavailable", interval=interval,
        )

    lo, hi = min(vals), max(vals)
    display_raw = raw or f"{cur or ''} {lo:g}-{hi:g}".strip()

    if period == "hourly":
        return SalaryInfo(
            lo if MIN_HOURLY <= lo <= MAX_HOURLY else None,
            hi if MIN_HOURLY <= hi <= MAX_HOURLY else None,
            cur, "hourly", "base", "unverified",
            "Salary undisclosed / unverified", display_raw,
            ["hourly compensation — not treated as annual base"],
            source=source, interval=interval,
        )

    if period == "monthly":
        return SalaryInfo(
            None, None, cur, "monthly", "base", "unverified",
            "Salary undisclosed / unverified", display_raw,
            ["monthly compensation — not converted to annual"],
            source=source, interval=interval,
        )

    if period not in ("annual", "unknown"):
        return SalaryInfo(
            None, None, cur, period, "base", "unverified",
            "Salary undisclosed / unverified", display_raw,
            [f"unsupported pay interval: {interval}"],
            source=source, interval=interval,
        )

    # unknown interval: only accept if values look like annual base
    if period == "unknown":
        reasons.append("pay interval missing — requiring annual-looking amounts")

    if any(v < MIN_ANNUAL or v > MAX_ANNUAL for v in vals):
        return SalaryInfo(
            None, None, cur, period, "undisclosed", "unverified",
            "Salary undisclosed / unverified", display_raw,
            reasons + ["numeric value outside plausible annual base range"],
            source=source, interval=interval,
        )

    if cur is None:
        return SalaryInfo(
            lo, hi, None, "annual", "base", "unverified",
            "Salary undisclosed / unverified", display_raw,
            reasons + ["currency not evidenced (CAD/USD)"],
            source=source, interval=interval,
        )

    # Missing interval + annual-looking + currency → verified only when interval
    # was explicitly annual; unknown interval stays unverified unless clearly annual cues in raw.
    if period == "annual" or (period == "unknown" and _ANNUAL_CUE.search(display_raw or "")):
        conf = "verified"
        label = (
            f"Verified salary range: {cur} {int(lo):,}–{int(hi):,}"
            if lo != hi
            else f"Verified salary: {cur} {int(lo):,}"
        )
        return SalaryInfo(
            lo, hi, cur, "annual", "base", conf, label, display_raw,
            reasons or ["structured annual base"], source=source, interval=interval,
        )

    # Structured amounts in annual band with currency but no interval → verified
    # when values are clearly annual (ATS structured fields typically mean yearly).
    if period == "unknown" and source == "structured_ats":
        label = (
            f"Verified salary range: {cur} {int(lo):,}–{int(hi):,}"
            if lo != hi
            else f"Verified salary: {cur} {int(lo):,}"
        )
        return SalaryInfo(
            lo, hi, cur, "annual", "base", "verified", label, display_raw,
            reasons + ["structured ATS amounts treated as annual base"],
            source=source, interval=interval,
        )

    return SalaryInfo(
        lo, hi, cur, "annual", "base", "unverified",
        "Salary undisclosed / unverified", display_raw, reasons,
        source=source, interval=interval,
    )


def extract_salary_from_text(
    text: str,
    *,
    currency_hint: str | None = None,
    location_hint: str | None = None,
) -> SalaryInfo:
    """Extract employer-advertised annual base when evidence is clear; else undisclosed.

    When multiple geographic pay bands appear, select only the band that matches
    ``location_hint`` (Canadian location must not inherit a US-city USD band).
    """
    blob = strip_html(text or "")
    reasons: list[str] = []
    if not blob.strip():
        return SalaryInfo(
            None, None, None, "unknown", "undisclosed", "undisclosed",
            "Salary undisclosed / unverified", "", ["no salary text"],
            source="unavailable",
        )

    if _HOURLY.search(blob) and not (_BASE.search(blob) and _ANNUAL_CUE.search(blob)):
        m = _HOURLY.search(blob)
        return SalaryInfo(
            None, None, _detect_currency(blob, currency_hint), "hourly", "base",
            "unverified", "Salary undisclosed / unverified",
            m.group(0) if m else "",
            ["hourly compensation detected — not treated as annual base"],
            source="employer_description",
        )

    loc_hint = currency_hint_from_location(location_hint)
    currency = currency_hint if (currency_hint or "").upper() in ("CAD", "USD") else None
    currency = currency or loc_hint
    currency = currency or _detect_currency(blob)

    amin = amax = None
    raw = ""
    matched_currency_tokens: list[str] = []
    range_matches = _range_matches(blob)
    m = _select_location_band(blob, range_matches, location_hint=location_hint)
    if range_matches and m is None:
        return SalaryInfo(
            None, None, currency, "unknown", "undisclosed", "undisclosed",
            "Salary undisclosed / unverified", "",
            reasons
            + [
                "multiple geographic salary bands found; none match job location "
                "(refusing to publish a non-applicable band)"
            ],
            source="employer_description",
        )
    if m:
        amin = _parse_amount(m.group("a"))
        amax = _parse_amount(m.group("b"))
        raw = m.group(0)
        for g in ("cur_lead", "cur_mid", "cur_trail"):
            if m.groupdict().get(g):
                matched_currency_tokens.append(m.group(g))
        # Stuck form embeds currency in a/b tokens
        matched_currency_tokens.extend([m.group("a"), m.group("b")])
        # Prefer currency token adjacent to the selected band over whole-doc scan.
        band_cur = _detect_currency(_band_context(blob, m), None)
        if band_cur:
            currency = band_cur
    else:
        m2 = _SINGLE.search(blob)
        if m2:
            amin = amax = _parse_amount(m2.group("a"))
            raw = m2.group(0)
            for g in ("cur_lead", "cur_trail"):
                if m2.groupdict().get(g):
                    matched_currency_tokens.append(m2.group(g))

    for tok in matched_currency_tokens:
        mapped = _currency_from_token(tok) if tok and not re.match(r"^[\d,.k]+$", tok.strip(), re.I) else None
        if mapped is None and tok:
            # CA$95K / C$120,000 style
            if re.search(r"CA\$|C\$|CAD", tok, re.I):
                mapped = "CAD"
            elif re.search(r"US\$|USD", tok, re.I):
                mapped = "USD"
        if mapped:
            currency = mapped
            break
    if currency is None:
        currency = _detect_currency(blob, currency_hint) or loc_hint

    if amin is None and amax is None:
        return SalaryInfo(
            None, None, currency, "unknown", "undisclosed", "undisclosed",
            "Salary undisclosed / unverified", "",
            reasons or ["no numeric salary found"], source="unavailable",
        )

    vals = [v for v in (amin, amax) if v is not None]
    if any(v < MIN_ANNUAL for v in vals) or any(v > MAX_ANNUAL for v in vals):
        return SalaryInfo(
            None, None, currency, "unknown", "undisclosed", "unverified",
            "Salary undisclosed / unverified", raw,
            reasons + ["numeric value outside plausible annual base range"],
            source="employer_description",
        )

    # Equity/bonus elsewhere in a posting is common; only reject when the matched
    # snippet itself is OTE/total-comp, or when there is no base/pay-range cue and
    # the only compensation language is equity/OTE.
    kind = "base"
    window = blob
    if raw and raw in blob:
        idx = blob.find(raw)
        window = blob[max(0, idx - 80) : idx + len(raw) + 80]
    if _OTE_ONLY.search(raw) or _OTE_ONLY.search(window):
        kind = "total_comp"
        reasons.append("matched compensation looks like OTE/total comp — not base")
    elif _EQUITY_BONUS.search(blob) and not _BASE.search(blob) and not currency:
        kind = "total_comp"
        reasons.append("compensation text mentions equity/bonus/OTE without base cues")

    if kind != "base":
        return SalaryInfo(
            None, None, currency, "annual", kind, "unverified",
            "Salary undisclosed / unverified", raw,
            reasons + ["refusing to treat non-base compensation as annual base"],
            source="employer_description",
        )

    if currency is None:
        return SalaryInfo(
            min(vals), max(vals), None, "annual", "base", "unverified",
            "Salary undisclosed / unverified", raw,
            reasons + ["currency not evidenced (CAD/USD)"],
            source="employer_description",
        )

    lo, hi = min(vals), max(vals)
    label = f"Verified salary range: {currency} {int(lo):,}–{int(hi):,}" if lo != hi else (
        f"Verified salary: {currency} {int(lo):,}"
    )
    return SalaryInfo(
        lo, hi, currency, "annual", "base", "verified", label, raw,
        reasons or ["extracted annual base"], source="employer_description",
    )


def enrich_job_salary(job: dict[str, Any]) -> dict[str, Any]:
    """Return salary fields for a job dict without inventing missing pay.

    Prefers existing structured adapter fields; falls back to description/raw text.
    Never overwrites verified structured annual pay with weaker description parses.
    """
    out = dict(job)
    amin = job.get("salary_min")
    amax = job.get("salary_max")
    currency = (job.get("salary_currency") or "").strip().upper() or None
    raw = str(job.get("salary_raw") or "")
    interval = job.get("salary_interval") or job.get("salary_period")
    existing_conf = (job.get("salary_confidence") or "").strip().lower()

    structured = from_structured(
        amin=float(amin) if amin is not None else None,
        amax=float(amax) if amax is not None else None,
        currency=currency,
        interval=str(interval) if interval else None,
        raw=raw or None,
        source="structured_ats",
    )
    if amin is not None or amax is not None:
        if structured.confidence == "verified":
            out["salary_min"] = structured.salary_min
            out["salary_max"] = structured.salary_max
            out["salary_currency"] = structured.currency
            out["salary_confidence"] = "verified"
            out["salary_label"] = structured.label
            out["salary_period"] = "annual"
            out["salary_source"] = job.get("salary_source") or "structured_ats"
            if structured.interval:
                out["salary_interval"] = structured.interval
            return out
        if structured.period == "hourly":
            out["salary_confidence"] = "unverified"
            out["salary_label"] = structured.label
            out["salary_period"] = "hourly"
            out["salary_source"] = job.get("salary_source") or "structured_ats"
            # Do not keep hourly amounts in annual salary_min/max columns.
            out["salary_min"] = None
            out["salary_max"] = None
            return out

    if existing_conf == "verified" and amin is not None and currency in ("CAD", "USD"):
        # Preserve verified rows; do not clobber with description.
        out.setdefault("salary_period", "annual")
        out.setdefault("salary_source", "structured_ats")
        return out

    blob = " ".join(
        x for x in (raw, str(job.get("description") or ""), str(job.get("title") or "")) if x
    )
    loc = str(job.get("location_raw") or "") or None
    hint = currency or currency_hint_from_location(loc)
    info = extract_salary_from_text(
        blob, currency_hint=hint, location_hint=loc
    )
    out["salary_confidence"] = info.confidence
    out["salary_label"] = info.label
    out["salary_period"] = info.period
    out["salary_source"] = info.source
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
        source=str(enriched.get("salary_source") or "unavailable"),
        interval=enriched.get("salary_interval"),
    )


def apply_salary_info_to_raw(
    *,
    info: SalaryInfo,
) -> tuple[str | None, float | None, float | None, str | None]:
    """Map SalaryInfo onto RawJob salary_* columns (annual verified only for min/max)."""
    if info.confidence == "verified" and info.period == "annual" and info.salary_min is not None:
        return info.raw or None, info.salary_min, info.salary_max, info.currency
    if info.raw and info.period in ("hourly", "monthly"):
        return info.raw, None, None, info.currency
    if info.raw and info.confidence == "unverified":
        return info.raw, None, None, info.currency
    return info.raw or None, None, None, None
