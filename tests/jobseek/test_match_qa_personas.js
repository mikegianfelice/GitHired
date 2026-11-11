/**
 * Regression personas from live QA (2026-11-11).
 * Run: node --test tests/jobseek/test_match_qa_personas.js
 */
"use strict";

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");

const M = require(path.join(__dirname, "..", "..", "site", "match-engine.js"));

const SNAPSHOT_PATH = path.join(__dirname, "..", "..", "api", "data", "jobs.snapshot.json");

function loadJobs() {
  if (!fs.existsSync(SNAPSHOT_PATH)) return [];
  const snap = JSON.parse(fs.readFileSync(SNAPSHOT_PATH, "utf8"));
  return snap.jobs || [];
}

function job(overrides = {}) {
  return {
    title: "Senior Data Engineer",
    company: "Acme",
    location: "Remote - Canada",
    province: "ON",
    work_arrangement: "remote",
    remote_scope: "canada",
    seniority: "senior",
    track: "data_engineering",
    salary_min: 140000,
    salary_max: 170000,
    salary_currency: "CAD",
    salary_available: true,
    salary_max_cad: 170000,
    technologies: ["Python", "SQL", "Spark", "Databricks"],
    apply_url: "https://boards.greenhouse.io/acme/jobs/1",
    description_excerpt: "",
    first_seen: "2026-11-03",
    ...overrides,
  };
}

describe("Persona A — Senior Data Engineer", () => {
  const profile = {
    ...M.emptyProfile(),
    current_title: "Senior Data Engineer",
    desired_titles: ["Senior Data Engineer"],
    years_experience: 6,
    skills: ["Python", "SQL", "Databricks", "Terraform", "Kubernetes", "Redis", "Control-M"],
    disciplines: ["data_engineering"],
    seniority: ["senior"],
    work_arrangements: ["remote", "hybrid"],
    minimum_salary_cad: 150000,
    include_undisclosed_salary: true,
    salary_filter_mode: "strict",
  };

  it("matches role-family variants, not only exact title", () => {
    const jobs = [
      job({ title: "Senior Data Platform Engineer", salary_min: 155000, salary_max: 180000, salary_max_cad: 180000 }),
      job({ title: "Lead Data Engineer", seniority: "lead", salary_min: 160000, salary_max: 190000, salary_max_cad: 190000 }),
      job({ title: "Data Engineer", seniority: "mid", salary_min: 150000, salary_max: 165000, salary_max_cad: 165000 }),
    ];
    const results = M.matchJobs(profile, jobs, { limit: 10 });
    assert.equal(results.length, 3);
    assert.ok(results.every((r) => r.match.percent > 0));
  });

  it("excludes on-site when remote+hybrid selected", () => {
    const results = M.matchJobs(
      profile,
      [job({ title: "Senior Data Engineer", work_arrangement: "onsite", company: "BitGo" })],
      { limit: 5 }
    );
    assert.equal(results.length, 0);
  });

  it("strict salary excludes ranges that only meet at the max", () => {
    const results = M.matchJobs(
      profile,
      [
        job({
          title: "Senior Data Platform Engineer",
          salary_min: 110000,
          salary_max: 160000,
          salary_max_cad: 160000,
        }),
      ],
      { limit: 5 }
    );
    assert.equal(results.length, 0);
  });

  it("flexible salary mode includes max-only overlap", () => {
    const flexible = { ...profile, salary_filter_mode: "flexible" };
    const results = M.matchJobs(
      flexible,
      [
        job({
          title: "Senior Data Platform Engineer",
          salary_min: 110000,
          salary_max: 160000,
          salary_max_cad: 160000,
        }),
      ],
      { limit: 5 }
    );
    assert.equal(results.length, 1);
    assert.equal(results[0].match.meets_with_max_only, true);
  });

  it("Control-M unconfirmed is not treated as a fabricated match", () => {
    const results = M.matchJobs(
      profile,
      [job({ technologies: ["Python", "SQL", "Databricks"], salary_min: 155000, salary_max_cad: 170000 })],
      { limit: 5 }
    );
    assert.ok(!results[0].match.matched_skills.includes("Control-M"));
    assert.ok(results[0].match.unconfirmed_skills.includes("Control-M"));
    assert.ok(
      results[0].match.reasons.some((r) => /unconfirmed/i.test(r) || /not mentioned/i.test(r))
    );
  });
});

describe("Persona B — Junior Frontend Engineer", () => {
  const profile = {
    ...M.emptyProfile(),
    current_title: "Frontend Engineer",
    desired_titles: ["Frontend Engineer"],
    years_experience: 2,
    skills: ["React", "TypeScript", "JavaScript"],
    disciplines: ["software_engineering"],
    seniority: [],
    work_arrangements: ["remote", "hybrid"],
    minimum_salary_cad: 0,
    salary_filter_mode: "strict",
  };

  it("penalizes Staff roles for a 2-year candidate", () => {
    const mid = job({
      title: "Frontend Engineer",
      seniority: "mid",
      track: "software_engineering",
      technologies: ["React", "TypeScript", "JavaScript"],
      salary_available: false,
      salary_min: null,
      salary_max: null,
      salary_max_cad: null,
    });
    const staff = job({
      title: "Staff Frontend Engineer",
      seniority: "staff",
      track: "software_engineering",
      technologies: ["React", "TypeScript", "JavaScript"],
      description_excerpt: "Requires 8+ years of experience building frontend systems.",
      salary_available: false,
      salary_min: null,
      salary_max: null,
      salary_max_cad: null,
    });
    const results = M.matchJobs(profile, [mid, staff], { limit: 5 });
    assert.equal(results.length, 2);
    const midPct = results.find((r) => r.job.title === "Frontend Engineer").match.percent;
    const staffPct = results.find((r) => r.job.title === "Staff Frontend Engineer").match.percent;
    assert.ok(staffPct < midPct, `staff ${staffPct} should be < mid ${midPct}`);
    assert.ok(staffPct < 70, `staff score ${staffPct} should not look like a strong match`);
    assert.ok(
      results
        .find((r) => r.job.title === "Staff Frontend Engineer")
        .match.reasons.some((r) => /experience/i.test(r) || /stretch/i.test(r) || /Seniority/i.test(r))
    );
  });
});

describe("Persona C — Platform Engineer", () => {
  const profile = {
    ...M.emptyProfile(),
    current_title: "Platform Engineer",
    desired_titles: ["Platform Engineer"],
    years_experience: 7,
    skills: ["Terraform", "Kubernetes", "Docker", "AWS"],
    disciplines: ["platform_engineering"],
    seniority: ["senior"],
    work_arrangements: ["remote"],
    preferred_locations: ["Canada"],
    minimum_salary_cad: 0,
    salary_filter_mode: "strict",
  };

  it("recognizes K8s/Terraform aliases and prioritizes platform track", () => {
    const platform = job({
      title: "Senior Platform Engineer",
      track: "platform_engineering",
      technologies: ["K8s", "Terraform", "Docker", "AWS"],
      work_arrangement: "remote",
      remote_scope: "canada",
    });
    const unrelated = job({
      title: "Marketing Analyst",
      track: "analytics_engineering",
      technologies: ["Excel", "Tableau"],
      work_arrangement: "remote",
      remote_scope: "canada",
      seniority: "mid",
    });
    const results = M.matchJobs(profile, [platform, unrelated], { limit: 5 });
    assert.ok(results.length >= 1);
    assert.ok(results[0].job.title.includes("Platform"));
    assert.ok(results[0].match.matched_skills.includes("Kubernetes"));
    assert.ok(results[0].match.matched_skills.includes("Terraform"));
    if (results.length > 1) {
      assert.ok(results[0].match.percent > results[1].match.percent);
    }
  });

  it("excludes hybrid when remote-only", () => {
    const results = M.matchJobs(
      profile,
      [job({ title: "Platform Engineer", work_arrangement: "hybrid", technologies: ["Terraform", "Kubernetes"] })],
      { limit: 5 }
    );
    assert.equal(results.length, 0);
  });
});

describe("Persona D — Analytics Engineer", () => {
  const profile = {
    ...M.emptyProfile(),
    current_title: "Analytics Engineer",
    desired_titles: ["Analytics Engineer"],
    years_experience: 5,
    skills: ["SQL", "Snowflake", "dbt", "Power BI"],
    disciplines: ["analytics_engineering"],
    seniority: ["senior"],
    work_arrangements: ["remote", "hybrid"],
    minimum_salary_cad: 140000,
    include_undisclosed_salary: true,
    salary_filter_mode: "strict",
  };

  it("matches SQL/dbt/Snowflake and respects strict salary", () => {
    const good = job({
      title: "Analytics Engineer",
      track: "analytics_engineering",
      technologies: ["SQL", "Snowflake", "dbt", "Power BI"],
      salary_min: 145000,
      salary_max: 175000,
      salary_max_cad: 175000,
    });
    const low = job({
      title: "Analytics Engineer",
      company: "LowPay",
      track: "analytics_engineering",
      technologies: ["SQL", "Snowflake", "dbt"],
      salary_min: 100000,
      salary_max: 130000,
      salary_max_cad: 130000,
    });
    const results = M.matchJobs(profile, [good, low], { limit: 5 });
    assert.equal(results.length, 1);
    assert.ok(results[0].match.matched_skills.includes("SQL"));
    assert.ok(results[0].match.matched_skills.includes("dbt"));
    assert.ok(results[0].match.matched_skills.includes("Snowflake"));
  });
});

describe("Persona E — Narrow Control-M profile", () => {
  const profile = {
    ...M.emptyProfile(),
    current_title: "Data Engineer",
    desired_titles: ["Data Engineer"],
    years_experience: 5,
    skills: ["Control-M"],
    disciplines: ["data_engineering"],
    seniority: ["mid"],
    work_arrangements: ["remote", "hybrid"],
    minimum_salary_cad: 0,
    salary_filter_mode: "strict",
  };

  it("does not invent Control-M matches or inflate on unconfirmed skills", () => {
    const results = M.matchJobs(
      profile,
      [job({ title: "Data Engineer", technologies: ["Python", "SQL"] })],
      { limit: 5 }
    );
    assert.equal(results.length, 1);
    assert.deepEqual(results[0].match.matched_skills, []);
    assert.ok(results[0].match.unconfirmed_skills.includes("Control-M"));
    assert.ok(results[0].match.percent < 70);
  });
});

describe("Persona F — Strict remote", () => {
  const profile = {
    ...M.emptyProfile(),
    current_title: "Software Engineer",
    desired_titles: ["Software Engineer"],
    years_experience: 4,
    skills: ["Python", "Docker"],
    disciplines: ["software_engineering"],
    seniority: ["mid"],
    work_arrangements: ["remote"],
    preferred_locations: ["ON"],
    minimum_salary_cad: 0,
    salary_filter_mode: "strict",
  };

  it("excludes hybrid and onsite", () => {
    const jobs = [
      job({ title: "Software Engineer", work_arrangement: "remote", remote_scope: "canada", province: null }),
      job({ title: "Software Engineer", company: "Hyb", work_arrangement: "hybrid" }),
      job({ title: "Software Engineer", company: "On", work_arrangement: "onsite" }),
    ];
    const results = M.matchJobs(profile, jobs, { limit: 10 });
    assert.equal(results.length, 1);
    assert.equal(results[0].job.work_arrangement, "remote");
  });

  it("rejects province-restricted remote outside preference", () => {
    const results = M.matchJobs(
      profile,
      [
        job({
          title: "Software Engineer",
          work_arrangement: "remote",
          remote_scope: "province",
          province: "BC",
          location: "Remote - BC",
        }),
      ],
      { limit: 5 }
    );
    assert.equal(results.length, 0);
  });
});

describe("Snapshot smoke — Persona A against live dataset shape", () => {
  it("returns relevant remote/hybrid data roles when snapshot present", () => {
    const jobs = loadJobs();
    if (!jobs.length) {
      assert.ok(true, "empty snapshot — skipped");
      return;
    }
    const profile = {
      ...M.emptyProfile(),
      current_title: "Senior Data Engineer",
      desired_titles: ["Senior Data Engineer"],
      years_experience: 6,
      skills: ["Python", "SQL", "Databricks", "Terraform", "Kubernetes", "Redis", "Control-M"],
      disciplines: ["data_engineering"],
      seniority: ["senior"],
      work_arrangements: ["remote", "hybrid"],
      minimum_salary_cad: 150000,
      include_undisclosed_salary: true,
      salary_filter_mode: "flexible", // compare eligibility broadly against API default
    };
    const results = M.matchJobs(profile, jobs, { limit: 40, fx: 1.35 });
    assert.ok(results.length > 0, "expected at least one match on snapshot");
    assert.ok(results.every((r) => r.job.work_arrangement !== "onsite"));
    // Title family should include data/platform engineering roles
    const titles = results.map((r) => r.job.title.toLowerCase());
    assert.ok(
      titles.some((t) => t.includes("data") || t.includes("platform") || t.includes("analytics")),
      `unexpected titles: ${titles.slice(0, 5).join("; ")}`
    );
  });
});
