/**
 * Node tests for site/match-engine.js (salary filter + matching).
 * Run: node --test tests/jobseek/test_match_engine.js
 */
"use strict";

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const M = require(path.join(__dirname, "..", "..", "site", "match-engine.js"));

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
    first_seen: "2026-11-03",
    ...overrides,
  };
}

describe("salaryFilterPass", () => {
  it("$0 threshold passes all", () => {
    const r = M.salaryFilterPass(job(), 0, true);
    assert.equal(r.pass, true);
  });

  it("$100K CAD range passes", () => {
    const r = M.salaryFilterPass(job(), 100000, true);
    assert.equal(r.pass, true);
    assert.equal(r.meets_with_max_only, false);
  });

  it("$150K with range max only — flexible mode", () => {
    const r = M.salaryFilterPass(
      job({ salary_min: 120000, salary_max: 160000, salary_max_cad: 160000 }),
      150000,
      true,
      1.35,
      "flexible"
    );
    assert.equal(r.pass, true);
    assert.equal(r.meets_with_max_only, true);
  });

  it("$150K with range max only — strict mode excludes", () => {
    const r = M.salaryFilterPass(
      job({ salary_min: 120000, salary_max: 160000, salary_max_cad: 160000 }),
      150000,
      true,
      1.35,
      "strict"
    );
    assert.equal(r.pass, false);
    assert.equal(r.meets_with_max_only, true);
  });

  it("$300K+ threshold", () => {
    assert.equal(M.salaryFilterPass(job({ salary_max: 280000, salary_max_cad: 280000 }), 300000, true).pass, false);
    assert.equal(
      M.salaryFilterPass(job({ salary_max: 320000, salary_max_cad: 320000 }), 300000, true).pass,
      true
    );
  });

  it("USD converts via 1.35", () => {
    const j = job({
      salary_min: 100000,
      salary_max: 110000,
      salary_currency: "USD",
      salary_max_cad: null,
    });
    // 110k USD * 1.35 = 148500 CAD
    assert.equal(M.salaryFilterPass(j, 140000, false, 1.35).pass, true);
    assert.equal(M.salaryFilterPass(j, 160000, false, 1.35).pass, false);
  });

  it("missing compensation respects checkbox", () => {
    const j = job({
      salary_available: false,
      salary_min: null,
      salary_max: null,
      salary_max_cad: null,
    });
    assert.equal(M.salaryFilterPass(j, 100000, true).pass, true);
    assert.equal(M.salaryFilterPass(j, 100000, false).pass, false);
  });
});

describe("extractProfileFromText", () => {
  it("empty résumé yields empty skills", () => {
    const p = M.extractProfileFromText("");
    assert.deepEqual(p.skills, []);
    assert.equal(p.current_title, "");
  });

  it("extracts skills and aliases", () => {
    const p = M.extractProfileFromText(
      "Senior Data Engineer\n7 years of experience\nPySpark, PostgreSQL, JS, TS, AWS"
    );
    assert.ok(p.skills.includes("Python"));
    assert.ok(p.skills.includes("Spark"));
    assert.ok(p.skills.includes("SQL"));
    assert.ok(p.skills.includes("JavaScript"));
    assert.ok(p.skills.includes("TypeScript"));
    assert.ok(p.skills.includes("AWS"));
    assert.equal(p.years_experience, 7);
  });

  it("does not invent skills", () => {
    const p = M.extractProfileFromText("Product Manager interested in leadership");
    assert.ok(!p.skills.includes("Kubernetes"));
  });

  it("normalizes T-SQL / PL/SQL and SQL Server", () => {
    const p = M.extractProfileFromText("T-SQL, PL/SQL, SQL Server");
    assert.ok(p.skills.includes("SQL")); // PL/SQL
    assert.ok(p.skills.includes("SQL Server")); // T-SQL / SQL Server
  });

  it("extracts Control-M, Redis, Terraform, K8s", () => {
    const p = M.extractProfileFromText("Control-M, Redis, Terraform, K8s");
    assert.ok(p.skills.includes("Control-M"));
    assert.ok(p.skills.includes("Redis"));
    assert.ok(p.skills.includes("Terraform"));
    assert.ok(p.skills.includes("Kubernetes"));
  });

  it("extracts MySQL and Databricks distinctly", () => {
    const p = M.extractProfileFromText("MySQL, Databricks, Snowflake");
    assert.ok(p.skills.includes("MySQL"));
    assert.ok(p.skills.includes("Databricks"));
    assert.ok(p.skills.includes("Snowflake"));
  });
});

describe("matchJobs", () => {
  const profile = {
    ...M.emptyProfile(),
    current_title: "Senior Data Engineer",
    desired_titles: ["Senior Data Engineer"],
    skills: ["Python", "SQL", "Databricks", "Spark", "AWS"],
    disciplines: ["data_engineering"],
    seniority: ["senior"],
    work_arrangements: ["remote", "hybrid"],
    minimum_salary_cad: 100000,
    include_undisclosed_salary: true,
  };

  it("perfect skill match scores high", () => {
    const results = M.matchJobs(profile, [job()], { limit: 5 });
    assert.equal(results.length, 1);
    assert.ok(results[0].match.percent >= 70);
    assert.ok(results[0].match.matched_skills.includes("Python"));
    assert.ok(results[0].match.unconfirmed_skills.includes("AWS"));
  });

  it("missing job tech is unconfirmed not a hard fail", () => {
    const results = M.matchJobs(profile, [job({ technologies: [] })], { limit: 5 });
    assert.equal(results.length, 1);
    assert.ok(results[0].match.unconfirmed_skills.length >= 1);
  });

  it("SQL does not exact-match PostgreSQL-only job tags", () => {
    const results = M.matchJobs(profile, [job({ technologies: ["PostgreSQL", "Python"] })], {
      limit: 5,
    });
    assert.ok(!results[0].match.matched_skills.includes("SQL"));
    assert.ok(results[0].match.matched_skills.includes("Python"));
  });

  it("PostgreSQL profile matches SQL job tag", () => {
    const results = M.matchJobs(
      { ...profile, skills: ["PostgreSQL"] },
      [job({ technologies: ["SQL", "Python"] })],
      { limit: 5 }
    );
    assert.ok(results[0].match.matched_skills.includes("PostgreSQL"));
  });

  it("K8s profile matches Kubernetes job tag", () => {
    const results = M.matchJobs(
      { ...profile, skills: ["K8s", "Terraform"] },
      [job({ technologies: ["Kubernetes", "Terraform"] })],
      { limit: 5 }
    );
    assert.ok(results[0].match.matched_skills.includes("Kubernetes"));
    assert.ok(results[0].match.matched_skills.includes("Terraform"));
  });

  it("does not fabricate matches for unrelated skills", () => {
    const results = M.matchJobs(
      { ...profile, skills: ["Kafka", "Terraform"] },
      [job({ technologies: ["Python", "SQL"] })],
      { limit: 5 }
    );
    assert.deepEqual(results[0].match.matched_skills, []);
    assert.ok(results[0].match.unconfirmed_skills.includes("Kafka"));
  });

  it("job Python does not count as Spark", () => {
    const results = M.matchJobs(
      { ...profile, skills: ["Spark"] },
      [job({ technologies: ["Python", "SQL"] })],
      { limit: 5 }
    );
    assert.deepEqual(results[0].match.matched_skills, []);
    assert.ok(results[0].match.unconfirmed_skills.includes("Spark"));
  });

  it("province-restricted remote outside preference is ineligible", () => {
    const p = {
      ...profile,
      preferred_locations: ["BC"],
    };
    const results = M.matchJobs(
      p,
      [
        job({
          remote_scope: "province",
          province: "ON",
          location: "Remote - Ontario",
        }),
      ],
      { limit: 5 }
    );
    assert.equal(results.length, 0);
  });

  it("Canada-wide remote passes province preference", () => {
    const p = { ...profile, preferred_locations: ["BC"] };
    const results = M.matchJobs(p, [job({ remote_scope: "canada", province: null })], {
      limit: 5,
    });
    assert.equal(results.length, 1);
  });

  it("salary mismatch is ineligible", () => {
    const p = { ...profile, minimum_salary_cad: 250000, include_undisclosed_salary: false };
    const results = M.matchJobs(p, [job()], { limit: 5 });
    assert.equal(results.length, 0);
  });

  it("dedupes duplicate company+title", () => {
    const results = M.matchJobs(profile, [job(), job({ apply_url: "https://x/2" })], {
      limit: 5,
    });
    assert.equal(results.length, 1);
  });

  it("remote-only excludes unspecified, hybrid, and onsite", () => {
    const p = {
      ...M.emptyProfile(),
      current_title: "Backend Engineer",
      desired_titles: ["Backend Engineer"],
      skills: ["Python"],
      work_arrangements: ["remote"],
      minimum_salary_cad: 0,
    };
    const jobs = [
      job({
        company: "RemoteCo",
        title: "Backend Engineer",
        work_arrangement: "remote",
        seniority: "mid",
        technologies: ["Python"],
      }),
      job({
        company: "UnspecCo",
        title: "Backend Engineer",
        work_arrangement: "unspecified",
        seniority: "mid",
        technologies: ["Python"],
      }),
      job({
        company: "HybridCo",
        title: "Backend Engineer",
        work_arrangement: "hybrid",
        seniority: "mid",
        technologies: ["Python"],
      }),
    ];
    const results = M.matchJobs(p, jobs, { limit: 10 });
    assert.equal(results.length, 1);
    assert.equal(results[0].job.company, "RemoteCo");
  });

  it("no arrangement preference keeps unspecified jobs", () => {
    const p = {
      ...M.emptyProfile(),
      current_title: "Backend Engineer",
      desired_titles: ["Backend Engineer"],
      skills: ["Python"],
      work_arrangements: [],
      minimum_salary_cad: 0,
    };
    const jobs = [
      job({
        company: "UnspecCo",
        title: "Backend Engineer",
        work_arrangement: "unspecified",
        seniority: "mid",
        technologies: ["Python"],
      }),
    ];
    const results = M.matchJobs(p, jobs, { limit: 5 });
    assert.equal(results.length, 1);
  });

  it("junior / 0-YOE ranks confirmed junior above mid and senior", () => {
    const p = {
      ...M.emptyProfile(),
      current_title: "Junior Software Engineer",
      desired_titles: ["Software Engineer", "Python Developer"],
      skills: ["Python"],
      seniority: ["junior"],
      years_experience: 0,
      work_arrangements: ["remote", "hybrid"],
      minimum_salary_cad: 0,
    };
    const jobs = [
      job({
        company: "JuniorCo",
        title: "Junior Software Engineer",
        seniority: "junior",
        track: "software_engineering",
        technologies: ["Python"],
        salary_max_cad: 90000,
      }),
      job({
        company: "MidCo",
        title: "Software Engineer",
        seniority: "mid",
        track: "software_engineering",
        technologies: ["Python"],
        salary_max_cad: 140000,
      }),
      job({
        company: "SeniorCo",
        title: "Senior Software Engineer",
        seniority: "senior",
        track: "software_engineering",
        technologies: ["Python"],
        salary_max_cad: 180000,
      }),
    ];
    const results = M.matchJobs(p, jobs, { limit: 10 });
    assert.equal(results[0].job.company, "JuniorCo");
    const byCo = Object.fromEntries(results.map((r) => [r.job.company, r.match.percent]));
    assert.ok(byCo.JuniorCo > byCo.MidCo);
    assert.ok(byCo.JuniorCo > byCo.SeniorCo);
  });
});

describe("filterBrowseJobs", () => {
  it("combines search and salary", () => {
    const jobs = [
      job({ title: "Platform Engineer", company: "Zulu", salary_max_cad: 200000 }),
      job({
        title: "Data Engineer",
        company: "Alpha",
        salary_max: 90000,
        salary_max_cad: 90000,
        salary_min: 80000,
      }),
    ];
    const out = M.filterBrowseJobs(
      jobs,
      {
        query: "engineer",
        minimum_salary_cad: 100000,
        include_undisclosed_salary: false,
        sort: "company",
      },
      1.35
    );
    assert.equal(out.length, 1);
    assert.equal(out[0].job.company, "Zulu");
  });

  it("sorts by highest salary", () => {
    const jobs = [
      job({ company: "Low", salary_max_cad: 100000, salary_max: 100000 }),
      job({ company: "High", salary_max_cad: 200000, salary_max: 200000 }),
    ];
    const out = M.filterBrowseJobs(jobs, { sort: "salary", minimum_salary_cad: 0 }, 1.35);
    assert.equal(out[0].job.company, "High");
  });

  it("supports multi-select province / arrangement / seniority", () => {
    const jobs = [
      job({ company: "A", province: "ON", work_arrangement: "remote", seniority: "senior" }),
      job({ company: "B", province: "BC", work_arrangement: "hybrid", seniority: "mid" }),
      job({ company: "C", province: "AB", work_arrangement: "onsite", seniority: "junior" }),
    ];
    const out = M.filterBrowseJobs(
      jobs,
      {
        provinces: ["ON", "BC"],
        arrangements: ["remote", "hybrid"],
        seniorities: ["senior", "mid"],
        minimum_salary_cad: 0,
        sort: "company",
      },
      1.35
    );
    assert.deepEqual(
      out.map((r) => r.job.company),
      ["A", "B"]
    );
  });

  it("keeps legacy single-string filters working", () => {
    const jobs = [
      job({ company: "A", province: "ON" }),
      job({ company: "B", province: "BC" }),
    ];
    const out = M.filterBrowseJobs(jobs, { province: "BC", minimum_salary_cad: 0 }, 1.35);
    assert.equal(out.length, 1);
    assert.equal(out[0].job.company, "B");
  });

  it("defaults to highest advertised salary", () => {
    const jobs = [
      job({
        company: "OldHigh",
        last_verified: "2026-10-01",
        salary_max: 300000,
        salary_max_cad: 300000,
      }),
      job({
        company: "NewLow",
        last_verified: "2026-11-09",
        salary_max: 90000,
        salary_max_cad: 90000,
      }),
    ];
    const out = M.filterBrowseJobs(jobs, { minimum_salary_cad: 0 }, 1.35);
    assert.equal(out[0].job.company, "OldHigh");
  });

  it("matchJobs sorts by relevance (match percent), not salary", () => {
    const profile = {
      ...M.emptyProfile(),
      current_title: "Senior Data Engineer",
      desired_titles: ["Senior Data Engineer"],
      skills: ["Python", "SQL"],
      disciplines: ["data_engineering"],
      seniority: ["senior"],
      work_arrangements: ["remote"],
      minimum_salary_cad: 0,
    };
    const jobs = [
      job({
        company: "HighPayWeakFit",
        title: "Senior Data Engineer",
        technologies: [],
        salary_max: 300000,
        salary_max_cad: 300000,
      }),
      job({
        company: "LowerPayStrongFit",
        title: "Senior Data Engineer",
        technologies: ["Python", "SQL", "Databricks"],
        salary_max: 160000,
        salary_max_cad: 160000,
      }),
    ];
    const results = M.matchJobs(profile, jobs, { limit: 5 });
    assert.equal(results[0].job.company, "LowerPayStrongFit");
    assert.ok(results[0].match.percent >= results[1].match.percent);
  });

  it("sort=verified uses last_verified; sort=recent uses first_seen", () => {
    const jobs = [
      job({
        company: "VerifiedNew",
        last_verified: "2026-11-09",
        first_seen: "2026-10-01",
      }),
      job({
        company: "DiscoveredNew",
        last_verified: "2026-10-01",
        first_seen: "2026-11-08",
      }),
    ];
    const verified = M.filterBrowseJobs(jobs, { sort: "verified", minimum_salary_cad: 0 }, 1.35);
    const recent = M.filterBrowseJobs(jobs, { sort: "recent", minimum_salary_cad: 0 }, 1.35);
    assert.equal(verified[0].job.company, "VerifiedNew");
    assert.equal(recent[0].job.company, "DiscoveredNew");
  });

  it("puts jobs without salary after advertised when sorting by salary", () => {
    const jobs = [
      job({
        company: "Unknown",
        salary_available: false,
        salary_min: null,
        salary_max: null,
        salary_max_cad: null,
      }),
      job({ company: "Listed", salary_max: 120000, salary_max_cad: 120000 }),
    ];
    const out = M.filterBrowseJobs(jobs, { sort: "salary", minimum_salary_cad: 0 }, 1.35);
    assert.equal(out[0].job.company, "Listed");
    assert.equal(out[1].job.company, "Unknown");
  });
});
