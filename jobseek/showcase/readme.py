"""Render and surgically replace the Top Paying Jobs section in README.md."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jobseek.showcase.svg_dashboard import SVG_REL_PATH, write_dashboard_svg
from jobseek.showcase.top_paying import COMPARISON_RULE, ShowcaseJob

START_MARKER = "<!-- TOP-PAYING-JOBS:START -->"
END_MARKER = "<!-- TOP-PAYING-JOBS:END -->"


def _escape_md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").replace("[", "\\[").replace("]", "\\]").strip()


def render_section(
    jobs: list[ShowcaseJob],
    *,
    generated_at: datetime | None = None,
    comparison_rule: str = COMPARISON_RULE,
    svg_rel_path: str = SVG_REL_PATH,
    today: datetime | None = None,
) -> str:
    """Return Markdown between (and including) the START/END markers."""
    generated_at = generated_at or datetime.now(timezone.utc)
    today = today or generated_at
    stamp = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        START_MARKER,
        "",
        "## Top 5 High-Paying Jobs Discovered Today",
        "",
        "*Real opportunities. Direct from company career pages. Powered by GitHired.*",
        "",
    ]

    if not jobs:
        lines.extend(
            [
                f'<p align="center"><img src="{svg_rel_path}" alt="GitHired top paying jobs showcase" width="880" /></p>',
                "",
                "_No qualifying salaried Canada-eligible engineering roles in the "
                "current snapshot. The previous successful refresh is preserved when "
                "discovery fails; this empty state means the latest successful run "
                "found none under the published rules._",
                "",
                '<p align="center"><a href="#quick-start"><strong>Get Started with GitHired →</strong></a></p>',
                "",
                "<details>",
                "<summary>Ranking & eligibility rules</summary>",
                "",
                comparison_rule,
                "",
                "- Canada geographic eligibility required.",
                "- Direct employer career / ATS URLs only (affiliates excluded).",
                "- Engineering tracks only; listings older than 14 days excluded.",
                "- **Discovered Today** appears on a card only when `first_seen` is today; "
                "otherwise the card shows **Verified YYYY-MM-DD**.",
                "- Fewer than five cards means fewer than five qualified.",
                "",
                "</details>",
                "",
                END_MARKER,
            ]
        )
        return "\n".join(lines)

    lines.extend(
        [
            f'<p align="center"><img src="{svg_rel_path}" alt="Top 5 high-paying Canada-eligible engineering jobs discovered by GitHired" width="880" /></p>',
            "",
            "<p align=\"center\">",
        ]
    )

    # Clickable Apply links (SVG buttons are visual-only on GitHub <img>)
    apply_bits: list[str] = []
    for i, job in enumerate(jobs, start=1):
        label = f"{i}. {_escape_md(job.company)} — Apply →"
        apply_bits.append(f'<a href="{job.apply_url}"><strong>{label}</strong></a>')
    lines.append(" &nbsp;·&nbsp; ".join(apply_bits))
    lines.extend(
        [
            "</p>",
            "",
            '<p align="center"><strong>Discovered and verified by GitHired · Open Source</strong></p>',
            "",
            '<p align="center"><a href="#quick-start"><strong>Get Started with GitHired →</strong></a></p>',
            "",
            "<details>",
            "<summary>Ranking & eligibility rules</summary>",
            "",
            comparison_rule,
            "",
            f"- Snapshot refreshed: **{stamp}** (preserved on failure — never backdated).",
            "- Blue ✓ marks listings confirmed against a direct employer career / ATS URL.",
            "- **Discovered Today** is shown only when the job’s `first_seen` date is today; "
            "otherwise the card shows the last verified date.",
            "- Advertised annual base only (CAD / USD); no estimates for undisclosed pay.",
            "- Fewer than five cards means fewer than five qualified.",
            "",
            "</details>",
            "",
            END_MARKER,
        ]
    )
    return "\n".join(lines)


def replace_section(readme_text: str, new_section: str) -> str:
    """Replace content between markers. Raises if markers missing or malformed."""
    if START_MARKER not in readme_text or END_MARKER not in readme_text:
        raise ValueError("README is missing TOP-PAYING-JOBS markers")
    start = readme_text.index(START_MARKER)
    end = readme_text.index(END_MARKER) + len(END_MARKER)
    if start > end - len(END_MARKER):
        raise ValueError("TOP-PAYING-JOBS markers out of order")
    if not new_section.startswith(START_MARKER) or not new_section.rstrip().endswith(
        END_MARKER
    ):
        raise ValueError("new_section must include START and END markers")
    return readme_text[:start] + new_section.rstrip() + readme_text[end:]


def update_readme_file(
    readme_path: Path,
    jobs: list[ShowcaseJob],
    *,
    generated_at: datetime | None = None,
    svg_path: Path | None = None,
    today: datetime | None = None,
) -> bool:
    """Write SVG + README section if changed. Returns True if README written."""
    generated_at = generated_at or datetime.now(timezone.utc)
    today = today or generated_at
    if svg_path is None:
        svg_path = readme_path.parent / SVG_REL_PATH
    write_dashboard_svg(svg_path, jobs, today=today, generated_at=generated_at)

    text = readme_path.read_text(encoding="utf-8")
    section = render_section(jobs, generated_at=generated_at, today=today)
    updated = replace_section(text, section)
    if updated == text:
        return False
    readme_path.write_text(updated, encoding="utf-8")
    return True
