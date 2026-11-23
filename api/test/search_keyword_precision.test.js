import assert from "node:assert/strict";
import { test } from "node:test";
import { searchJobs } from "../src/search.ts";

const snapshot = {
  schema_version: 1,
  dataset_id: "test1234",
  generated_at: "2026-11-23T00:00:00Z",
  source: "unit-test",
  limit: 1000,
  count: 3,
  usd_to_cad: 1.35,
  repo_url: "https://example.com",
  salary_policy: {},
  eligibility: {},
  stats: { total_jobs: 3, total_companies: 3, remote_jobs: 1, jobs_with_advertised_salary: 2 },
  companies: [],
  disclaimer: "",
  jobs: [
    // True positive: explicit Data Engineer
    {
      id: "A",
      title: "Senior Data Engineer",
      company: "Cohere",
      location: "Toronto, ON",
      province: "ON",
      work_arrangement: "hybrid",
      remote_scope: "local",
      seniority: "senior",
      track: "data_engineering",
      salary_min: 120000,
      salary_max: 180000,
      salary_currency: "CAD",
      salary_available: true,
      salary_max_cad: 180000,
      salary_period: "annual",
      salary_kind: "advertised_base",
      apply_url: "https://example.com/a",
      verified: true,
      first_seen: "2026-11-01",
      last_verified: "2026-11-20",
      discovered_today: false,
      technologies: ["PySpark", "SQL"],
      source: "ashby",
      description_excerpt: "We build data pipelines in PySpark.",
    },
    // False positive previously: generic SWE mentions 'data' in description only
    {
      id: "B",
      title: "Senior Software Engineer, Payments",
      company: "MongoDB",
      location: "Toronto, ON",
      province: "ON",
      work_arrangement: "hybrid",
      remote_scope: "local",
      seniority: "senior",
      track: "software_engineering",
      salary_min: 110000,
      salary_max: 170000,
      salary_currency: "CAD",
      salary_available: true,
      salary_max_cad: 170000,
      salary_period: "annual",
      salary_kind: "advertised_base",
      apply_url: "https://example.com/b",
      verified: true,
      first_seen: "2026-11-01",
      last_verified: "2026-11-20",
      discovered_today: false,
      technologies: ["Go"],
      source: "greenhouse",
      description_excerpt: "You will work with payments data and systems.",
    },
    // Should match by title family overlap ("Data Platform")
    {
      id: "C",
      title: "Senior Software Engineer, Data Platform",
      company: "Terminal",
      location: "Toronto, ON",
      province: "ON",
      work_arrangement: "hybrid",
      remote_scope: "local",
      seniority: "senior",
      track: "software_engineering",
      salary_min: 120000,
      salary_max: 170000,
      salary_currency: "CAD",
      salary_available: true,
      salary_max_cad: 170000,
      salary_period: "annual",
      salary_kind: "advertised_base",
      apply_url: "https://example.com/c",
      verified: true,
      first_seen: "2026-11-01",
      last_verified: "2026-11-20",
      discovered_today: false,
      technologies: ["Python", "SQL"],
      source: "ashby",
      description_excerpt: "Build data platform capabilities.",
    },
  ],
};

test("keyword filter excludes description-only token matches", () => {
  const result = searchJobs(snapshot, {
    q: "senior data engineer",
    location: "Toronto",
    salary_min: 120000,
    sort: "relevance",
    limit: 50,
  });
  const ids = result.jobs.map((j) => j.id);
  // Must include A (exact), may include C (title contains 'Data')
  assert.ok(ids.includes("A"));
  assert.ok(ids.includes("C"));
  // Must exclude B where 'data' only appears in description
  assert.ok(!ids.includes("B"));
});

