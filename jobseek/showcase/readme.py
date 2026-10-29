"""Render and surgically replace the Top Paying Jobs section in README.md."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from jobseek.showcase.top_paying import (
    COMPARISON_RULE,
    ShowcaseJob,
    format_salary_range,
    verified_date_label,
)

START_MARKER = "<!-- TOP-PAYING-JOBS:START -->"
END_MARKER = "<!-- TOP-PAYING-JOBS:END -->"


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_section(
    jobs: list[ShowcaseJob],
    *,
    generated_at: datetime | None = None,
    comparison_rule: str = COMPARISON_RULE,
) -> str:
    """Return Markdown between (and including) the START/END markers."""
    generated_at = generated_at or datetime.now(timezone.utc)
    stamp = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        START_MARKER,
        "",
        "## Top 5 High-Paying Jobs",
        "",
        "> Real listings discovered by GitHired with **employer-advertised** annual "
        "base salaries. No estimates. Ranked by annual high end "
        f"(CAD-comparable for sorting; USD×{1.35:g}). "
        f"Last refreshed: **{stamp}**.",
        "",
    ]

    if not jobs:
        lines.extend(
            [
                "_No qualifying salaried Canada-eligible engineering roles in the "
                "current snapshot. The previous successful refresh is preserved when "
                "discovery fails; this empty state means the latest successful run "
                "found none under the published rules._",
                "",
                "<details>",
                "<summary>Ranking & eligibility rules</summary>",
                "",
                comparison_rule,
                "",
                "- Canada geographic eligibility required (remote Canada / hybrid / "
                "on-site / province as configured).",
                "- Direct ATS apply URLs only (affiliates excluded).",
                "- Engineering tracks only; listings older than 14 days excluded.",
                "- Fewer than five rows means fewer than five qualified.",
                "",
                "</details>",
                "",
                END_MARKER,
            ]
        )
        return "\n".join(lines)

    lines.extend(
        [
            "| # | Role | Company | Annual base | Location | Verified | Apply |",
            "| -: | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for i, job in enumerate(jobs, start=1):
        salary = format_salary_range(job.salary_min, job.salary_max, job.salary_currency)
        verified = verified_date_label(job.verified_at)
        row = (
            f"| {i} "
            f"| **{_escape_cell(job.title)}** "
            f"| {_escape_cell(job.company)} "
            f"| `{salary}` "
            f"| {_escape_cell(job.eligibility_label)} "
            f"| {verified} "
            f"| [Apply]({job.apply_url}) |"
        )
        lines.append(row)

    lines.extend(
        [
            "",
            "<details>",
            "<summary>Ranking & eligibility rules</summary>",
            "",
            comparison_rule,
            "",
            "- Canada geographic eligibility required (remote Canada / hybrid / "
            "on-site / province as configured).",
            "- Direct ATS apply URLs only (affiliates excluded).",
            "- Engineering tracks only; listings older than 14 days excluded.",
            "- Dates use **Verified YYYY-MM-DD** from discovery `last_seen` "
            "(calendar date only — no same-day marketing labels).",
            "- Fewer than five rows means fewer than five qualified.",
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
    # Ensure new_section includes markers
    if not new_section.startswith(START_MARKER) or not new_section.rstrip().endswith(
        END_MARKER
    ):
        raise ValueError("new_section must include START and END markers")
    return readme_text[:start] + new_section.rstrip() + readme_text[end:]


def update_readme_file(readme_path: Path, jobs: list[ShowcaseJob], *, generated_at: datetime | None = None) -> bool:
    """Write README if the Top Paying section changed. Returns True if written."""
    text = readme_path.read_text(encoding="utf-8")
    section = render_section(jobs, generated_at=generated_at)
    updated = replace_section(text, section)
    if updated == text:
        return False
    readme_path.write_text(updated, encoding="utf-8")
    return True
