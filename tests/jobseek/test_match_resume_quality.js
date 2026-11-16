/**
 * Résumé parse + match quality regressions (negation, seniority, ranking).
 * Run: node --test tests/jobseek/test_match_resume_quality.js
 */
"use strict";

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const M = require(path.join(__dirname, "..", "..", "site", "match-engine.js"));

const FIXTURE = fs.readFileSync(
  path.join(__dirname, "fixtures", "mock_senior_data_engineer_resume.txt"),
  "utf8"
);

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
    salary_min: 155000,
    salary_max: 180000,
    salary_currency: "CAD",
    salary_available: true,
    salary_max_cad: 180000,
    technologies: ["Python", "SQL", "Spark", "Databricks", "AWS"],
    apply_url: "https://boards.greenhouse.io/acme/jobs/1",
    description_excerpt: "",
    first_seen: "2026-11-03",
    ...overrides,
  };
}

describe("skill negation / context", () => {
  it("does not confirm skills under Not claimed / Exclude", () => {
    const p = M.extractProfileFromText(FIXTURE);
    for (const bad of ["Kubernetes", "Java", "React", "Azure", "GCP", "LLM"]) {
      assert.ok(!p.skills.includes(bad), bad);
    }
    for (const good of ["Python", "SQL", "PySpark", "Spark", "Databricks", "AWS", "Power BI"]) {
      assert.ok(p.skills.includes(good), good);
    }
  });

  it("handles mixed positive and negative in one résumé", () => {
    const text =
      "Backend Engineer\n3 years of experience\nBuilt APIs with Python and Go.\n" +
      "Not claimed: Rust, Kubernetes.\nInterested in learning React.";
    const p = M.extractProfileFromText(text);
    assert.ok(p.skills.includes("Python"));
    assert.ok(p.skills.includes("Go"));
    assert.ok(!p.skills.includes("Rust"));
    assert.ok(!p.skills.includes("Kubernetes"));
    assert.ok(!p.skills.includes("React"));
  });

  it("denies multiple technologies listed after no professional experience with", () => {
    const text =
      "Data Engineer\n5 years of experience with Python and SQL.\n" +
      "No professional experience with Kubernetes, Java, or Azure.";
    const p = M.extractProfileFromText(text);
    assert.ok(p.skills.includes("Python"));
    assert.ok(!p.skills.includes("Kubernetes"));
    assert.ok(!p.skills.includes("Java"));
    assert.ok(!p.skills.includes("Azure"));
  });

  it("keeps ambiguous positive mentions", () => {
    const text = "Engineer\nUsed Docker in one internship; open to Kubernetes roles.";
    const p = M.extractProfileFromText(text);
    assert.ok(p.skills.includes("Docker"));
  });
});

describe("mock Senior Data Engineer fixture profile", () => {
  const p = M.extractProfileFromText(FIXTURE);

  it("extracts title, years, seniority, salary, arrangements", () => {
    assert.equal(p.current_title, "Senior Data Engineer");
    assert.equal(p.years_experience, 6);
    assert.deepEqual(p.seniority, ["senior"]);
    assert.equal(p.minimum_salary_cad, 150000);
    assert.ok(p.work_arrangements.includes("remote"));
    assert.ok(p.work_arrangements.includes("hybrid"));
    assert.ok(!p.work_arrangements.includes("onsite"));
    assert.ok(p.desired_titles.includes("Data Platform Engineer"));
    assert.ok(p.desired_titles.includes("Analytics Engineer"));
    assert.ok(p.disciplines.includes("data_engineering"));
    assert.ok(!p.disciplines.includes("software_engineering"));
  });

  it("ranks Senior Data Engineer above junior SWE/SRE on a controlled slate", () => {
    const slate = [
      job({
        company: "PointClickCare",
        title: "Canada- Jr Software Engineer (SRE)",
        seniority: "junior",
        track: "software_engineering",
        salary_min: 70000,
        salary_max: 80000,
        salary_max_cad: 80000,
        technologies: ["Kubernetes", "Azure", "Prometheus"],
      }),
      job({
        company: "PolicyMe",
        title: "Junior Software Engineer (Remote)",
        seniority: "junior",
        track: "software_engineering",
        salary_min: 80000,
        salary_max: 110000,
        salary_max_cad: 110000,
        technologies: ["Python", "PostgreSQL", "AWS", "React"],
      }),
      job({
        company: "Sun Life",
        title: "Senior Data Engineer",
        seniority: "senior",
        track: "data_engineering",
        salary_available: false,
        salary_min: null,
        salary_max: null,
        salary_max_cad: null,
        work_arrangement: "hybrid",
        technologies: ["Python", "SQL", "Spark", "AWS"],
      }),
    ];
    const results = M.matchJobs(p, slate, { limit: 10 });
    assert.ok(results.length >= 1);
    assert.equal(results[0].job.company, "Sun Life");
    assert.ok(results[0].match.percent >= 70);
    assert.ok(!results.some((r) => /Junior|Jr\b/i.test(r.job.title)));
    assert.ok(!results[0].match.reasons.some((r) => /Seniority compatible/i.test(r) && /junior/i.test(results[0].job.title)));
  });

  it("never claims Seniority compatible for senior→junior", () => {
    const junior = job({
      title: "Junior Data Engineer",
      seniority: "junior",
      salary_min: 160000,
      salary_max: 180000,
      salary_max_cad: 180000,
      technologies: ["Python", "SQL", "Spark"],
    });
    const scored = M.scoreJob(p, junior, 1.35);
    if (scored.status !== "ineligible") {
      assert.ok(scored.percent < 50);
      assert.ok(!scored.reasons.includes("Seniority compatible"));
      assert.ok(scored.reasons.some((r) => /junior|entry-level|more senior/i.test(r)));
    }
  });
});

describe("multi-persona ranking sanity", () => {
  const personas = [
    {
      name: "senior_de",
      profile: {
        ...M.emptyProfile(),
        current_title: "Senior Data Engineer",
        desired_titles: ["Senior Data Engineer"],
        years_experience: 6,
        skills: ["Python", "SQL", "Spark", "Databricks", "AWS"],
        disciplines: ["data_engineering"],
        seniority: ["senior"],
        work_arrangements: ["remote", "hybrid"],
        minimum_salary_cad: 150000,
        include_undisclosed_salary: true,
        salary_filter_mode: "strict",
      },
      prefer: /data engineer/i,
      avoidTop: /junior|jr\b/i,
    },
    {
      name: "junior_python",
      profile: {
        ...M.emptyProfile(),
        current_title: "Python Developer",
        desired_titles: ["Python Developer", "Junior Software Engineer"],
        years_experience: 1,
        skills: ["Python", "SQL", "Git"],
        disciplines: ["software_engineering"],
        seniority: ["junior"],
        work_arrangements: ["remote"],
        minimum_salary_cad: 65000,
        include_undisclosed_salary: true,
        salary_filter_mode: "flexible",
      },
      prefer: /junior|python|software engineer/i,
    },
    {
      name: "career_switcher",
      profile: {
        ...M.emptyProfile(),
        current_title: "Aspiring Software Developer",
        desired_titles: ["Software Developer", "Junior Developer"],
        years_experience: 0,
        skills: ["Python"],
        disciplines: ["software_engineering"],
        seniority: ["junior"],
        work_arrangements: ["remote", "hybrid"],
        minimum_salary_cad: 0,
        include_undisclosed_salary: true,
      },
    },
    {
      name: "staff_ai",
      profile: {
        ...M.emptyProfile(),
        current_title: "Staff AI Engineer",
        desired_titles: ["Staff AI Engineer", "Staff Machine Learning Engineer"],
        years_experience: 9,
        skills: ["Python", "PyTorch", "LLM", "AWS"],
        disciplines: ["ml_engineering"],
        seniority: ["staff"],
        work_arrangements: ["remote"],
        minimum_salary_cad: 200000,
        include_undisclosed_salary: true,
        salary_filter_mode: "strict",
      },
      avoidTop: /junior|jr\b/i,
    },
    {
      name: "frontend",
      profile: {
        ...M.emptyProfile(),
        current_title: "Frontend Developer",
        desired_titles: ["Frontend Engineer", "React Developer"],
        years_experience: 3,
        skills: ["React", "TypeScript", "JavaScript"],
        disciplines: ["software_engineering"],
        seniority: ["mid"],
        work_arrangements: ["remote", "hybrid"],
        minimum_salary_cad: 90000,
        include_undisclosed_salary: true,
      },
    },
    {
      name: "solutions_architect",
      profile: {
        ...M.emptyProfile(),
        current_title: "Senior Solutions Architect",
        desired_titles: ["Solutions Architect", "Cloud Architect"],
        years_experience: 8,
        skills: ["AWS", "Azure", "Terraform", "Kubernetes"],
        disciplines: ["platform_engineering"],
        seniority: ["senior"],
        work_arrangements: ["remote"],
        minimum_salary_cad: 170000,
        include_undisclosed_salary: true,
        salary_filter_mode: "strict",
      },
      avoidTop: /junior|jr\b/i,
    },
  ];

  const slate = [
    job({ company: "DE", title: "Senior Data Engineer", seniority: "senior", track: "data_engineering" }),
    job({
      company: "JrSWE",
      title: "Junior Software Engineer",
      seniority: "junior",
      track: "software_engineering",
      salary_min: 70000,
      salary_max: 90000,
      salary_max_cad: 90000,
      technologies: ["Python", "React"],
    }),
    job({
      company: "FE",
      title: "Frontend Engineer",
      seniority: "mid",
      track: "software_engineering",
      salary_min: 95000,
      salary_max: 120000,
      salary_max_cad: 120000,
      technologies: ["React", "TypeScript", "JavaScript"],
    }),
    job({
      company: "AI",
      title: "Staff Machine Learning Engineer",
      seniority: "staff",
      track: "ml_engineering",
      salary_min: 210000,
      salary_max: 260000,
      salary_max_cad: 260000,
      technologies: ["Python", "PyTorch", "LLM", "AWS"],
    }),
    job({
      company: "Arch",
      title: "Senior Cloud Architect",
      seniority: "senior",
      track: "platform_engineering",
      salary_min: 175000,
      salary_max: 210000,
      salary_max_cad: 210000,
      technologies: ["AWS", "Azure", "Terraform", "Kubernetes"],
    }),
  ];

  for (const persona of personas) {
    it(`${persona.name}: produces ranked matches without junior false-confidence`, () => {
      const results = M.matchJobs(persona.profile, slate, { limit: 5 });
      assert.ok(results.length >= 1, persona.name);
      if (persona.avoidTop) {
        assert.ok(!persona.avoidTop.test(results[0].job.title), results[0].job.title);
      }
      for (const r of results) {
        if (/junior|jr\b/i.test(r.job.title) && ["senior", "staff"].includes(persona.profile.seniority[0])) {
          assert.ok(!r.match.reasons.includes("Seniority compatible"));
          assert.ok(r.match.percent < 55);
        }
      }
    });
  }

  it("junior python still prefers junior SWE over staff AI when salary allows", () => {
    const junior = personas.find((p) => p.name === "junior_python").profile;
    const results = M.matchJobs(junior, slate, { limit: 5 });
    assert.ok(results.some((r) => r.job.company === "JrSWE"));
    const jr = results.find((r) => r.job.company === "JrSWE");
    const ai = results.find((r) => r.job.company === "AI");
    if (jr && ai) assert.ok(jr.match.percent >= ai.match.percent);
  });
});
