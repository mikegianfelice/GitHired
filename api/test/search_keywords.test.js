import assert from "node:assert/strict";
import { test } from "node:test";

function tokens(text) {
  return String(text || "")
    .toLowerCase()
    .split(/[^a-z0-9+#.]+/i)
    .filter((t) => t.length >= 2);
}

function hasToken(hay, token) {
  return tokens(hay).includes(String(token || "").toLowerCase());
}

function titleOrRole(job) {
  return `${job.title} ${job.track || ""} ${job.seniority || ""}`.toLowerCase();
}

const SENIORITY_TOKENS = new Set([
  "senior",
  "sr",
  "junior",
  "jr",
  "staff",
  "principal",
  "lead",
  "intern",
  "entry",
  "mid",
  "intermediate",
  "i",
  "ii",
  "iii",
  "iv",
]);

const GENERIC_ROLE_TOKENS = new Set(["engineer", "engineering", "developer", "software"]);

function matchesLikeApi(job, q) {
  const all = tokens(q);
  if (!all.length) return true;
  const inAny = all.filter(
    (t) =>
      hasToken(job.title, t) ||
      hasToken(job.company, t) ||
      (job.technologies || []).some((x) => hasToken(x, t)) ||
      hasToken(
        `${job.title} ${job.company} ${job.location} ${job.province || ""} ${job.track || ""} ${
          job.seniority || ""
        } ${(job.technologies || []).join(" ")} ${job.description_excerpt || ""}`,
        t,
      ),
  ).length;
  if (inAny < all.length) return false;
  const roleHits = all.filter(
    (t) => !SENIORITY_TOKENS.has(t) && !GENERIC_ROLE_TOKENS.has(t) && hasToken(titleOrRole(job), t),
  ).length;
  const companyHits = all.filter((t) => hasToken(job.company, t)).length;
  const techHits = all.filter((t) => (job.technologies || []).some((x) => hasToken(x, t))).length;
  if (roleHits === 0 && companyHits === 0 && techHits === 0) return false;
  return true;
}

test("keyword filter excludes description-only matches for role-family queries", () => {
  const q = "senior data engineer";
  const falsePositive = {
    title: "Senior Security Engineer",
    company: "ExampleCo",
    location: "Toronto, ON",
    province: "ON",
    track: "security_engineering",
    seniority: "senior",
    technologies: ["Go", "Kubernetes"],
    description_excerpt:
      "We build data pipelines and support data engineers across teams using Spark and Python.",
  };
  const truePositive = {
    title: "Senior Data Engineer",
    company: "ExampleCo",
    location: "Toronto, ON",
    province: "ON",
    track: "data_engineering",
    seniority: "senior",
    technologies: ["Python", "Spark"],
    description_excerpt:
      "Design and scale data pipelines in PySpark and SQL.",
  };
  assert.equal(matchesLikeApi(falsePositive, q), false);
  assert.equal(matchesLikeApi(truePositive, q), true);
});

