import type { ApiJob, ApiSnapshot, MatchProfileInput, SearchFilters } from "./types";
import { jobMatchesFilters } from "./search";

/**
 * Deterministic profile matching — port of site/match-engine.js intent.
 * Keep aliases aligned with jobseek/skills/tech_extract.py.
 * No LLM. Does not store profiles. Never claims qualification without evidence.
 */

function norm(s: string): string {
  return s.trim().toLowerCase();
}

/** Conservative exact-match related hits (broad ≠ specific). */
const RELATED: Record<string, string[]> = {
  postgresql: ["sql"],
  mysql: ["sql"],
  "sql server": ["sql"],
  pyspark: ["python", "spark"],
  "node.js": ["javascript", "node"],
  node: ["node.js", "javascript"],
  javascript: ["node.js"],
};

const JOB_EXPAND: Record<string, string[]> = {
  pyspark: ["python", "spark"],
  "sql server": ["sql"],
  node: ["node.js"],
  "node.js": ["node"],
};

const SKILL_ALIASES: Record<string, string> = {
  plsql: "sql",
  "pl/sql": "sql",
  tsql: "sql server",
  "t-sql": "sql server",
  sqlserver: "sql server",
  "ms sql": "sql server",
  mssql: "sql server",
  "microsoft sql server": "sql server",
  postgres: "postgresql",
  nodejs: "node.js",
  golang: "go",
  k8s: "kubernetes",
  "control m": "control-m",
  controlm: "control-m",
  "google cloud": "gcp",
  "google cloud platform": "gcp",
  "github actions": "github actions",
  "gh actions": "github actions",
  "ci cd": "ci/cd",
  "ci-cd": "ci/cd",
  nextjs: "next.js",
  powerbi: "power bi",
  "machine learning": "machine learning",
  "model context protocol": "mcp",
};

function canonicalSkill(skill: string): string {
  const s = norm(skill)
    .replace(/_/g, " ")
    .replace(/[/-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return SKILL_ALIASES[s] || s;
}

function skillHit(job: ApiJob, skill: string): boolean {
  const s = canonicalSkill(skill);
  if (!s) return false;
  const jobSkills = job.technologies.map((t) => canonicalSkill(t));
  const expanded = new Set(jobSkills);
  for (const t of jobSkills) {
    for (const r of JOB_EXPAND[t] || []) expanded.add(r);
  }
  if (expanded.has(s) || (RELATED[s] || []).some((r) => expanded.has(r))) {
    return true;
  }
  // Fallback: title / track / excerpt substring — not a confirmed requirement.
  const blob = `${job.title} ${job.track || ""} ${(job.description_excerpt || "").slice(0, 800)}`.toLowerCase();
  return blob.includes(s);
}

function roleHit(job: ApiJob, role: string): boolean {
  const r = norm(role);
  if (!r) return false;
  return (
    job.title.toLowerCase().includes(r) ||
    (job.track || "").toLowerCase().includes(r.replace(/\s+/g, "_")) ||
    (job.track || "").toLowerCase().replace(/_/g, " ").includes(r)
  );
}

function seniorityCompatible(jobSeniority: string | null, preferred: string | undefined): boolean {
  if (!preferred) return true;
  const order = ["intern", "junior", "mid", "senior", "staff", "principal", "lead"];
  const js = (jobSeniority || "mid").toLowerCase();
  const ps = preferred.toLowerCase();
  const ji = order.indexOf(js);
  const pi = order.indexOf(ps);
  if (ji < 0 || pi < 0) return js === ps;
  // Allow adjacent bands; reject large over/under shoots as soft gaps later.
  return Math.abs(ji - pi) <= 1;
}

export interface MatchResult {
  id: string;
  title: string;
  company: string;
  location: string;
  apply_url: string;
  match_score: number;
  matching_skills: string[];
  gaps: string[];
  explanation: string;
  last_verified: string;
  salary_max_cad: number | null;
  work_arrangement: string;
}

export function matchProfile(snapshot: ApiSnapshot, input: MatchProfileInput): {
  matches: MatchResult[];
  dataset_id: string;
  generated_at: string;
  note: string;
} {
  const skills = (input.skills || []).map(norm).filter(Boolean);
  const roles = (input.preferred_roles || []).map(norm).filter(Boolean);
  const locations = (input.preferred_locations || []).map(norm).filter(Boolean);
  const limit = Math.min(25, Math.max(1, input.limit || 10));
  const fx = Number(snapshot.usd_to_cad) || 1.35;

  const geoFilters: SearchFilters = {
    remote: input.remote_preference === true ? true : undefined,
    salary_min: input.minimum_salary,
    seniority: undefined,
    limit: 500,
  };

  const scored: MatchResult[] = [];
  for (const job of snapshot.jobs) {
    if (!jobMatchesFilters(job, geoFilters, fx)) continue;
    if (input.seniority && !seniorityCompatible(job.seniority, input.seniority)) continue;

    if (locations.length) {
      const locBlob = `${job.location} ${job.province || ""}`.toLowerCase();
      const locOk =
        locations.some((l) => locBlob.includes(l)) ||
        (input.remote_preference && job.work_arrangement === "remote");
      if (!locOk) continue;
    }

    const matchingSkills = skills.filter((s) => skillHit(job, s));
    const missingSkills = skills.filter((s) => !skillHit(job, s));
    const roleOk = roles.length === 0 || roles.some((r) => roleHit(job, r));
    if (roles.length && !roleOk) continue;

    let score = 0;
    // Title / role ~30%
    if (roleOk && roles.length) score += 30;
    else if (roles.length === 0) score += 15;
    // Skills ~30%
    if (skills.length) {
      score += Math.round(30 * (matchingSkills.length / skills.length));
    } else {
      score += 10;
    }
    // Seniority ~15%
    if (seniorityCompatible(job.seniority, input.seniority)) score += 15;
    // Discipline / track presence ~15%
    if (job.track) score += 10;
    if (job.verified) score += 5;
    // Preferences ~10%
    if (input.remote_preference && job.work_arrangement === "remote") score += 10;
    else if (!input.remote_preference) score += 5;

    // "gaps" field retained for API compatibility — values are unconfirmed
    // (not evidenced), never claimed as confirmed missing requirements.
    const gaps: string[] = [];
    if (missingSkills.length) {
      gaps.push(`Unconfirmed in listing (not evidenced): ${missingSkills.slice(0, 5).join(", ")}`);
    }
    if (input.seniority && (job.seniority || "").toLowerCase() !== input.seniority.toLowerCase()) {
      gaps.push(
        `Seniority band differs (job=${job.seniority || "unspecified"}, preferred=${input.seniority})`,
      );
    }
    if (!job.salary_available && input.minimum_salary) {
      gaps.push("Salary undisclosed — could not confirm compensation floor from employer text");
    }

    const explanationParts = [
      roleOk && roles.length ? `Role keywords matched (${roles.slice(0, 2).join(", ")})` : null,
      matchingSkills.length ? `Overlapping skills: ${matchingSkills.slice(0, 6).join(", ")}` : null,
      `Canada-eligible listing (${job.work_arrangement}, scope=${job.remote_scope})`,
      job.salary_available
        ? `Advertised pay up to ${job.salary_currency} ${Math.round(job.salary_max || 0).toLocaleString()}`
        : "No advertised annual salary",
    ].filter(Boolean);

    scored.push({
      id: job.id,
      title: job.title,
      company: job.company,
      location: job.location,
      apply_url: job.apply_url,
      match_score: Math.min(99, score),
      matching_skills: matchingSkills,
      gaps,
      explanation: explanationParts.join(". ") + ".",
      last_verified: job.last_verified,
      salary_max_cad: job.salary_max_cad,
      work_arrangement: job.work_arrangement,
    });
  }

  scored.sort((a, b) => b.match_score - a.match_score || a.title.localeCompare(b.title));

  return {
    matches: scored.slice(0, limit),
    dataset_id: snapshot.dataset_id,
    generated_at: snapshot.generated_at,
    note:
      "Deterministic relevance against GitHired's tracked Canada-eligible jobs — not an LLM assessment, " +
      "not a guarantee of hireability, and not a full Canadian labour-market census.",
  };
}
