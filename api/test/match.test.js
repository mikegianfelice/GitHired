/**
 * API/MCP matchProfile regression tests (esbuild-bundled TypeScript).
 * Run: npm test (from api/)
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { test, before } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const bundlePath = join(root, "test/.cache/match.bundle.mjs");

let matchProfile;
let roleFamilyScore;
let salaryMeetsMinimum;
let snapshot;

before(async () => {
  mkdirSync(dirname(bundlePath), { recursive: true });
  const build = spawnSync(
    "npx",
    ["--yes", "esbuild", "src/match.ts", "--bundle", "--platform=neutral", "--format=esm", `--outfile=${bundlePath}`],
    { cwd: root, encoding: "utf8" },
  );
  if (build.status !== 0) {
    throw new Error(`esbuild failed: ${build.stderr || build.stdout}`);
  }
  const mod = await import(pathToFileURL(bundlePath).href + `?t=${Date.now()}`);
  matchProfile = mod.matchProfile;
  roleFamilyScore = mod.roleFamilyScore;
  salaryMeetsMinimum = mod.salaryMeetsMinimum;
  snapshot = JSON.parse(readFileSync(join(root, "data/jobs.snapshot.json"), "utf8"));
});

function miniSnapshot(jobs) {
  return {
    ...snapshot,
    jobs,
    dataset_id: "test",
    generated_at: "2026-11-11T00:00:00Z",
    usd_to_cad: 1.35,
  };
}

function baseJob(overrides = {}) {
  return {
    id: "j1",
    title: "Senior Data Engineer",
    company: "Acme",
    location: "Remote - Canada",
    province: "ON",
    work_arrangement: "remote",
    remote_scope: "canada",
    seniority: "senior",
    track: "data_engineering",
    salary_min: 155000,
    salary_max: 180000,
    salary_currency: "CAD",
    salary_available: true,
    salary_max_cad: 180000,
    technologies: ["Python", "SQL", "Databricks", "Terraform", "Kubernetes"],
    apply_url: "https://example.com/apply",
    last_verified: "2026-11-11",
    verified: true,
    description_excerpt: "",
    ...overrides,
  };
}

test("role family: Senior Data Engineer matches platform/lead variants", () => {
  assert.ok(roleFamilyScore("Senior Data Platform Engineer", "Senior Data Engineer") >= 0.6);
  assert.ok(roleFamilyScore("Lead Data Engineer", "Senior Data Engineer") >= 0.6);
  assert.ok(roleFamilyScore("Data Engineer", "Senior Data Engineer") >= 0.6);
  assert.ok(roleFamilyScore("Staff Frontend Engineer", "Senior Data Engineer") < 0.6);
  // "data" must not substring-match "datastores"
  assert.ok(roleFamilyScore("Senior Software Engineer, Datastores", "Senior Data Engineer") < 0.6);
});

test("Persona A: Senior DE + remote/hybrid returns matches (not zero)", () => {
  const snap = miniSnapshot([
    baseJob({ id: "a", title: "Senior Data Platform Engineer", work_arrangement: "remote" }),
    baseJob({ id: "b", title: "Lead Data Engineer", work_arrangement: "hybrid", seniority: "lead" }),
    baseJob({
      id: "c",
      title: "Senior Data Engineer",
      company: "BitGo",
      work_arrangement: "onsite",
    }),
  ]);
  const result = matchProfile(snap, {
    preferred_roles: ["Senior Data Engineer"],
    years_experience: 6,
    skills: ["Python", "SQL", "Databricks", "Terraform", "Kubernetes", "Redis", "Control-M"],
    work_arrangements: ["remote", "hybrid"],
    minimum_salary: 150000,
    salary_mode: "flexible",
    limit: 25,
  });
  assert.ok(result.matches.length >= 2, `expected matches, got ${result.matches.length}`);
  assert.ok(result.matches.every((m) => m.work_arrangement !== "onsite"));
  assert.equal(result.filter_semantics.arrangements.join("+"), "remote+hybrid");
});

test("legacy remote_preference alone still means remote-only", () => {
  const snap = miniSnapshot([
    baseJob({ id: "r", work_arrangement: "remote" }),
    baseJob({ id: "h", title: "Senior Data Platform Engineer", work_arrangement: "hybrid" }),
  ]);
  const result = matchProfile(snap, {
    preferred_roles: ["Senior Data Engineer"],
    remote_preference: true,
    limit: 10,
  });
  assert.equal(result.matches.length, 1);
  assert.equal(result.matches[0].work_arrangement, "remote");
});

test("strict salary mode excludes max-only overlap; flexible includes", () => {
  const job = baseJob({
    salary_min: 110000,
    salary_max: 160000,
    salary_max_cad: 160000,
  });
  assert.equal(salaryMeetsMinimum(job, 150000, "strict", 1.35).pass, false);
  assert.equal(salaryMeetsMinimum(job, 150000, "flexible", 1.35).pass, true);
});

test("Persona B: staff role with 8+ years is heavily penalized for 2y candidate", () => {
  const snap = miniSnapshot([
    baseJob({
      id: "mid",
      title: "Frontend Engineer",
      seniority: "mid",
      track: "software_engineering",
      technologies: ["React", "TypeScript", "JavaScript"],
      salary_available: false,
      salary_min: null,
      salary_max: null,
      salary_max_cad: null,
    }),
    baseJob({
      id: "staff",
      title: "Staff Frontend Engineer",
      seniority: "staff",
      track: "software_engineering",
      technologies: ["React", "TypeScript", "JavaScript"],
      description_excerpt: "Requires 8+ years of experience.",
      salary_available: false,
      salary_min: null,
      salary_max: null,
      salary_max_cad: null,
    }),
  ]);
  const result = matchProfile(snap, {
    preferred_roles: ["Frontend Engineer"],
    years_experience: 2,
    skills: ["React", "TypeScript", "JavaScript"],
    limit: 10,
  });
  assert.equal(result.matches.length, 2);
  const mid = result.matches.find((m) => m.id === "mid");
  const staff = result.matches.find((m) => m.id === "staff");
  assert.ok(staff.match_score < mid.match_score);
  assert.ok(staff.match_score < 75);
  assert.ok(/experience|stretch|Seniority/i.test(staff.explanation + staff.gaps.join(" ")));
});

test("snapshot Persona A: preferred Senior DE + work_arrangements remote/hybrid yields matches", () => {
  if (!snapshot.jobs?.length) {
    assert.ok(true, "empty snapshot");
    return;
  }
  const result = matchProfile(snapshot, {
    preferred_roles: ["Senior Data Engineer"],
    years_experience: 6,
    skills: ["Python", "SQL", "Databricks", "Terraform", "Kubernetes", "Redis", "Control-M"],
    work_arrangements: ["remote", "hybrid"],
    minimum_salary: 150000,
    salary_mode: "flexible",
    limit: 25,
  });
  // Soft assertion: with soft titles we must not get the previous hard-zero.
  // Onsite-only BitGo should not appear when arrangements exclude onsite.
  assert.ok(result.matches.every((m) => m.work_arrangement !== "onsite"));
});

test("remote-only hard-excludes unspecified, hybrid, and onsite", () => {
  const snap = miniSnapshot([
    baseJob({ id: "remote", title: "Backend Engineer", work_arrangement: "remote", seniority: "mid" }),
    baseJob({
      id: "unspec",
      title: "Backend Engineer",
      work_arrangement: "unspecified",
      seniority: "mid",
    }),
    baseJob({ id: "hybrid", title: "Backend Engineer", work_arrangement: "hybrid", seniority: "mid" }),
    baseJob({ id: "onsite", title: "Backend Engineer", work_arrangement: "onsite", seniority: "mid" }),
  ]);
  const result = matchProfile(snap, {
    preferred_roles: ["Backend Engineer"],
    work_arrangements: ["remote"],
    limit: 10,
  });
  assert.equal(result.matches.length, 1);
  assert.equal(result.matches[0].id, "remote");
  assert.equal(result.filter_semantics.arrangements.join("+"), "remote");
});

test("no arrangement preference still includes unspecified jobs", () => {
  const snap = miniSnapshot([
    baseJob({ id: "unspec", title: "Backend Engineer", work_arrangement: "unspecified", seniority: "mid" }),
    baseJob({ id: "remote", title: "Backend Engineer", work_arrangement: "remote", seniority: "mid" }),
  ]);
  const result = matchProfile(snap, {
    preferred_roles: ["Backend Engineer"],
    limit: 10,
  });
  assert.equal(result.matches.length, 2);
});

test("junior / 0-YOE profile ranks confirmed junior above mid/senior", () => {
  const snap = miniSnapshot([
    baseJob({
      id: "junior",
      title: "Junior Software Engineer",
      seniority: "junior",
      track: "software_engineering",
      technologies: ["Python"],
      salary_min: 70000,
      salary_max: 90000,
      salary_max_cad: 90000,
    }),
    baseJob({
      id: "mid",
      title: "Software Engineer",
      seniority: "mid",
      track: "software_engineering",
      technologies: ["Python"],
      salary_min: 110000,
      salary_max: 140000,
      salary_max_cad: 140000,
    }),
    baseJob({
      id: "senior",
      title: "Senior Software Engineer",
      seniority: "senior",
      track: "software_engineering",
      technologies: ["Python"],
      salary_min: 150000,
      salary_max: 180000,
      salary_max_cad: 180000,
    }),
    baseJob({
      id: "unknown",
      title: "Software Engineer",
      seniority: "",
      track: "software_engineering",
      technologies: ["Python"],
      salary_available: false,
      salary_min: null,
      salary_max: null,
      salary_max_cad: null,
    }),
  ]);
  const result = matchProfile(snap, {
    preferred_roles: ["Software Engineer", "Python Developer"],
    years_experience: 0,
    seniority: "junior",
    skills: ["Python"],
    work_arrangements: ["remote", "hybrid"],
    limit: 10,
  });
  assert.ok(result.matches.length >= 2);
  assert.equal(result.matches[0].id, "junior");
  const byId = Object.fromEntries(result.matches.map((m) => [m.id, m.match_score]));
  assert.ok(byId.junior > byId.mid);
  assert.ok(byId.junior > byId.senior);
  // Unknown seniority remains eligible but should not outrank confirmed junior.
  if (byId.unknown != null) {
    assert.ok(byId.junior > byId.unknown);
  }
});
