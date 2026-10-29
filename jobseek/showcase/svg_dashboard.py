"""Generate a premium dark-theme SVG job dashboard for the README showcase."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

from jobseek.showcase.top_paying import ShowcaseJob, discovery_date_label, format_salary_range

SVG_REL_PATH = "assets/showcase/top-paying-jobs.svg"

# Visual tokens
BG = "#0B1220"
PANEL = "#111827"
CARD = "#151C2C"
CARD_BORDER = "#1E293B"
ACCENT = "#3B82F6"
ACCENT_SOFT = "#1D4ED8"
GREEN = "#34D399"
MUTED = "#94A3B8"
TEXT = "#F8FAFC"
TAG_BG = "#1E293B"
TAG_TEXT = "#CBD5E1"
WIDTH = 880
PAD_X = 28
HEADER_H = 108
CARD_H = 108
CARD_GAP = 12
FOOTER_H = 52


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _truncate(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _tag_pill(x: float, y: float, label: str, *, fill: str = TAG_BG, color: str = TAG_TEXT) -> tuple[str, float]:
    """Return (svg_snippet, width_used)."""
    label = _truncate(label, 28)
    # Approximate width: 7.2px per char at 11px + padding
    w = max(52.0, 14 + len(label) * 7.0)
    h = 22
    r = 11
    snip = (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h}" rx="{r}" fill="{fill}"/>'
        f'<text x="{x + w / 2:.1f}" y="{y + 15:.1f}" text-anchor="middle" '
        f'font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" font-size="11" '
        f'fill="{color}">{_esc(label)}</text>'
    )
    return snip, w


def _verified_badge(cx: float, cy: float) -> str:
    """Blue social-style verification checkmark."""
    return (
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8" fill="{ACCENT}"/>'
        f'<path d="M{cx - 3.6:.1f},{cy:.1f} l2.2,2.3 l4.6,-5.2" fill="none" '
        f'stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
    )


def _apply_hint(x: float, y: float) -> str:
    """Non-interactive cue — GitHub README <img> SVGs cannot host clickable regions."""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="end" '
        f'font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" font-size="11" '
        f'font-weight="600" fill="{ACCENT}">Apply below ↓</text>'
    )


def render_dashboard_svg(
    jobs: list[ShowcaseJob],
    *,
    today: datetime | None = None,
    generated_at: datetime | None = None,
) -> str:
    """Return a complete SVG document string."""
    today = today or datetime.now(timezone.utc)
    generated_at = generated_at or today
    n = len(jobs)
    body_h = HEADER_H + (n * CARD_H + max(0, n - 1) * CARD_GAP if n else 80) + FOOTER_H + 24
    height = body_h + 24

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" '
        f'aria-label="Top 5 High-Paying Jobs Discovered Today">'
        f"<title>Top 5 High-Paying Jobs Discovered Today</title>"
        f"<defs>"
        f'<linearGradient id="ghBg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="#0B1220"/>'
        f'<stop offset="100%" stop-color="#0F172A"/>'
        f"</linearGradient>"
        f'<linearGradient id="ghHeader" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0%" stop-color="#1D4ED8" stop-opacity="0.35"/>'
        f'<stop offset="100%" stop-color="#0B1220" stop-opacity="0"/>'
        f"</linearGradient>"
        f'<filter id="ghShadow" x="-2%" y="-2%" width="104%" height="110%">'
        f'<feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#000" flood-opacity="0.35"/>'
        f"</filter>"
        f"</defs>"
        f'<rect width="{WIDTH}" height="{height}" rx="24" fill="url(#ghBg)"/>'
        f'<rect x="1" y="1" width="{WIDTH - 2}" height="{height - 2}" rx="23" '
        f'fill="none" stroke="#1E293B" stroke-width="1"/>'
        # Header panel
        f'<rect x="16" y="16" width="{WIDTH - 32}" height="{HEADER_H}" rx="18" fill="{PANEL}"/>'
        f'<rect x="16" y="16" width="{WIDTH - 32}" height="{HEADER_H}" rx="18" fill="url(#ghHeader)"/>'
        f'<text x="{PAD_X + 4}" y="52" font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" '
        f'font-size="26" font-weight="800" fill="{TEXT}">Top 5 High-Paying Jobs Discovered Today</text>'
        f'<text x="{PAD_X + 4}" y="80" font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" '
        f'font-size="14" font-style="italic" fill="{MUTED}">'
        f"Real opportunities. Direct from company career pages. Powered by GitHired."
        f"</text>"
        f'<text x="{PAD_X + 4}" y="104" font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" '
        f'font-size="11" fill="#64748B">Advertised annual base · CAD &amp; USD labeled · '
        f'No estimates · Snapshot {generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</text>',
    ]

    y = 16 + HEADER_H + 16
    if not jobs:
        parts.append(
            f'<rect x="16" y="{y}" width="{WIDTH - 32}" height="72" rx="16" fill="{CARD}" '
            f'stroke="{CARD_BORDER}"/>'
            f'<text x="{WIDTH / 2}" y="{y + 42}" text-anchor="middle" '
            f'font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" font-size="14" fill="{MUTED}">'
            f"No qualifying salaried Canada-eligible engineering roles in this snapshot."
            f"</text>"
        )
        y += 88
    else:
        for i, job in enumerate(jobs, start=1):
            card_y = y + (i - 1) * (CARD_H + CARD_GAP)
            salary = format_salary_range(job.salary_min, job.salary_max, job.salary_currency)
            date_label = discovery_date_label(
                discovered_today=job.discovered_today,
                verified_at=job.verified_at,
                today=today,
            )
            title = _truncate(job.title, 52)
            company = _truncate(job.company, 28)
            loc_tag = _truncate(job.location_tag or job.eligibility_label or "Canada", 26)
            mode_tag = _truncate(job.work_mode_tag or "Full-time", 16)

            # Card shell
            parts.append(
                f'<g filter="url(#ghShadow)">'
                f'<rect x="16" y="{card_y}" width="{WIDTH - 32}" height="{CARD_H}" rx="16" '
                f'fill="{CARD}" stroke="{CARD_BORDER}"/>'
                f"</g>"
                # Rank chip
                f'<rect x="32" y="{card_y + 18}" width="28" height="28" rx="8" fill="#0F172A" '
                f'stroke="{ACCENT_SOFT}"/>'
                f'<text x="46" y="{card_y + 37}" text-anchor="middle" '
                f'font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" font-size="13" '
                f'font-weight="700" fill="{ACCENT}">{i}</text>'
                # Title
                f'<text x="72" y="{card_y + 37}" '
                f'font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" font-size="17" '
                f'font-weight="700" fill="{TEXT}">{_esc(title)}</text>'
            )

            # Company + optional verified badge
            company_x = 72.0
            parts.append(
                f'<text x="{company_x}" y="{card_y + 60}" '
                f'font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" font-size="13" '
                f'fill="{MUTED}">{_esc(company)}</text>'
            )
            if job.career_page_verified:
                # Approximate company text width
                badge_x = company_x + len(company) * 7.4 + 14
                parts.append(_verified_badge(badge_x, card_y + 55))

            # Tags
            tag_x = 72.0
            tag_y = card_y + 74
            t1, w1 = _tag_pill(tag_x, tag_y, loc_tag)
            parts.append(t1)
            t2, _w2 = _tag_pill(tag_x + w1 + 8, tag_y, mode_tag)
            parts.append(t2)

            # Salary + date (right side); links live in Markdown under the image
            salary_x = WIDTH - 36
            parts.append(
                f'<text x="{salary_x}" y="{card_y + 40}" text-anchor="end" '
                f'font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" font-size="18" '
                f'font-weight="800" fill="{GREEN}">{_esc(salary)}</text>'
                f'<text x="{salary_x}" y="{card_y + 60}" text-anchor="end" '
                f'font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" font-size="11" '
                f'fill="{MUTED}">{_esc(date_label)}</text>'
            )
            parts.append(_apply_hint(salary_x, card_y + 86))

    footer_y = y + (n * CARD_H + max(0, n - 1) * CARD_GAP if n else 88) + 18
    parts.append(
        f'<text x="{WIDTH / 2}" y="{footer_y}" text-anchor="middle" '
        f'font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif" font-size="12" '
        f'font-weight="600" fill="{MUTED}">'
        f"Discovered and verified by GitHired · Open Source"
        f"</text>"
        f"</svg>\n"
    )
    return "".join(parts)


def write_dashboard_svg(
    path: Path,
    jobs: list[ShowcaseJob],
    *,
    today: datetime | None = None,
    generated_at: datetime | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_dashboard_svg(jobs, today=today, generated_at=generated_at),
        encoding="utf-8",
    )
