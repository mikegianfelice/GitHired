"""Public shortlist export: schema, geo labels, privacy, Pages base-path assets."""

from __future__ import annotations

import json
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from jobseek.public_shortlist.export import (
    PUBLIC_SEARCH,
    assert_public_payload_safe,
    build_public_snapshot,
    select_public_jobs,
    write_public_site,
)

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


def _job(**overrides):
    base = {
        "title": "Senior Software Engineer",
        "company": "ExampleCo",
        "location_raw": "Remote - Canada",
        "description": "Remote in Canada. Python TypeScript. Build platforms." + (" x" * 40),
        "description_complete": 1,
        "url": "https://boards.greenhouse.io/exampleco/jobs/12345",
        "apply_url": "https://boards.greenhouse.io/exampleco/jobs/12345",
        "source": "greenhouse",
        "ats_provider": "greenhouse",
        "first_seen": "2026-11-04T08:00:00Z",
        "last_seen": "2026-11-04T10:00:00Z",
        "salary_min": 150000,
        "salary_max": 180000,
        "salary_currency": "CAD",
        "removed_at": None,
    }
    base.update(overrides)
    return base


class PublicShortlistSelectTests(unittest.TestCase):
    def test_selects_eligible_engineering_jobs(self):
        jobs = select_public_jobs(
            [_job(title="Senior Software Engineer (Python)")],
            limit=10,
            now=NOW,
        )
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertTrue(j.verified)
        self.assertEqual(j.work_arrangement, "remote")
        self.assertEqual(j.remote_scope, "canada")
        self.assertTrue(j.salary_available)
        self.assertTrue(j.discovered_today)
        self.assertIn("Python", j.technologies)

    def test_city_only_canada_eligible_but_arrangement_unspecified(self):
        """City-only locations stay eligible under onsite mode without inventing onsite."""
        jobs = select_public_jobs(
            [
                _job(
                    location_raw="Toronto, Canada",
                    title="Software Engineer",
                    description=(
                        "Join our Toronto engineering team building products. "
                        "Python TypeScript." + (" y" * 40)
                    ),
                    url="https://boards.greenhouse.io/exampleco/jobs/toronto-1",
                    apply_url="https://boards.greenhouse.io/exampleco/jobs/toronto-1",
                )
            ],
            limit=10,
            now=NOW,
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].work_arrangement, "unspecified")

    def test_city_only_explicit_hybrid_description_wins(self):
        jobs = select_public_jobs(
            [
                _job(
                    location_raw="Vancouver, Canada",
                    title="Software Engineer",
                    description=(
                        "This is a hybrid position based in Vancouver. "
                        "Python TypeScript." + (" y" * 40)
                    ),
                    url="https://boards.greenhouse.io/exampleco/jobs/van-1",
                    apply_url="https://boards.greenhouse.io/exampleco/jobs/van-1",
                )
            ],
            limit=10,
            now=NOW,
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].work_arrangement, "hybrid")

    def test_rejects_uncertain_us_remote(self):
        jobs = select_public_jobs(
            [
                _job(
                    location_raw="Remote, USA",
                    title="Software Engineer",
                    description="Remote within the United States only. Python." + (" z" * 40),
                    url="https://boards.greenhouse.io/exampleco/jobs/999",
                    apply_url="https://boards.greenhouse.io/exampleco/jobs/999",
                )
            ],
            limit=10,
            now=NOW,
        )
        self.assertEqual(jobs, [])

    def test_rejects_affiliate_urls(self):
        jobs = select_public_jobs(
            [
                _job(
                    url="https://www.whatjobs.com/job/abc",
                    apply_url="https://www.whatjobs.com/job/abc",
                )
            ],
            limit=10,
            now=NOW,
        )
        self.assertEqual(jobs, [])

    def test_rejects_incomplete_descriptions(self):
        jobs = select_public_jobs(
            [_job(description_complete=0, description="short")],
            limit=10,
            now=NOW,
        )
        self.assertEqual(jobs, [])

    def test_missing_salary_still_eligible(self):
        jobs = select_public_jobs(
            [
                _job(
                    salary_min=None,
                    salary_max=None,
                    salary_currency=None,
                    title="Platform Engineer",
                    url="https://jobs.ashbyhq.com/example/job/abc-123",
                    apply_url="https://jobs.ashbyhq.com/example/job/abc-123",
                )
            ],
            limit=10,
            now=NOW,
        )
        self.assertEqual(len(jobs), 1)
        self.assertFalse(jobs[0].salary_available)

    def test_province_remote_not_labeled_canada_wide(self):
        jobs = select_public_jobs(
            [
                _job(
                    location_raw="Remote - Ontario",
                    title="Senior Backend Engineer",
                    url="https://jobs.lever.co/example/abcdef12-3456-7890-abcd-ef1234567890",
                    apply_url="https://jobs.lever.co/example/abcdef12-3456-7890-abcd-ef1234567890",
                    description="Remote within Ontario, Canada. Python." + (" y" * 40),
                )
            ],
            limit=10,
            now=NOW,
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].remote_scope, "province")
        self.assertEqual(jobs[0].province, "ON")

    def test_stale_jobs_excluded(self):
        jobs = select_public_jobs(
            [_job(last_seen="2025-01-01T00:00:00Z", first_seen="2025-01-01T00:00:00Z")],
            limit=10,
            max_age_days=21,
            now=NOW,
        )
        self.assertEqual(jobs, [])

    def test_off_track_titles_excluded(self):
        jobs = select_public_jobs(
            [
                _job(
                    title="Account Executive",
                    url="https://boards.greenhouse.io/exampleco/jobs/55",
                    apply_url="https://boards.greenhouse.io/exampleco/jobs/55",
                )
            ],
            limit=10,
            now=NOW,
        )
        self.assertEqual(jobs, [])

    def test_discovered_today_false_when_first_seen_older(self):
        jobs = select_public_jobs(
            [_job(first_seen="2026-10-01T00:00:00Z", last_seen="2026-11-03T00:00:00Z")],
            limit=10,
            now=NOW,
        )
        self.assertEqual(len(jobs), 1)
        self.assertFalse(jobs[0].discovered_today)


class PublicShortlistSnapshotTests(unittest.TestCase):
    def test_snapshot_schema_and_privacy(self):
        selected = select_public_jobs([_job()], limit=5, now=NOW)
        snap = build_public_snapshot(selected, generated_at=NOW, limit=300)
        self.assertEqual(snap["schema_version"], 2)
        self.assertEqual(snap["count"], 1)
        self.assertIn("salary_max_cad", snap["jobs"][0])
        self.assertEqual(snap["jobs"][0]["salary_max_cad"], 180000.0)
        self.assertNotIn("description", snap["jobs"][0])
        self.assertNotIn("overall", snap["jobs"][0])
        assert_public_payload_safe(snap)

    def test_usd_salary_max_cad_conversion(self):
        selected = select_public_jobs(
            [
                _job(
                    salary_min=100000,
                    salary_max=120000,
                    salary_currency="USD",
                    url="https://boards.greenhouse.io/exampleco/jobs/888",
                    apply_url="https://boards.greenhouse.io/exampleco/jobs/888",
                )
            ],
            limit=5,
            now=NOW,
        )
        self.assertEqual(len(selected), 1)
        self.assertAlmostEqual(selected[0].salary_max_cad or 0, 120000 * 1.35)
        snap = build_public_snapshot(selected, generated_at=NOW)
        self.assertEqual(snap["usd_to_cad"], 1.35)

    def test_forbidden_fields_rejected(self):
        with self.assertRaises(ValueError):
            assert_public_payload_safe({"jobs": [{"email": "a@b.c"}]})

    def test_preserve_previous_on_empty(self):
        selected = select_public_jobs([_job()], limit=5, now=NOW)
        good = build_public_snapshot(selected, generated_at=NOW)
        empty = build_public_snapshot([], generated_at=NOW)
        with TemporaryDirectory() as tmp:
            site = Path(tmp)
            write_public_site(good, site, preserve_on_empty=True)
            meta = write_public_site(empty, site, preserve_on_empty=True)
            self.assertTrue(meta["preserved_previous"])
            data = json.loads((site / "jobs.json").read_text(encoding="utf-8"))
            self.assertEqual(data["count"], 1)

    def test_malformed_salary_ignored(self):
        jobs = select_public_jobs(
            [_job(salary_min=12, salary_max=20, salary_currency="CAD")],
            limit=5,
            now=NOW,
        )
        self.assertEqual(len(jobs), 1)
        self.assertFalse(jobs[0].salary_available)


class PublicSiteStaticTests(unittest.TestCase):
    def test_site_files_exist(self):
        for name in (
            "index.html",
            "styles.css",
            "app.js",
            "match-engine.js",
            "resume.js",
            "jobs.json",
            ".nojekyll",
        ):
            self.assertTrue((SITE / name).is_file(), name)

    def test_find_my_matches_nav_present(self):
        html = (SITE / "index.html").read_text(encoding="utf-8")
        self.assertIn("Find My Matches", html)
        self.assertIn("Minimum salary (CAD)", html)
        self.assertIn("Your résumé stays in this browser", html)
        self.assertIn("match-engine.js", html)
        self.assertIn("resume.js", html)

    def test_browse_filters_are_multiselect(self):
        html = (SITE / "index.html").read_text(encoding="utf-8")
        js = (SITE / "app.js").read_text(encoding="utf-8")
        for name in ("province", "arrangement", "seniority"):
            self.assertIn(f'data-filter="{name}"', html)
            self.assertIn(f"filter-{name}-panel", html)
            self.assertIn('aria-multiselectable="true"', html)
        self.assertIn("provinces:", js)
        self.assertIn("arrangements:", js)
        self.assertIn("seniorities:", js)
        self.assertNotIn('id="filter-province"', html)
        self.assertNotIn('id="filter-arrangement"', html)
        self.assertNotIn('id="filter-seniority"', html)

    def test_relative_assets_for_github_pages_base_path(self):
        html = (SITE / "index.html").read_text(encoding="utf-8")
        js = (SITE / "app.js").read_text(encoding="utf-8")
        # Relative href/src so /GitHired/ project Pages resolves correctly
        # Cache-busting query strings are allowed (styles.css?v=…).
        self.assertRegex(html, r'href="styles\.css(\?[^"]*)?"')
        self.assertRegex(html, r'src="app\.js(\?[^"]*)?"')
        self.assertNotIn('href="/styles.css"', html)
        self.assertIn("new URL(name, window.location.href)", js)
        self.assertIn("GitHiredPublic", js)

    def test_placeholder_jobs_json_safe(self):
        data = json.loads((SITE / "jobs.json").read_text(encoding="utf-8"))
        assert_public_payload_safe(data)
        self.assertEqual(data["count"], len(data["jobs"]))

    def test_public_search_has_no_salary_floor_gate(self):
        self.assertEqual((PUBLIC_SEARCH.get("salary") or {}).get("policy"), "none")


class PublicExportScriptSmokeTests(unittest.TestCase):
    def test_script_exports_fixture(self):
        import subprocess
        import sys

        fixture = [
            _job(
                url="https://boards.greenhouse.io/acme/jobs/777",
                apply_url="https://boards.greenhouse.io/acme/jobs/777",
            )
        ]
        with TemporaryDirectory() as tmp:
            jobs_path = Path(tmp) / "jobs.json"
            site = Path(tmp) / "site"
            site.mkdir()
            jobs_path.write_text(json.dumps(fixture), encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "export_public_shortlist.py"),
                    "--jobs-json",
                    str(jobs_path),
                    "--site-dir",
                    str(site),
                    "--limit",
                    "10",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads((site / "jobs.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(out["count"], 1)


if __name__ == "__main__":
    unittest.main()
