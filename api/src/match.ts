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

const SENIORITY_ORDER = ["intern", "junior", "mid", "senior", "staff", "principal", "lead"];

const SENIORITY_STOP = new Set([
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
  "level",
  "i",
  "ii",
  "iii",
  "iv",
]);

const ROLE_TRACK_HINTS: Array<{ pattern: RegExp; tracks: string[] }> = [
  { pattern: /\bdata\s+engineer|\bdata\s+platform|\betl\b/i, tracks: ["data_engineering"] },
  { pattern: /\banalytics\s+engineer/i, tracks: ["analytics_engineering", "data_engineering"] },
  { pattern: /\bplatform\s+engineer|\bcloud\s+engineer|\binfrastructure/i, tracks: ["platform_engineering", "devops_sre"] },
  { pattern: /\bfrontend|\bfront[\s-]?end|\breact\b/i, tracks: ["software_engineering"] },
  { pattern: /\bsite\s+reliability|\bdevops|\bsre\b/i, tracks: ["devops_sre", "platform_engineering"] },
];

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

function titleTokens(text: string): string[] {
  return norm(text)
    .split(/[^a-z0-9+#.]+/)
    .filter((t) => t.length > 1);
}

/** Role-family tokens with seniority/level words removed. */
function roleFamilyTokens(text: string): string[] {
  return titleTokens(text).filter((t) => t.length > 2 && !SENIORITY_STOP.has(t));
}

function tokenInTitle(title: string, token: string): boolean {
  // Whole-token match only — "data" must not hit "datastores" / "database".
  const parts = new Set(roleFamilyTokens(title).concat(titleTokens(title)));
  return parts.has(token);
}

/**
 * Soft title relevance: exact substring, then family-token overlap.
 * "Senior Data Engineer" ↔ "Senior Data Platform Engineer" / "Lead Data Engineer".
 */
export function roleFamilyScore(jobTitle: string, preferred: string): number {
  const job = norm(jobTitle);
  const pref = norm(preferred);
  if (!pref) return 0;
  if (job === pref || job.includes(pref) || pref.includes(job)) {
    // Guard: prefer exact / contiguous phrase matches.
    if (job.includes(pref) || pref.includes(job)) return 1;
  }

  const prefFamily = roleFamilyTokens(pref);
  if (!prefFamily.length) {
    const toks = titleTokens(pref).filter((t) => !SENIORITY_STOP.has(t));
    if (!toks.length) return 0;
    const hits = toks.filter((t) => tokenInTitle(job, t)).length;
    return hits / toks.length;
  }
  const hits = prefFamily.filter((t) => tokenInTitle(job, t)).length;
  return hits / prefFamily.length;
}

function roleMatch(job: ApiJob, roles: string[]): { ok: boolean; score: number } {
  if (!roles.length) return { ok: true, score: 0.5 };
  let best = 0;
  for (const role of roles) {
    best = Math.max(best, roleFamilyScore(job.title, role));
    for (const hint of ROLE_TRACK_HINTS) {
      if (hint.pattern.test(role) && job.track && hint.tracks.includes(job.track)) {
        best = Math.max(best, 0.7);
      }
    }
  }
  // Require solid family overlap — not exact title equality.
  return { ok: best >= 0.6, score: best };
}

function inferSeniorityFromYears(years: number | null | undefined): string | null {
  if (years == null || !Number.isFinite(years) || years < 0) return null;
  if (years < 2) return "junior";
  if (years < 5) return "mid";
  if (years < 8) return "senior";
  if (years < 12) return "staff";
  return "principal";
}

function extractYearsRequired(text: string): number | null {
  const blob = String(text || "");
  const m =
    blob.match(/(\d{1,2})\+?\s*(?:\+)?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp)/i) ||
    blob.match(/(?:experience|exp)[:\s]+(\d{1,2})\+?\s*(?:years?|yrs?)/i) ||
    blob.match(/(\d{1,2})\+?\s*(?:years?|yrs?)\s+(?:required|minimum|min\.?)/i);
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isFinite(n) && n >= 0 && n <= 50 ? n : null;
}

/** Typical years midpoint per band — used only when JD has no explicit years. */
const BAND_YEARS: Record<string, number> = {
  intern: 0,
  junior: 1,
  mid: 3,
  senior: 6,
  staff: 9,
  principal: 12,
  lead: 8,
};

function seniorityBandScore(
  jobSeniority: string | null,
  preferredBands: string[],
): { score: number; distance: number } {
  const jobSen = (jobSeniority || "").toLowerCase();
  if (!preferredBands.length) return { score: 0.5, distance: 0 };
  if (!jobSen) return { score: 0.55, distance: 0 };
  if (preferredBands.includes(jobSen)) return { score: 1, distance: 0 };
  const ji = SENIORITY_ORDER.indexOf(jobSen);
  if (ji < 0) return { score: 0.4, distance: 2 };
  const dists = preferredBands.map((w) => {
    const wi = SENIORITY_ORDER.indexOf(w);
    return wi < 0 ? 3 : Math.abs(wi - ji);
  });
  const d = Math.min(...dists);
  if (d === 0) return { score: 1, distance: 0 };
  if (d === 1) return { score: 0.7, distance: 1 };
  if (d === 2) return { score: 0.35, distance: 2 };
  return { score: 0.12, distance: d };
}

function yearsGapMultiplier(
  candidateYears: number | null | undefined,
  jobYearsRequired: number | null,
  jobSeniority: string | null,
): { mult: number; note: string | null } {
  if (candidateYears == null || !Number.isFinite(candidateYears)) {
    return { mult: 1, note: null };
  }
  let required = jobYearsRequired;
  let invented = false;
  if (required == null && jobSeniority) {
    // No explicit JD years — do not invent a hard requirement; soft-compare to band midpoint only.
    const mid = BAND_YEARS[jobSeniority.toLowerCase()];
    if (mid != null) {
      required = mid;
      invented = true;
    }
  }
  if (required == null) {
    return {
      mult: 1,
      note: "Experience requirement unspecified in listing — seniority compatibility is uncertain",
    };
  }
  const gap = required - candidateYears;
  if (gap <= 0) return { mult: 1, note: null };
  if (invented) {
    // Soft heuristic only (no explicit JD years).
    if (gap >= 5) {
      return {
        mult: 0.35,
        note: `Strong skill overlap possible, but this ${jobSeniority} role typically expects more experience than your profile indicates`,
      };
    }
    if (gap >= 3) {
      return {
        mult: 0.55,
        note: `Seniority band may require more experience than your ${candidateYears} years indicate`,
      };
    }
    return { mult: 0.8, note: null };
  }
  // Explicit JD years — material penalty, never auto-reject.
  if (gap >= 4) {
    return {
      mult: 0.25,
      note: `Listing asks for ~${required}+ years; your profile shows ${candidateYears} — substantial experience gap`,
    };
  }
  if (gap >= 2) {
    return {
      mult: 0.45,
      note: `Listing asks for ~${required}+ years; your profile shows ${candidateYears}`,
    };
  }
  return {
    mult: 0.75,
    note: `Listing asks for ~${required}+ years; your profile shows ${candidateYears}`,
  };
}

function salaryMaxCad(job: ApiJob, fx: number): number | null {
  if (job.salary_max_cad != null) return job.salary_max_cad;
  if (job.salary_max == null || !job.salary_currency) return null;
  const cur = job.salary_currency.toUpperCase();
  if (cur === "CAD") return job.salary_max;
  if (cur === "USD") return job.salary_max * fx;
  return null;
}

function salaryMinCad(job: ApiJob, fx: number): number | null {
  if (job.salary_min == null || !job.salary_currency) return salaryMaxCad(job, fx);
  const cur = job.salary_currency.toUpperCase();
  if (cur === "CAD") return job.salary_min;
  if (cur === "USD") return job.salary_min * fx;
  return null;
}

/**
 * Salary floor filter.
 * - flexible (API/MCP default): advertised max CAD may meet the floor
 * - strict: advertised min CAD must meet the floor
 */
export function salaryMeetsMinimum(
  job: ApiJob,
  minimumCad: number | undefined,
  mode: "strict" | "flexible",
  fx: number,
): { pass: boolean; meets_with_max_only: boolean; reason: string } {
  if (minimumCad == null || !Number.isFinite(minimumCad) || minimumCad <= 0) {
    return { pass: true, meets_with_max_only: false, reason: "no minimum" };
  }
  if (!job.salary_available) {
    // Match path historically soft-includes undisclosed (scored with a gap note).
    return { pass: true, meets_with_max_only: false, reason: "undisclosed" };
  }
  const maxCad = salaryMaxCad(job, fx);
  const minCad = salaryMinCad(job, fx);
  if (maxCad == null) {
    return { pass: true, meets_with_max_only: false, reason: "incomparable" };
  }
  if (maxCad < minimumCad) {
    return { pass: false, meets_with_max_only: false, reason: "below minimum" };
  }
  const meetsWithMaxOnly =
    minCad != null && Number.isFinite(minCad) && minCad < minimumCad && maxCad >= minimumCad;
  if (mode === "strict" && meetsWithMaxOnly) {
    return {
      pass: false,
      meets_with_max_only: true,
      reason: "range starts below minimum (strict)",
    };
  }
  return {
    pass: true,
    meets_with_max_only: meetsWithMaxOnly,
    reason: meetsWithMaxOnly ? "max meets minimum" : "meets minimum",
  };
}

function normalizeArrangements(input: MatchProfileInput): string[] {
  const raw = (input.work_arrangements || [])
    .map((a) => norm(a))
    .filter((a) => a === "remote" || a === "hybrid" || a === "onsite");
  if (raw.length) return [...new Set(raw)];
  // Backward compatible: remote_preference=true → remote-only hard filter.
  if (input.remote_preference === true) return ["remote"];
  return [];
}

function arrangementAllowed(job: ApiJob, allowed: string[]): boolean {
  if (!allowed.length) return true;
  const arr = (job.work_arrangement || "unknown").toLowerCase();
  if (arr === "unknown" || arr === "unspecified") {
    // Unknown arrangement: do not hard-exclude (Canada eligibility already applied).
    return true;
  }
  return allowed.includes(arr);
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

export function matchProfile(
  snapshot: ApiSnapshot,
  input: MatchProfileInput,
): {
  matches: MatchResult[];
  dataset_id: string;
  generated_at: string;
  note: string;
  filter_semantics?: {
    arrangements: string[];
    salary_mode: "strict" | "flexible";
    role_matching: "family_tokens";
  };
} {
  const skills = (input.skills || []).map(norm).filter(Boolean);
  const roles = (input.preferred_roles || []).map(norm).filter(Boolean);
  const locations = (input.preferred_locations || []).map(norm).filter(Boolean);
  const limit = Math.min(25, Math.max(1, input.limit || 10));
  const fx = Number(snapshot.usd_to_cad) || 1.35;
  const allowedArrangements = normalizeArrangements(input);
  const salaryMode: "strict" | "flexible" =
    input.salary_mode === "strict" ? "strict" : "flexible";

  const preferredBands = [
    ...(input.seniority ? [norm(input.seniority)] : []),
    ...(inferSeniorityFromYears(input.years_experience)
      ? [inferSeniorityFromYears(input.years_experience) as string]
      : []),
  ].filter(Boolean);

  // Arrangement + salary handled in-match (not via remote-only search filter) so
  // remote+hybrid profiles are expressible without breaking remote_preference.
  const geoFilters: SearchFilters = {
    remote: undefined,
    salary_min: undefined,
    seniority: undefined,
    limit: 500,
  };

  const scored: MatchResult[] = [];
  for (const job of snapshot.jobs) {
    if (!jobMatchesFilters(job, geoFilters, fx)) continue;

    if (!arrangementAllowed(job, allowedArrangements)) continue;

    const sal = salaryMeetsMinimum(job, input.minimum_salary, salaryMode, fx);
    if (!sal.pass) continue;

    if (locations.length) {
      const locBlob = `${job.location} ${job.province || ""}`.toLowerCase();
      const locOk =
        locations.some((l) => locBlob.includes(l)) ||
        (allowedArrangements.includes("remote") && job.work_arrangement === "remote");
      if (!locOk) continue;
    }

    const role = roleMatch(job, roles);
    if (!role.ok) continue;

    const matchingSkills = skills.filter((s) => skillHit(job, s));
    const unconfirmedSkills = skills.filter((s) => !skillHit(job, s));

    const band = seniorityBandScore(job.seniority, preferredBands);
    const jobYears = extractYearsRequired(job.description_excerpt || "");
    const years = yearsGapMultiplier(input.years_experience, jobYears, job.seniority);
    const senScore = Math.min(1, band.score * years.mult);

    let score = 0;
    // Title / role ~25%
    if (roles.length) score += Math.round(25 * role.score);
    else score += 12;
    // Skills ~25%
    if (skills.length) {
      score += Math.round(25 * (matchingSkills.length / skills.length));
    } else {
      score += 8;
    }
    // Seniority / experience ~30% — material influence
    score += Math.round(30 * senScore);
    // Discipline / track presence ~10%
    if (job.track) score += 7;
    if (job.verified) score += 3;
    // Arrangement preference ~10%
    if (allowedArrangements.length) {
      const arr = (job.work_arrangement || "").toLowerCase();
      if (allowedArrangements.includes(arr)) score += 10;
      else score += 4; // unknown arrangement soft credit
    } else {
      score += 5;
    }
    // Large seniority/experience gaps must not look like strong matches on skills alone.
    if (senScore < 0.4) {
      score = Math.min(score, Math.round(40 + senScore * 25));
    }

    // "gaps" retained for API compatibility — unconfirmed / soft notes only.
    const gaps: string[] = [];
    if (unconfirmedSkills.length) {
      gaps.push(
        `Skills not mentioned in listing (unconfirmed, not necessarily missing): ${unconfirmedSkills.slice(0, 5).join(", ")}`,
      );
    }
    if (years.note) gaps.push(years.note);
    else if (
      preferredBands.length &&
      job.seniority &&
      !preferredBands.includes((job.seniority || "").toLowerCase()) &&
      band.distance >= 2
    ) {
      gaps.push(
        `Seniority band differs (job=${job.seniority || "unspecified"}, profile≈${preferredBands[0]})`,
      );
    }
    if (!job.salary_available && input.minimum_salary) {
      gaps.push("Salary undisclosed — could not confirm compensation floor from employer text");
    }
    if (sal.meets_with_max_only) {
      gaps.push("Salary range overlaps your minimum, but starts below it");
    }

    const explanationParts = [
      roles.length
        ? role.score >= 0.99
          ? `Title closely matches preferred role (${roles.slice(0, 2).join(", ")})`
          : `Role family overlap with preferred title (${roles.slice(0, 2).join(", ")})`
        : null,
      matchingSkills.length
        ? `Confirmed matching skills: ${matchingSkills.slice(0, 6).join(", ")}`
        : skills.length
          ? "No profile skills evidenced in listing tags"
          : null,
      years.note
        ? years.note
        : senScore >= 0.9
          ? "Seniority compatible"
          : senScore < 0.5
            ? "Seniority / experience may be a stretch for this listing"
            : null,
      `Canada-eligible listing (${job.work_arrangement}, scope=${job.remote_scope})`,
      job.salary_available
        ? sal.meets_with_max_only
          ? `Advertised range ${job.salary_currency} ${Math.round(job.salary_min || 0).toLocaleString()}–${Math.round(job.salary_max || 0).toLocaleString()} overlaps your floor at the high end only`
          : `Advertised pay up to ${job.salary_currency} ${Math.round(job.salary_max || 0).toLocaleString()}`
        : "No advertised annual salary",
    ].filter(Boolean);

    scored.push({
      id: job.id,
      title: job.title,
      company: job.company,
      location: job.location,
      apply_url: job.apply_url,
      match_score: Math.min(99, Math.max(1, score)),
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
      "not a probability of being hired, and not a full Canadian labour-market census. " +
      `Arrangement filter: ${allowedArrangements.length ? allowedArrangements.join("+") : "none (all arrangements)"}; ` +
      `salary mode: ${salaryMode} (${salaryMode === "flexible" ? "max may meet floor" : "min must meet floor"}).`,
    filter_semantics: {
      arrangements: allowedArrangements,
      salary_mode: salaryMode,
      role_matching: "family_tokens",
    },
  };
}
