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

  it("$150K with range max only", () => {
    const r = M.salaryFilterPass(
      job({ salary_min: 120000, salary_max: 160000, salary_max_cad: 160000 }),
      150000,
      true
    );
    assert.equal(r.pass, true);
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
});
