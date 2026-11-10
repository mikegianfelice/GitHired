"""Regression tests for deterministic technology extraction."""

from __future__ import annotations

import unittest

from jobseek.skills.tech_extract import (
    extract_technologies,
    normalize_skill_label,
    skills_overlap,
)


class ExtractFromDescriptionTests(unittest.TestCase):
    def test_sql_only_in_description(self):
        tech = extract_technologies(
            "Senior Software Engineer",
            "Remote - Canada",
            "You will write complex SQL queries against our warehouse.",
        )
        self.assertIn("SQL", tech)
        self.assertNotIn("Snowflake", tech)

    def test_title_only_still_works(self):
        tech = extract_technologies("Senior Software Engineer (Python)", "Canada", "")
        self.assertIn("Python", tech)

    def test_tsql_and_plsql_normalize_to_sql(self):
        self.assertIn("SQL", extract_technologies("", "", "Strong T-SQL and stored procedures."))
        self.assertIn("SQL", extract_technologies("", "", "Experience with PL/SQL packages."))
        self.assertEqual(normalize_skill_label("T-SQL"), "SQL")
        self.assertEqual(normalize_skill_label("PL/SQL"), "SQL")

    def test_sql_server_postgres_mysql(self):
        tech = extract_technologies(
            "Data Engineer",
            "",
            "SQL Server, PostgreSQL, and MySQL experience required.",
        )
        self.assertIn("SQL", tech)
        self.assertIn("PostgreSQL", tech)
        self.assertIn("MySQL", tech)
        # Platform tags must not invent SQL from postgres alone
        snow_only = extract_technologies("", "", "We use Snowflake for analytics.")
        self.assertIn("Snowflake", snow_only)
        self.assertNotIn("SQL", snow_only)
        pg_only = extract_technologies("", "", "Experience with PostgreSQL preferred.")
        self.assertIn("PostgreSQL", pg_only)
        self.assertNotIn("SQL", pg_only)

    def test_multiple_technologies(self):
        tech = extract_technologies(
            "Data Engineer",
            "Remote",
            "Python, PySpark, Databricks, Snowflake, dbt, Airflow, and Kafka on AWS and Azure.",
        )
        for label in (
            "Python",
            "PySpark",
            "Spark",
            "Databricks",
            "Snowflake",
            "dbt",
            "Airflow",
            "Kafka",
            "AWS",
            "Azure",
        ):
            self.assertIn(label, tech)

    def test_case_insensitive(self):
        tech = extract_technologies("", "", "PYTHON and sql and DaTaBrIcKs and SNOWFLAKE")
        self.assertIn("Python", tech)
        self.assertIn("SQL", tech)
        self.assertIn("Databricks", tech)
        self.assertIn("Snowflake", tech)

    def test_missing_description_honest(self):
        self.assertEqual(extract_technologies("Manager", "Toronto", None), [])
        self.assertEqual(extract_technologies("", "", ""), [])

    def test_html_stripped(self):
        tech = extract_technologies(
            "",
            "",
            "<p>Experience with <b>SQL</b> and <em>Python</em></p>",
        )
        self.assertIn("SQL", tech)
        self.assertIn("Python", tech)

    def test_negated_requirements_skipped(self):
        tech = extract_technologies(
            "Backend Engineer",
            "",
            "No SQL experience required. We do not require Kubernetes. Python is essential.",
        )
        self.assertIn("Python", tech)
        self.assertNotIn("SQL", tech)
        self.assertNotIn("Kubernetes", tech)

    def test_sql_is_not_required(self):
        tech = extract_technologies("", "", "SQL is not required for this role. Use our GUI.")
        self.assertNotIn("SQL", tech)

    def test_snowflake_does_not_imply_sql(self):
        tech = extract_technologies(
            "Analytics Engineer",
            "",
            "Our Tech Stack: Snowflake, dbt, Looker.",
        )
        self.assertIn("Snowflake", tech)
        self.assertIn("dbt", tech)
        self.assertNotIn("SQL", tech)

    def test_databricks_does_not_imply_spark_or_sql(self):
        tech = extract_technologies("", "", "Familiarity with Databricks processing.")
        self.assertEqual(tech, ["Databricks"])

    def test_no_fabricated_matches(self):
        tech = extract_technologies(
            "Product Manager",
            "Remote - Canada",
            "Lead cross-functional teams. Stakeholder management. Roadmaps and prioritization.",
        )
        self.assertEqual(tech, [])

    def test_not_just_is_not_negation(self):
        tech = extract_technologies(
            "",
            "",
            "Hands-on experience applying LLMs — not just prototypes. "
            "Strong proficiency in Python and JavaScript/Node.js.",
        )
        self.assertIn("Python", tech)
        self.assertIn("JavaScript", tech)


class OverlapTests(unittest.TestCase):
    def test_sql_matches_postgresql_job(self):
        matched, unconfirmed = skills_overlap(["SQL", "Rust"], ["PostgreSQL", "Python"])
        self.assertIn("SQL", matched)
        self.assertIn("Rust", unconfirmed)

    def test_unconfirmed_is_not_a_gap_claim(self):
        matched, unconfirmed = skills_overlap(["Kafka"], ["Python"])
        self.assertEqual(matched, [])
        self.assertEqual(unconfirmed, ["Kafka"])

    def test_normalization(self):
        matched, _ = skills_overlap(["t-sql", "node.js"], ["SQL", "Node"])
        self.assertIn("SQL", matched)
        self.assertIn("Node", matched)


class PublicExportIntegrationTests(unittest.TestCase):
    def test_select_public_jobs_reads_description(self):
        from datetime import datetime, timezone

        from jobseek.public_shortlist.export import select_public_jobs

        now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
        jobs = select_public_jobs(
            [
                {
                    "title": "Senior Software Engineer",
                    "company": "ExampleCo",
                    "location_raw": "Remote - Canada",
                    "description": (
                        "Remote in Canada. You have hands-on experience with complex "
                        "SQL queries and production Python. Databricks a plus."
                        + (" x" * 40)
                    ),
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
            ],
            limit=10,
            now=now,
        )
        self.assertEqual(len(jobs), 1)
        self.assertIn("SQL", jobs[0].technologies)
        self.assertIn("Python", jobs[0].technologies)
        self.assertIn("Databricks", jobs[0].technologies)


if __name__ == "__main__":
    unittest.main()
