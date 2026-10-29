"""Tests for README top-paying showcase selection and refresh."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from jobseek.showcase.readme import (
    END_MARKER,
    START_MARKER,
    render_section,
    replace_section,
    update_readme_file,
)
from jobseek.showcase.refresh import refresh_readme
from jobseek.showcase.top_paying import (
    ShowcaseJob,
    annualize_for_rank,
    format_salary_range,
    is_valid_apply_url,
    select_top_paying_jobs,
    verified_date_label,
)


def _job(**kwargs):
    base = {
        "title": "Senior Software Engineer",
        "company": "Acme",
        "salary_min": 150000,
        "salary_max": 180000,
        "salary_currency": "CAD",
        "location_raw": "Remote, Canada",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/1",
        "url": "https://boards.greenhouse.io/acme/jobs/1",
        "last_seen": "2026-10-28T12:00:00Z",
        "source": "greenhouse",
        "removed_at": None,
    }
    base.update(kwargs)
    return base


NOW = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)


class TestSalaryNormalization:
    def test_cad_annual_high(self):
        assert annualize_for_rank(salary_min=100_000, salary_max=150_000, currency="CAD") == 150_000

    def test_usd_converted_with_documented_fx(self):
        assert annualize_for_rank(
            salary_min=100_000, salary_max=100_000, currency="USD", fx_usd_cad=1.35
        ) == pytest.approx(135_000)

    def test_rejects_hourly_noise(self):
        assert annualize_for_rank(salary_min=45, salary_max=55, currency="CAD") is None

    def test_rejects_unknown_currency(self):
        assert annualize_for_rank(salary_min=100_000, salary_max=120_000, currency="EUR") is None

    def test_format_range(self):
        assert format_salary_range(140_000, 180_000, "CAD") == "CAD 140,000–180,000"
        assert format_salary_range(200_000, 200_000, "USD") == "USD 200,000"


class TestLinkValidation:
    def test_accepts_direct_ats(self):
        assert is_valid_apply_url("https://jobs.lever.co/wattpad/abc/apply")
        assert is_valid_apply_url("https://boards.greenhouse.io/x/jobs/1")

    def test_rejects_affiliate(self):
        # WhatJobs-style affiliate hosts are classified as affiliate
        assert not is_valid_apply_url("https://www.whatjobs.com/jobs/foo")

    def test_rejects_empty_and_non_http(self):
        assert not is_valid_apply_url(None)
        assert not is_valid_apply_url("")
        assert not is_valid_apply_url("ftp://example.com/x")
        assert not is_valid_apply_url("not-a-url")


class TestDateLabeling:
    def test_never_says_today(self):
        label = verified_date_label("2026-10-29", today=NOW)
        assert "today" not in label.casefold()
        assert label == "Verified 2026-10-29"

    def test_section_never_says_discovered_today(self):
        jobs = [
            ShowcaseJob(
                title="Senior Software Engineer",
                company="Acme",
                salary_min=150000,
                salary_max=180000,
                salary_currency="CAD",
                location_raw="Remote, Canada",
                eligibility_label="Remote, Canada",
                apply_url="https://boards.greenhouse.io/acme/jobs/1",
                verified_at="2026-10-29",
                source="greenhouse",
                rank_cad=180000,
            )
        ]
        md = render_section(jobs, generated_at=NOW)
        # Must not market freshness with a "Discovered today" label
        assert "discovered today" not in md.casefold()
        assert "| Verified 2026-10-29 |" in md or "Verified 2026-10-29" in md
        assert "Last refreshed:" in md


class TestRanking:
    def test_ranks_by_cad_comparable_high(self):
        rows = [
            _job(company="Low", salary_min=100_000, salary_max=120_000, salary_currency="CAD"),
            _job(
                company="USDHigh",
                salary_min=200_000,
                salary_max=200_000,
                salary_currency="USD",
                apply_url="https://jobs.lever.co/usd/1",
            ),
            _job(
                company="CadHigh",
                salary_min=240_000,
                salary_max=280_000,
                salary_currency="CAD",
                apply_url="https://jobs.ashbyhq.com/cad/1",
                title="Head of Engineering",
            ),
        ]
        selected = select_top_paying_jobs(rows, limit=5, now=NOW)
        assert [j.company for j in selected] == ["CadHigh", "USDHigh", "Low"]

    def test_excludes_geo_ineligible_and_stale_and_removed(self):
        rows = [
            _job(company="USOnly", location_raw="Remote - US"),
            _job(company="Stale", last_seen="2026-01-01T00:00:00Z"),
            _job(company="Gone", removed_at="2026-10-20T00:00:00Z"),
            _job(company="Ok", salary_max=160_000),
        ]
        selected = select_top_paying_jobs(rows, limit=5, max_age_days=14, now=NOW)
        assert [j.company for j in selected] == ["Ok"]

    def test_excludes_undisclosed_and_non_engineering(self):
        rows = [
            _job(company="NoPay", salary_min=None, salary_max=None),
            _job(company="FP&A", title="Director, Commercial FP&A"),
            _job(company="Eng", title="Senior Software Engineer", salary_max=170_000),
        ]
        # salary_min None with salary_max None — fix row shape
        rows[0] = _job(company="NoPay")
        rows[0]["salary_min"] = None
        rows[0]["salary_max"] = None
        selected = select_top_paying_jobs(rows, limit=5, now=NOW)
        assert [j.company for j in selected] == ["Eng"]

    def test_dedupes_company_title(self):
        rows = [
            _job(company="Dup", salary_max=170_000, apply_url="https://jobs.lever.co/a/1"),
            _job(company="Dup", salary_max=190_000, apply_url="https://jobs.lever.co/a/2"),
        ]
        selected = select_top_paying_jobs(rows, limit=5, now=NOW)
        assert len(selected) == 1
        assert selected[0].salary_max == 190_000

    def test_returns_fewer_than_five(self):
        rows = [_job(company="Only", salary_max=155_000)]
        selected = select_top_paying_jobs(rows, limit=5, now=NOW)
        assert len(selected) == 1


class TestReadmeReplacement:
    def test_replace_section_only(self):
        original = (
            "# Title\n\nIntro\n\n"
            f"{START_MARKER}\nold\n{END_MARKER}\n\n"
            "## Docs\nkeep me\n"
        )
        new = render_section([], generated_at=NOW)
        updated = replace_section(original, new)
        assert "## Docs\nkeep me" in updated
        assert "Intro" in updated
        assert "\nold\n" not in updated
        assert START_MARKER in updated and END_MARKER in updated

    def test_missing_markers_raise(self):
        with pytest.raises(ValueError, match="markers"):
            replace_section("# no markers\n", render_section([]))

    def test_update_readme_file_idempotent(self, tmp_path: Path):
        jobs = [
            ShowcaseJob(
                title="Senior Software Engineer",
                company="Acme",
                salary_min=150000,
                salary_max=180000,
                salary_currency="CAD",
                location_raw="Toronto, Ontario",
                eligibility_label="Toronto, Ontario",
                apply_url="https://boards.greenhouse.io/acme/jobs/1",
                verified_at="2026-10-28",
                source="greenhouse",
                rank_cad=180000,
            )
        ]
        readme = tmp_path / "README.md"
        readme.write_text(
            f"# X\n\n{START_MARKER}\nplaceholder\n{END_MARKER}\n\n## Tail\n",
            encoding="utf-8",
        )
        assert update_readme_file(readme, jobs, generated_at=NOW) is True
        assert update_readme_file(readme, jobs, generated_at=NOW) is False
        text = readme.read_text(encoding="utf-8")
        assert "Acme" in text and "## Tail" in text
        assert "`CAD 150,000–180,000`" in text


class TestFailureHandling:
    def test_preserves_prior_on_empty_selection(self, tmp_path: Path):
        snap = tmp_path / "snap.json"
        readme = tmp_path / "README.md"
        prior_jobs = [
            ShowcaseJob(
                title="Senior Software Engineer",
                company="Kept",
                salary_min=150000,
                salary_max=180000,
                salary_currency="CAD",
                location_raw="Canada",
                eligibility_label="Canada",
                apply_url="https://boards.greenhouse.io/kept/jobs/1",
                verified_at="2026-10-20",
                source="greenhouse",
                rank_cad=180000,
            )
        ]
        from jobseek.showcase.top_paying import snapshot_payload
        from jobseek.showcase.refresh import write_snapshot

        prior = snapshot_payload(
            prior_jobs,
            generated_at=datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc),
        )
        write_snapshot(snap, prior)
        readme.write_text(
            f"# H\n{START_MARKER}\nKept section\n{END_MARKER}\n",
            encoding="utf-8",
        )
        result = refresh_readme(
            readme_path=readme,
            snapshot_path=snap,
            jobs_rows=[],  # empty → no qualifying jobs
            now=NOW,
        )
        assert result["preserved_prior"] is True
        assert result["wrote_snapshot"] is False
        assert result["count"] == 1
        assert "2026-10-20" in result["generated_at"]
        assert "Kept section" in readme.read_text(encoding="utf-8")

    def test_preserves_prior_on_selection_exception(self, tmp_path: Path, monkeypatch):
        snap = tmp_path / "snap.json"
        readme = tmp_path / "README.md"
        from jobseek.showcase.top_paying import snapshot_payload
        from jobseek.showcase.refresh import write_snapshot
        import jobseek.showcase.refresh as refresh_mod

        prior = snapshot_payload(
            [
                ShowcaseJob(
                    title="Senior Software Engineer",
                    company="Prior",
                    salary_min=100000,
                    salary_max=120000,
                    salary_currency="CAD",
                    location_raw="Canada",
                    eligibility_label="Canada",
                    apply_url="https://jobs.lever.co/prior/1",
                    verified_at="2026-10-15",
                    source="lever",
                    rank_cad=120000,
                )
            ],
            generated_at=datetime(2026, 10, 15, tzinfo=timezone.utc),
        )
        write_snapshot(snap, prior)
        readme.write_text(f"{START_MARKER}\nx\n{END_MARKER}\n", encoding="utf-8")

        def boom(*_a, **_k):
            raise RuntimeError("db exploded")

        monkeypatch.setattr(refresh_mod, "select_top_paying_jobs", boom)
        result = refresh_readme(
            readme_path=readme,
            snapshot_path=snap,
            jobs_rows=[_job()],
            now=NOW,
        )
        assert result["ok"] is False
        assert result["preserved_prior"] is True
        assert "2026-10-15" in result["generated_at"]

    def test_empty_overwrite_when_allowed(self, tmp_path: Path):
        snap = tmp_path / "snap.json"
        readme = tmp_path / "README.md"
        from jobseek.showcase.top_paying import snapshot_payload
        from jobseek.showcase.refresh import write_snapshot

        write_snapshot(
            snap,
            snapshot_payload(
                [
                    ShowcaseJob(
                        title="Senior Software Engineer",
                        company="Old",
                        salary_min=100000,
                        salary_max=110000,
                        salary_currency="CAD",
                        location_raw="Canada",
                        eligibility_label="Canada",
                        apply_url="https://jobs.lever.co/old/1",
                        verified_at="2026-10-01",
                        source="lever",
                        rank_cad=110000,
                    )
                ],
                generated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            ),
        )
        readme.write_text(f"# R\n{START_MARKER}\nold\n{END_MARKER}\n", encoding="utf-8")
        result = refresh_readme(
            readme_path=readme,
            snapshot_path=snap,
            jobs_rows=[],
            now=NOW,
            allow_empty_overwrite=True,
        )
        assert result["wrote_snapshot"] is True
        assert result["count"] == 0
        assert "No qualifying" in readme.read_text(encoding="utf-8")
