/**
 * Match / skill / freshness quality regressions from MCP production QA.
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
const matchBundle = join(root, "test/.cache/match_quality.bundle.mjs");
const searchBundle = join(root, "test/.cache/search_quality.bundle.mjs");

let matchProfile;
let roleFamilyScore;
let withLiveDiscoveredToday;

before(async () => {
  mkdirSync(dirname(matchBundle), { recursive: true });
  const buildMatch = spawnSync(
    "npx",
    [
      "--yes",
      "esbuild",
      "src/match.ts",
      "--bundle",
      "--platform=neutral",
      "--format=esm",
      `--outfile=${matchBundle}`,
    ],
    { cwd: root, encoding: "utf8" },
  );
  if (buildMatch.status !== 0) {
    throw new Error(`esbuild match failed: ${buildMatch.stderr || buildMatch.stdout}`);
  }
  const buildSearch = spawnSync(
    "npx",
    [
      "--yes",
      "esbuild",
      "src/search.ts",
      "--bundle",
      "--platform=neutral",
      "--format=esm",
      `--outfile=${searchBundle}`,
    ],
    { cwd: root, encoding: "utf8" },
  );
  if (buildSearch.status !== 0) {
    throw new Error(`esbuild search failed: ${buildSearch.stderr || buildSearch.stdout}`);
  }
  const mod = await import(pathToFileURL(matchBundle).href + `?t=${Date.now()}`);
  matchProfile = mod.matchProfile;
  roleFamilyScore = mod.roleFamilyScore;
  const searchMod = await import(pathToFileURL(searchBundle).href + `?t=${Date.now()}`);
  withLiveDiscoveredToday = searchMod.withLiveDiscoveredToday;
});

function snap(jobs) {
  return {
    schema_version: 2,
    dataset_id: "test",
    generated_at: "2026-11-23T12:00:00Z",
    usd_to_cad: 1.35,
    jobs,
    companies: [],
    stats: {},
  };
}

function job(overrides = {}) {
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
    salary_min: 160000,
    salary_max: 190000,
    salary_currency: "CAD",
    salary_available: true,
    salary_max_cad: 190000,
    technologies: ["Python", "SQL", "Spark", "Databricks", "AWS"],
    apply_url: "https://example.com/apply",
    last_verified: "2026-11-23",
    first_seen: "2026-11-23",
    discovered_today: true,
    verified: true,
    description_excerpt: "",
    ...overrides,
  };
}

const DE_PROFILE = {
  preferred_roles: [
    "Senior Data Engineer",
    "AI Engineer",
    "Forward Deployed Engineer",
    "Solutions Architect",
    "Data Platform Engineer",
  ],
  years_experience: 5,
  skills: [
    "Python",
    "SQL",
    "Databricks",
    "PySpark",
    "Spark",
    "Snowflake",
    "AWS",
    "Terraform",
    "ETL",
    "CI/CD",
    "RAG",
    "LLMs",
    "MCP",
  ],
  work_arrangements: ["remote", "hybrid"],
  preferred_locations: ["Canada", "Ontario", "ON"],
  minimum_salary: 150000,
  salary_mode: "flexible",
  seniority: "senior",
  limit: 10,
};

test("AI Engineer does not match every Software/DevOps engineer title", () => {
  assert.ok(roleFamilyScore("Senior AI Engineer", "AI Engineer") >= 0.6);
  assert.ok(roleFamilyScore("Forward Deployed AI Engineer", "AI Engineer") >= 0.6);
  assert.ok(roleFamilyScore("Senior Full Stack Engineer", "AI Engineer") < 0.6);
  assert.ok(roleFamilyScore("Senior Infrastructure/ DevOps Engineer", "AI Engineer") < 0.6);
  assert.ok(roleFamilyScore("Senior Site Reliability Engineer", "Senior Data Engineer") < 0.6);
});

test("Data Platform Engineer still matches data platform titles", () => {
  assert.ok(roleFamilyScore("Senior Data Platform Engineer", "Data Platform Engineer") >= 0.6);
  assert.ok(roleFamilyScore("Senior Data Engineer", "Data Platform Engineer") >= 0.6);
});

test("multi-role DE/AI/FDE profile ranks relevant titles above DevOps/Full Stack", () => {
  const jobs = [
    job({
      id: "devops",
      title: "Senior Infrastructure/ DevOps Engineer",
      company: "Lazer",
      track: "devops_sre",
      technologies: ["Python", "Go", "SQL", "Terraform", "AWS", "CI/CD", "MCP"],
      salary_available: false,
      salary_min: null,
      salary_max: null,
      salary_max_cad: null,
    }),
    job({
      id: "fullstack",
      title: "Senior Full Stack Engineer",
      company: "Procurify",
      track: "software_engineering",
      technologies: ["Python", "AWS", "Terraform", "CI/CD"],
      salary_available: false,
      salary_min: null,
      salary_max: null,
      salary_max_cad: null,
    }),
    job({
      id: "fde",
      title: "Forward Deployed Engineer",
      company: "Spellbook",
      track: "forward_deployed",
      technologies: ["TypeScript", "AWS", "LLM", "RAG"],
      salary_min: 180000,
      salary_max: 225000,
      salary_max_cad: 225000,
    }),
    job({
      id: "de",
      title: "Senior Data Engineer - Data Performance and Tooling",
      company: "Jane App",
      track: "data_engineering",
      technologies: ["SQL", "Spark", "Snowflake", "AWS", "Terraform"],
      salary_min: 160000,
      salary_max: 190000,
      salary_max_cad: 190000,
    }),
    job({
      id: "lakehouse",
      title: "Senior Software Engineer, Backend (Lakehouse Infra)",
      company: "Affirm",
      track: "software_engineering",
      technologies: ["Python", "Spark", "Snowflake", "AWS", "Terraform"],
      salary_min: 153000,
      salary_max: 213000,
      salary_max_cad: 213000,
    }),
    job({
      id: "sre",
      title: "Senior Site Reliability Engineer - (Canada-Remote)",
      company: "ClickHouse",
      track: "devops_sre",
      technologies: ["Python", "SQL", "Terraform", "AWS"],
      salary_min: 150000,
      salary_max: 230000,
      salary_max_cad: 230000,
    }),
  ];
  const result = matchProfile(snap(jobs), DE_PROFILE);
  const ids = result.matches.map((m) => m.id);
  assert.ok(ids.includes("fde") || ids.includes("de") || ids.includes("lakehouse"));
  assert.ok(!ids.includes("devops"), `DevOps should not rank when role gate is tight: ${ids}`);
  assert.ok(!ids.includes("fullstack"), `Full Stack should not pass AI/DE family gate: ${ids}`);
  assert.ok(!ids.includes("sre"), `SRE should not pass DE family gate: ${ids}`);
  const top = result.matches[0];
  assert.ok(["fde", "de", "lakehouse"].includes(top.id), top.title);
});

test("confirmed skills require job tags — PySpark does not match Python-only listings", () => {
  const jobs = [
    job({
      id: "pyonly",
      title: "Senior Data Engineer",
      technologies: ["Python", "AWS", "Terraform"],
    }),
  ];
  const result = matchProfile(snap(jobs), {
    ...DE_PROFILE,
    preferred_roles: ["Senior Data Engineer"],
    skills: ["PySpark", "Python"],
  });
  assert.equal(result.matches.length, 1);
  assert.ok(result.matches[0].matching_skills.includes("python"));
  assert.ok(!result.matches[0].matching_skills.includes("pyspark"));
});

test("substring skills are not confirmed from prose", () => {
  const jobs = [
    job({
      id: "noise",
      title: "Senior Data Engineer",
      technologies: ["Python", "SQL"],
      // "rag" must not match inside "storage"; bare handbook text has no MCP token.
      description_excerpt:
        "We store aggregates in cold storage regions; the team handbook covers onboarding.",
    }),
  ];
  const result = matchProfile(snap(jobs), {
    preferred_roles: ["Senior Data Engineer"],
    skills: ["RAG", "MCP", "Python"],
    work_arrangements: ["remote"],
    limit: 5,
  });
  assert.equal(result.matches.length, 1);
  assert.deepEqual(
    result.matches[0].matching_skills.filter((s) => s === "rag" || s === "mcp"),
    [],
  );
  assert.ok(result.matches[0].matching_skills.includes("python"));
});

test("ten diverse personas produce matches without DevOps false opens for DE intent", () => {
  const personas = [
    {
      name: "de",
      preferred_roles: ["Senior Data Engineer"],
      skills: ["Python", "SQL", "Spark"],
    },
    {
      name: "ai",
      preferred_roles: ["AI Engineer"],
      skills: ["Python", "PyTorch", "LLM"],
    },
    {
      name: "fde",
      preferred_roles: ["Forward Deployed Engineer"],
      skills: ["Python", "AWS"],
    },
    {
      name: "backend",
      preferred_roles: ["Backend Engineer"],
      skills: ["Go", "Kubernetes"],
    },
    {
      name: "frontend",
      preferred_roles: ["Frontend Engineer"],
      skills: ["React", "TypeScript"],
    },
    {
      name: "devops",
      preferred_roles: ["DevOps Engineer"],
      skills: ["Terraform", "Kubernetes", "AWS"],
    },
    {
      name: "analytics",
      preferred_roles: ["Analytics Engineer"],
      skills: ["SQL", "dbt", "Snowflake"],
    },
    {
      name: "architect",
      preferred_roles: ["Solutions Architect"],
      skills: ["AWS", "Azure"],
    },
    {
      name: "junior",
      preferred_roles: ["Junior Software Engineer"],
      skills: ["Python"],
      seniority: "junior",
      years_experience: 1,
    },
    {
      name: "staff",
      preferred_roles: ["Staff Software Engineer"],
      skills: ["Python", "Go"],
      seniority: "staff",
      years_experience: 9,
    },
  ];

  const slate = [
    job({
      id: "de",
      title: "Senior Data Engineer",
      track: "data_engineering",
      technologies: ["Python", "SQL", "Spark"],
    }),
    job({
      id: "ai",
      title: "Senior AI Engineer",
      track: "ai_engineering",
      technologies: ["Python", "PyTorch", "LLM"],
    }),
    job({
      id: "fde",
      title: "Forward Deployed Engineer",
      track: "forward_deployed",
      technologies: ["Python", "AWS"],
    }),
    job({
      id: "be",
      title: "Backend Engineer",
      track: "software_engineering",
      seniority: "mid",
      technologies: ["Go", "Kubernetes"],
    }),
    job({
      id: "fe",
      title: "Frontend Engineer",
      track: "software_engineering",
      seniority: "mid",
      technologies: ["React", "TypeScript"],
    }),
    job({
      id: "do",
      title: "DevOps Engineer",
      track: "devops_sre",
      seniority: "mid",
      technologies: ["Terraform", "Kubernetes", "AWS"],
    }),
    job({
      id: "ae",
      title: "Analytics Engineer",
      track: "analytics_engineering",
      seniority: "mid",
      technologies: ["SQL", "dbt", "Snowflake"],
    }),
    job({
      id: "sa",
      title: "Solutions Architect",
      track: "platform_engineering",
      technologies: ["AWS", "Azure"],
    }),
    job({
      id: "jr",
      title: "Junior Software Engineer",
      track: "software_engineering",
      seniority: "junior",
      technologies: ["Python"],
      salary_min: 70000,
      salary_max: 90000,
      salary_max_cad: 90000,
    }),
    job({
      id: "st",
      title: "Staff Software Engineer",
      track: "software_engineering",
      seniority: "staff",
      technologies: ["Python", "Go"],
      salary_min: 200000,
      salary_max: 250000,
      salary_max_cad: 250000,
    }),
  ];

  const relevant = {
    de: ["de"],
    ai: ["ai"],
    fde: ["fde"],
    backend: ["be"],
    frontend: ["fe"],
    devops: ["do"],
    analytics: ["ae"],
    architect: ["sa"],
    junior: ["jr"],
    staff: ["st"],
  };

  for (const p of personas) {
    const result = matchProfile(snap(slate), {
      preferred_roles: p.preferred_roles,
      skills: p.skills,
      years_experience: p.years_experience ?? 5,
      seniority: p.seniority || "senior",
      work_arrangements: ["remote", "hybrid"],
      minimum_salary: p.name === "junior" ? 65000 : 100000,
      salary_mode: "flexible",
      limit: 5,
    });
    assert.ok(result.matches.length >= 1, p.name);
    const ids = result.matches.map((m) => m.id);
    const gold = relevant[p.name];
    const p5 = ids.slice(0, 5).filter((id) => gold.includes(id)).length / Math.min(5, gold.length);
    assert.ok(p5 >= 1, `${p.name} Precision@5 against gold ${gold}: ${ids}`);
    if (p.name === "de") {
      assert.equal(result.matches[0].id, "de");
      assert.ok(!result.matches.some((m) => m.id === "do"));
    }
    if (p.name === "ai") {
      assert.ok(result.matches.some((m) => m.id === "ai"));
      assert.ok(!result.matches.some((m) => m.id === "do" || m.id === "fe"));
    }
  }
});

test("discovered_today is computed live from first_seen", () => {
  const old = job({ first_seen: "2026-11-23", discovered_today: true });
  const live = withLiveDiscoveredToday(old, new Date("2026-11-25T15:00:00Z"));
  assert.equal(live.discovered_today, false);
  const same = withLiveDiscoveredToday(old, new Date("2026-11-23T15:00:00Z"));
  assert.equal(same.discovered_today, true);
});

test("freshness threshold marks >48h datasets stale without raising the bar", () => {
  function freshness(generatedAt, nowMs, staleAfterHours = 48) {
    const ageHours = (nowMs - Date.parse(generatedAt)) / 3_600_000;
    return {
      fresh: ageHours <= staleAfterHours,
      age_hours: Math.round(ageHours * 10) / 10,
      stale_after_hours: staleAfterHours,
    };
  }
  const gen = "2026-11-23T12:05:12Z";
  const now = Date.parse("2026-11-25T15:13:00Z");
  const f = freshness(gen, now, 48);
  assert.equal(f.fresh, false);
  assert.ok(f.age_hours > 48);
  assert.equal(f.stale_after_hours, 48);
});
