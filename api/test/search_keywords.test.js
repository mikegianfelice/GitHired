/**
 * Keyword filter must not qualify on description-only hits.
 * Run: npm test (from api/)
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { test, before } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const bundlePath = join(root, "test/.cache/search_keywords.bundle.mjs");

let jobMatchesFilters;

before(async () => {
  mkdirSync(dirname(bundlePath), { recursive: true });
  const build = spawnSync(
    "npx",
    [
      "--yes",
      "esbuild",
      "src/search.ts",
      "--bundle",
      "--platform=neutral",
      "--format=esm",
      `--outfile=${bundlePath}`,
    ],
    { cwd: root, encoding: "utf8" },
  );
  if (build.status !== 0) {
    throw new Error(`esbuild failed: ${build.stderr || build.stdout}`);
  }
  const mod = await import(pathToFileURL(bundlePath).href + `?t=${Date.now()}`);
  jobMatchesFilters = mod.jobMatchesFilters;
});

function job(overrides = {}) {
  return {
    id: "x",
    title: "Senior Security Engineer",
    company: "ExampleCo",
    location: "Toronto, ON",
    province: "ON",
    work_arrangement: "hybrid",
    remote_scope: "local",
    seniority: "senior",
    track: "security_engineering",
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    salary_available: false,
    salary_max_cad: null,
    apply_url: "https://boards.greenhouse.io/example/jobs/1",
    verified: true,
    first_seen: "2026-11-01",
    last_verified: "2026-11-01",
    discovered_today: false,
    technologies: ["Go", "Kubernetes"],
    source: "greenhouse",
    description_excerpt:
      "We build data pipelines and support data engineers across teams using Spark and Python.",
    ...overrides,
  };
}

test("keyword filter excludes description-only matches for role-family queries", () => {
  const filters = { q: "senior data engineer", limit: 20, sort: "relevance" };
  const falsePositive = job();
  const truePositive = job({
    title: "Senior Data Engineer",
    track: "data_engineering",
    technologies: ["Python", "Spark"],
    description_excerpt: "Design and scale data pipelines in PySpark and SQL.",
  });
  assert.equal(jobMatchesFilters(falsePositive, filters, 1.35), false);
  assert.equal(jobMatchesFilters(truePositive, filters, 1.35), true);
});

test("keyword filter still matches company and skill queries", () => {
  const companyHit = job({ company: "Cohere", title: "Software Engineer" });
  assert.equal(
    jobMatchesFilters(companyHit, { q: "Cohere", limit: 20, sort: "relevance" }, 1.35),
    true,
  );
  const skillHit = job({
    title: "Platform Engineer",
    technologies: ["PySpark", "Airflow"],
  });
  assert.equal(
    jobMatchesFilters(skillHit, { q: "PySpark", limit: 20, sort: "relevance" }, 1.35),
    true,
  );
});
