/**
 * remote_scope ranking + exclude_global_remote filter behavior.
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { test, before } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const bundlePath = join(root, "test/.cache/search.rank.bundle.mjs");

let searchJobs;
let remoteScopeRank;
let parseSearchFilters;

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
  searchJobs = mod.searchJobs;
  remoteScopeRank = mod.remoteScopeRank;
  parseSearchFilters = mod.parseSearchFilters;
});

function job(overrides) {
  return {
    id: overrides.id || "j1",
    title: overrides.title || "Software Engineer",
    company: overrides.company || "Acme",
    location: overrides.location || "Remote",
    province: overrides.province ?? null,
    work_arrangement: overrides.work_arrangement || "remote",
    remote_scope: overrides.remote_scope || "unspecified",
    seniority: "senior",
    track: "software_engineering",
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    salary_available: false,
    salary_max_cad: null,
    salary_period: null,
    salary_kind: "none",
    apply_url: "https://example.com/jobs/1",
    verified: true,
    first_seen: "2026-11-01",
    last_verified: "2026-11-04",
    discovered_today: false,
    technologies: ["Python"],
    source: "greenhouse",
  };
}

function snapshot(jobs) {
  return {
    schema_version: 1,
    dataset_id: "test",
    generated_at: "2026-11-04T00:00:00Z",
    source: "test",
    limit: 100,
    count: jobs.length,
    usd_to_cad: 1.35,
    repo_url: "https://example.com",
    salary_policy: {},
    eligibility: {},
    stats: {
      total_jobs: jobs.length,
      total_companies: 1,
      remote_jobs: jobs.length,
      jobs_with_advertised_salary: 0,
    },
    companies: [],
    disclaimer: "",
    jobs,
  };
}

test("remoteScopeRank puts canada/province above global", () => {
  assert.ok(remoteScopeRank(job({ remote_scope: "canada" })) < remoteScopeRank(job({ remote_scope: "global" })));
  assert.ok(remoteScopeRank(job({ remote_scope: "province", province: "ON" })) < remoteScopeRank(job({ remote_scope: "global" })));
});

test("searchJobs ranks canada before global and exposes remote_scope", () => {
  const snap = snapshot([
    job({ id: "g", company: "WorldCo", remote_scope: "global", title: "Z Engineer" }),
    job({ id: "c", company: "CanadaCo", remote_scope: "canada", location: "Remote - Canada", title: "A Engineer" }),
  ]);
  const result = searchJobs(snap, parseSearchFilters(new URLSearchParams("limit=10")));
  assert.equal(result.jobs[0].id, "c");
  assert.equal(result.jobs[1].id, "g");
  assert.equal(result.jobs[0].remote_scope, "canada");
  assert.equal(result.jobs[1].remote_scope, "global");
});

test("exclude_global_remote drops global jobs", () => {
  const snap = snapshot([
    job({ id: "g", remote_scope: "global" }),
    job({ id: "c", remote_scope: "canada", location: "Remote - Canada" }),
  ]);
  const result = searchJobs(
    snap,
    parseSearchFilters(new URLSearchParams("exclude_global_remote=true&limit=10")),
  );
  assert.equal(result.total, 1);
  assert.equal(result.jobs[0].id, "c");
});

test("remote_scope=global filter returns only global", () => {
  const snap = snapshot([
    job({ id: "g", remote_scope: "global" }),
    job({ id: "c", remote_scope: "canada", location: "Remote - Canada" }),
  ]);
  const result = searchJobs(snap, parseSearchFilters(new URLSearchParams("remote_scope=global")));
  assert.equal(result.total, 1);
  assert.equal(result.jobs[0].id, "g");
});
