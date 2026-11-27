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

/**
 * Profile specialization → broader job tag (confirmed only when job lists the broader label).
 * Do NOT map PySpark→Python or Node→JavaScript — that invents confirmed skill overlap.
 */
const RELATED: Record<string, string[]> = {
  postgresql: ["sql"],
  mysql: ["sql"],
  "sql server": ["sql"],
};

/** Expand job-side tags so profile Python matches a job tagged PySpark. */
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

/** Preferred-role → job.track affinity (boost only; never satisfies the role gate alone). */
const ROLE_TRACK_HINTS: Array<{ pattern: RegExp; tracks: string[] }> = [
  { pattern: /\bdata\s+engineer|\bdata\s+platform|\betl\b/i, tracks: ["data_engineering"] },
  { pattern: /\banalytics\s+engineer/i, tracks: ["analytics_engineering", "data_engineering"] },
  {
    pattern: /\bforward[\s-]?deployed\b/i,
    tracks: ["forward_deployed", "ai_engineering", "ml_engineering"],
  },
  {
    pattern: /\b(?:ai|ml)\s+engineer\b|\bapplied\s+ai\b/i,
    tracks: ["ai_engineering", "ml_engineering"],
  },
  {
    pattern: /\bsolutions?\s+architect\b/i,
    tracks: ["platform_engineering", "ai_engineering", "forward_deployed"],
  },
  // Avoid matching "Data Platform Engineer" as generic platform/devops.
  {
    pattern: /(?<!\bdata\s)\bplatform\s+engineer\b|\bcloud\s+engineer\b|\binfrastructure\b/i,
    tracks: ["platform_engineering", "devops_sre"],
  },
  { pattern: /\bfrontend|\bfront[\s-]?end|\breact\b/i, tracks: ["software_engineering"] },
  {
    pattern: /\bsite\s+reliability|\bdevops\b|\bsre\b/i,
    tracks: ["devops_sre", "platform_engineering"],
  },
];

/** Short tokens that carry role meaning (kept despite length ≤ 2). */
const SHORT_ROLE_TOKENS = new Set(["ai", "ml", "bi", "qa", "ux", "ui", "sre", "de", "ae"]);

/** Tokens that must not alone make "AI Engineer" match every engineer title. */
const GENERIC_ROLE_TOKENS = new Set([
  "engineer",
  "developer",
  "software",
  "programmer",
  "specialist",
  "consultant",
  "manager",
  "associate",
  "member",
]);

/**
 * Preferred-role specific tokens → job-title synonyms (title gate only).
 * Keeps "Data Engineer" discoverable for lakehouse/ETL titles without
 * opening the gate for generic Software/DevOps engineers.
 */
const SPECIFIC_TOKEN_ALIASES: Record<string, string[]> = {
  data: ["lakehouse", "etl"],
  ai: ["llm", "ml"],
  ml: ["ai", "llm"],
  deployed: ["forward"],
  forward: ["deployed"],
};

function canonicalSkill(skill: string): string {
  const s = norm(skill)
    .replace(/_/g, " ")
    .replace(/[/-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return SKILL_ALIASES[s] || s;
}

function skillMentionedInText(text: string, skill: string): boolean {
  const escaped = skill
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    .replace(/\s+/g, "\\s+");
  const re = new RegExp(`(?:^|[^a-z0-9+#./])${escaped}(?=[^a-z0-9+#./]|$)`, "i");
  return re.test(text);
}

function skillHit(job: ApiJob, skill: string): boolean {
  const s = canonicalSkill(skill);
  if (!s) return false;
  const jobSkills = job.technologies.map((t) => canonicalSkill(t));
  const expanded = new Set(jobSkills);
  for (const t of jobSkills) {
    for (const r of JOB_EXPAND[t] || []) expanded.add(canonicalSkill(r));
  }
  if (expanded.has(s)) return true;
  if ((RELATED[s] || []).some((r) => expanded.has(canonicalSkill(r)))) return true;
  // Word-boundary evidence only — never raw substring ("rag" in "storage", "mcp" in noise).
  const blob = `${job.title} ${job.track || ""} ${(job.description_excerpt || "").slice(0, 800)}`;
  return skillMentionedInText(blob, s);
}

function titleTokens(text: string): string[] {
  return norm(text)
    .split(/[^a-z0-9+#.]+/)
    .filter((t) => t.length > 1);
}

/** Role-family tokens with seniority/level words removed. */
function roleFamilyTokens(text: string): string[] {
  return titleTokens(text).filter((t) => {
    if (SENIORITY_STOP.has(t)) return false;
    if (t.length > 2) return true;
    return SHORT_ROLE_TOKENS.has(t);
  });
}

function tokenInTitle(title: string, token: string): boolean {
  // Whole-token match only — "data" must not hit "datastores" / "database".
  const parts = new Set(roleFamilyTokens(title).concat(titleTokens(title)));
  if (parts.has(token)) return true;
  for (const alias of SPECIFIC_TOKEN_ALIASES[token] || []) {
    if (parts.has(alias)) return true;
  }
  return false;
}

/**
 * Soft title relevance: exact substring, then family-token overlap.
 * Specific tokens (data, ai, platform, …) must hit — "AI Engineer" must not
 * match every title that merely contains "engineer".
 */
export function roleFamilyScore(jobTitle: string, preferred: string): number {
  const job = norm(jobTitle);
  const pref = norm(preferred);
  if (!pref) return 0;
  if (job === pref) return 1;
  if (job.includes(pref) || pref.includes(job)) {
    // Contiguous phrase match, but reject ultra-short preferred collapsing into generics.
    const prefFamily = roleFamilyTokens(pref);
    const specific = prefFamily.filter((t) => !GENERIC_ROLE_TOKENS.has(t));
    if (!specific.length || specific.some((t) => tokenInTitle(job, t))) return 1;
  }

  const prefFamily = roleFamilyTokens(pref);
  if (!prefFamily.length) {
    const toks = titleTokens(pref).filter((t) => !SENIORITY_STOP.has(t));
    if (!toks.length) return 0;
    const hits = toks.filter((t) => tokenInTitle(job, t)).length;
    return hits / toks.length;
  }

  const specific = prefFamily.filter((t) => !GENERIC_ROLE_TOKENS.has(t));
  const generic = prefFamily.filter((t) => GENERIC_ROLE_TOKENS.has(t));
  if (specific.length) {
    const specificHits = specific.filter((t) => tokenInTitle(job, t)).length;
    if (specificHits === 0) {
      return generic.some((t) => tokenInTitle(job, t)) ? 0.35 : 0;
    }
    const specScore = specificHits / specific.length;
    const genBonus = generic.length
      ? 0.15 * (generic.filter((t) => tokenInTitle(job, t)).length / generic.length)
      : 0.1;
    // Partial specific overlap still clears the family gate when at least one
    // discriminative token hits (Data Platform Engineer ↔ Data Engineer).
    const raw = specScore * 0.85 + genBonus;
    return Math.min(1, Math.max(0.6, raw));
  }

  const hits = prefFamily.filter((t) => tokenInTitle(job, t)).length;
  return hits / prefFamily.length;
}

function trackAffinity(job: ApiJob, roles: string[]): number {
  if (!roles.length || !job.track) return 0;
  let best = 0;
  for (const role of roles) {
    for (const hint of ROLE_TRACK_HINTS) {
      if (hint.pattern.test(role) && hint.tracks.includes(job.track)) {
        best = Math.max(best, 1);
      }
    }
  }
  return best;
}

function roleMatch(job: ApiJob, roles: string[]): { ok: boolean; score: number; track: number } {
  if (!roles.length) return { ok: true, score: 0.5, track: 0 };
  let best = 0;
  for (const role of roles) {
    best = Math.max(best, roleFamilyScore(job.title, role));
  }
  const track = trackAffinity(job, roles);
  // Title family gate only — track affinity must not open the door alone.
  return { ok: best >= 0.6, score: best, track };
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
  jobTitle: string = "",
): { score: number; distance: number; note?: string | null } {
  const jobSen = (jobSeniority || "").toLowerCase();
  const juniorProfile = preferredBands.some((b) => b === "junior" || b === "intern");
  const candIdx = Math.max(
    -1,
    ...preferredBands.map((w) => SENIORITY_ORDER.indexOf(w)).filter((i) => i >= 0),
  );
  const seniorPlusProfile = candIdx >= SENIORITY_ORDER.indexOf("senior");
  const juniorJob =
    jobSen === "junior" || jobSen === "intern" || titleJuniorSignal(jobTitle);
  if (!preferredBands.length) return { score: 0.5, distance: 0 };

  // Senior+ candidate vs junior/entry role — soft directional mismatch (not a hard exclude).
  if (seniorPlusProfile && juniorJob) {
    return {
      score: 0.12,
      distance: 3,
      note: "Job is junior/entry-level; your profile targets more senior roles",
    };
  }

  // Unknown job seniority: cautious soft score — never invent junior eligibility.
  // For junior profiles, prefer titles that explicitly signal entry-level.
  if (!jobSen) {
    if (juniorProfile) {
      if (titleJuniorSignal(jobTitle)) return { score: 0.95, distance: 0 };
      if (titleSeniorSignal(jobTitle)) return { score: 0.18, distance: 3 };
      return { score: 0.35, distance: 1 };
    }
    if (seniorPlusProfile && titleJuniorSignal(jobTitle)) {
      return {
        score: 0.12,
        distance: 3,
        note: "Job is junior/entry-level; your profile targets more senior roles",
      };
    }
    return { score: 0.55, distance: 0 };
  }
  if (preferredBands.includes(jobSen)) return { score: 1, distance: 0 };
  const ji = SENIORITY_ORDER.indexOf(jobSen);
  if (ji < 0) return { score: 0.4, distance: 2 };
  const dists = preferredBands.map((w) => {
    const wi = SENIORITY_ORDER.indexOf(w);
    return wi < 0 ? 3 : Math.abs(wi - ji);
  });
  const d = Math.min(...dists);
  let score = 0.12;
  if (d === 0) score = 1;
  else if (d === 1) score = 0.7;
  else if (d === 2) score = 0.35;
  // Overqualified: candidate band clearly above job band.
  if (candIdx >= 0 && candIdx - ji >= 2) score = Math.min(score, 0.25);
  return { score, distance: d };
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

const COUNTRY_LOCATION_TOKENS = new Set(["canada", "canadian", "ca"]);

function isCountryLocationToken(token: string): boolean {
  return COUNTRY_LOCATION_TOKENS.has(norm(token));
}

function isProvinceCodeToken(token: string): boolean {
  return /^[a-z]{2}$/i.test(token.trim()) && token.trim().length <= 2;
}

/**
 * Geographic eligibility (hard filter) — applied before ranking.
 *
 * - Remote Canada-eligible jobs stay eligible when remote is allowed, regardless
 *   of HQ province (nationwide remote ≠ out-of-province hybrid).
 * - "Canada" in preferred_locations expands national remote eligibility and,
 *   alone, any Canada-eligible hybrid/onsite. When combined with province/city
 *   tokens, those regional tokens constrain hybrid/onsite — "Canada" must not
 *   open every provincial hybrid.
 */
export function locationAllowed(
  job: ApiJob,
  locations: string[],
  allowedArrangements: string[],
): boolean {
  if (!locations.length) return true;
  const countryPrefs = locations.filter(isCountryLocationToken);
  const regionalPrefs = locations.filter((l) => !isCountryLocationToken(l));
  const arr = (job.work_arrangement || "").toLowerCase();
  const remoteOk =
    allowedArrangements.includes("remote") || allowedArrangements.length === 0;
  const isRemote = arr === "remote";
  const canadaEligibleRemote =
    isRemote &&
    ["canada", "province", "americas", "local", "unspecified"].includes(
      (job.remote_scope || "").toLowerCase(),
    );

  if (isRemote && remoteOk && canadaEligibleRemote) {
    // Nationwide / Canada-eligible remote: never reject solely for HQ province.
    return true;
  }

  const locBlob = `${job.location} ${job.province || ""}`.toLowerCase();
  const regionalHit = regionalPrefs.some((lraw) => {
    const l = String(lraw || "").trim().toLowerCase();
    if (!l) return false;
    if (isProvinceCodeToken(l)) {
      return (job.province || "").toUpperCase() === l.toUpperCase();
    }
    const re = new RegExp(`\\b${l.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&")}\\b`, "i");
    return re.test(locBlob);
  });

  if (regionalPrefs.length) {
    return regionalHit;
  }
  // Country-only preference: any Canada-facing listing (province set or Canada in location).
  if (countryPrefs.length) {
    if (job.province) return true;
    return /\bcanada\b|\bcanadian\b/i.test(locBlob);
  }
  return true;
}

function skillCoverageScore(matchingCount: number, profileSkillCount: number): number {
  // Broad profiles must not dilute confirmed overlap — score against a soft
  // expected band rather than matching/total (which punishes long skill lists).
  if (profileSkillCount <= 0) return 0.5;
  const expected = Math.min(8, Math.max(4, Math.ceil(profileSkillCount * 0.45)));
  return Math.min(1, matchingCount / expected);
}

function preferredRoleFamilyKey(role: string): string {
  const t = norm(role);
  if (/\bforward[\s-]?deployed\b/.test(t)) return "forward_deployed";
  if (/\b(?:ai|ml)\s+engineer\b|\bapplied\s+ai\b/.test(t)) return "ai";
  if (/\bdata\s+platform\b|\bdata\s+engineer\b|\betl\b/.test(t)) return "data";
  if (/\bsolutions?\s+architect\b|\barchitect\b/.test(t)) return "architect";
  if (/\bdevops\b|\bsre\b|\bsite\s+reliability\b/.test(t)) return "devops";
  if (/\bfrontend|\bfront[\s-]?end\b/.test(t)) return "frontend";
  if (/\bbackend\b|\bfull[\s-]?stack\b|\bsoftware\b/.test(t)) return "software";
  return t.split(/\s+/).slice(0, 2).join("_") || "other";
}

function bestRoleFamily(job: ApiJob, roles: string[]): string | null {
  if (!roles.length) return null;
  let bestKey: string | null = null;
  let bestScore = 0;
  for (const role of roles) {
    const s = roleFamilyScore(job.title, role);
    if (s > bestScore) {
      bestScore = s;
      bestKey = preferredRoleFamilyKey(role);
    }
  }
  return bestKey;
}

/**
 * Soft multi-role coverage after score sort.
 * Never promotes a weak match: candidates must be within ``scoreSlack`` of the
 * next pure-relevance pick. Prefers an unseen preferred-role family when scores
 * are close so FDE/AI are not buried under many DE-family hits.
 */
export function diversifyByRoleFamily<T extends { match_score: number; _family?: string | null }>(
  ranked: T[],
  opts: { limit: number; scoreSlack?: number },
): T[] {
  const limit = opts.limit;
  const scoreSlack = opts.scoreSlack ?? 8;
  if (ranked.length <= limit) return ranked.slice(0, limit);
  const out: T[] = [];
  const used = new Set<number>();
  const families = new Set<string>();
  while (out.length < limit) {
    let bestIdx = -1;
    for (let i = 0; i < ranked.length; i++) {
      if (used.has(i)) continue;
      if (bestIdx < 0) {
        bestIdx = i;
        continue;
      }
      const cand = ranked[i];
      const best = ranked[bestIdx];
      if (cand.match_score < best.match_score - scoreSlack) break;
      const candNew = Boolean(cand._family && !families.has(cand._family));
      const bestNew = Boolean(best._family && !families.has(best._family));
      if (candNew && !bestNew) {
        bestIdx = i;
        break;
      }
    }
    if (bestIdx < 0) break;
    used.add(bestIdx);
    const row = ranked[bestIdx];
    out.push(row);
    if (row._family) families.add(row._family);
  }
  return out;
}

function arrangementAllowed(job: ApiJob, allowed: string[]): boolean {
  if (!allowed.length) return true;
  const arr = (job.work_arrangement || "unknown").toLowerCase();
  // Explicit arrangement selection is a hard allow-list: remote-only must not
  // silently include unspecified/hybrid/onsite.
  if (arr === "unknown" || arr === "unspecified") {
    return false;
  }
  return allowed.includes(arr);
}

/** Title tokens that confirm junior / entry intent when job.seniority is missing. */
function titleJuniorSignal(title: string): boolean {
  return /\b(?:junior|jr\.?|entry[\s-]?level|new[\s-]?grad|graduate|trainee|intern|co-?op|coop)\b/i.test(
    title || "",
  );
}

function titleSeniorSignal(title: string): boolean {
  return /\b(?:senior|sr\.?|staff|principal|director|vp\b|head of)\b/i.test(title || "");
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
  remote_scope: string;
  province: string | null;
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

  const remoteStrength =
    input.remote_preference_strength === "prefer_remote" ? "prefer_remote" : "equal";

  type Scored = MatchResult & { _family?: string | null };
  const scored: Scored[] = [];
  for (const job of snapshot.jobs) {
    if (!jobMatchesFilters(job, geoFilters, fx)) continue;

    if (!arrangementAllowed(job, allowedArrangements)) continue;

    const sal = salaryMeetsMinimum(job, input.minimum_salary, salaryMode, fx);
    if (!sal.pass) continue;

    if (!locationAllowed(job, locations, allowedArrangements)) continue;

    const role = roleMatch(job, roles);
    if (!role.ok) continue;

    const matchingSkills = skills.filter((s) => skillHit(job, s));
    const unconfirmedSkills = skills.filter((s) => !skillHit(job, s));

    const band = seniorityBandScore(job.seniority, preferredBands, job.title);
    const jobYears = extractYearsRequired(job.description_excerpt || "");
    const years = yearsGapMultiplier(input.years_experience, jobYears, job.seniority);
    // Unspecified seniority is not a penalty when the title lacks junior signals
    // (common for Forward Deployed / Solutions Architect listings).
    let senScore = Math.min(1, band.score * years.mult);
    if (!(job.seniority || "").trim() && !titleJuniorSignal(job.title) && senScore < 0.7) {
      senScore = Math.max(senScore, 0.72);
    }

    let score = 0;
    // Title / role intent ~34%
    if (roles.length) score += Math.round(34 * role.score);
    else score += 12;
    // Exact / near-exact title credit
    if (roles.length && role.score >= 0.99) score += 4;
    // Track affinity with preferred roles ~8% (cannot open the gate alone)
    if (roles.length) score += Math.round(8 * role.track);
    else if (job.track) score += 4;
    // Skills ~16% — coverage vs soft expected band (not diluted by long profiles)
    if (skills.length) {
      score += Math.round(16 * skillCoverageScore(matchingSkills.length, skills.length));
    } else {
      score += 5;
    }
    // Seniority / experience ~26%
    score += Math.round(26 * senScore);
    if (job.verified) score += 2;
    // Arrangement preference ~8% flat when on the allow-list (remote≈hybrid when equal)
    if (allowedArrangements.length) {
      const arr = (job.work_arrangement || "").toLowerCase();
      if (allowedArrangements.includes(arr)) {
        score += 8;
        if (remoteStrength === "prefer_remote" && arr === "remote") score += 3;
      }
    } else {
      score += 4;
    }
    // Cap when title is only a soft family hit and track disagrees.
    if (roles.length && role.score < 0.75 && role.track < 1) {
      score = Math.min(score, 78);
    }
    // Large seniority/experience gaps must not look like strong matches on skills alone.
    if (senScore < 0.4) {
      score = Math.min(score, Math.round(35 + senScore * 25));
    }
    // Junior / 0-YOE profiles: boost confirmed entry titles; demote explicit senior bands.
    const juniorProfile = preferredBands.some((b) => b === "junior" || b === "intern");
    const seniorPlusProfile = preferredBands.some((b) =>
      ["senior", "staff", "principal", "lead"].includes(b),
    );
    if (juniorProfile) {
      if (titleJuniorSignal(job.title) || (job.seniority || "").toLowerCase() === "junior") {
        score = Math.min(99, score + 12);
      } else if (
        ["mid", "senior", "staff", "principal", "lead"].includes((job.seniority || "").toLowerCase()) ||
        titleSeniorSignal(job.title)
      ) {
        score = Math.max(1, score - 18);
      }
    } else if (seniorPlusProfile) {
      if (titleJuniorSignal(job.title) || (job.seniority || "").toLowerCase() === "junior") {
        score = Math.max(1, score - 20);
      } else if (role.score >= 0.7 && senScore >= 0.7) {
        score = Math.min(99, score + 6);
      }
    }

    // "gaps" retained for API compatibility — unconfirmed / soft notes only.
    const gaps: string[] = [];
    if (unconfirmedSkills.length) {
      gaps.push(
        `Skills not mentioned in listing (unconfirmed, not necessarily missing): ${unconfirmedSkills.slice(0, 5).join(", ")}`,
      );
    }
    if (band.note) gaps.push(band.note);
    if (years.note) gaps.push(years.note);
    else if (
      !band.note &&
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
      band.note
        ? band.note
        : years.note
          ? years.note
          : senScore >= 0.9
            ? "Seniority compatible"
            : senScore < 0.5
              ? "Seniority / experience may be a stretch for this listing"
              : null,
      job.remote_scope === "global"
        ? `Worldwide-remote listing (${job.work_arrangement}, scope=global; ranked below Canada-specific roles)`
        : `Canada-eligible listing (${job.work_arrangement}, scope=${job.remote_scope})`,
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
      remote_scope: job.remote_scope,
      province: job.province,
      _family: bestRoleFamily(job, roles),
    });
  }

  // Relevance first. Demote worldwide-remote only as a soft penalty / tie-break —
  // never let canada-vs-province grouping override large match_score gaps.
  scored.sort((a, b) => {
    const aGlobal = (a.remote_scope || "").toLowerCase() === "global" ? 1 : 0;
    const bGlobal = (b.remote_scope || "").toLowerCase() === "global" ? 1 : 0;
    if (aGlobal !== bGlobal) return aGlobal - bGlobal;
    return b.match_score - a.match_score || a.title.localeCompare(b.title);
  });

  const diversified = diversifyByRoleFamily(scored, { limit });
  const matches: MatchResult[] = diversified.map(({ _family: _f, ...rest }) => rest);

  return {
    matches,
    dataset_id: snapshot.dataset_id,
    generated_at: snapshot.generated_at,
    note:
      "Deterministic relevance against GitHired's tracked Canada-eligible and optional worldwide-remote jobs — not an LLM assessment, " +
      "not a probability of being hired, and not a full Canadian labour-market census. " +
      "Ranking is by match_score; worldwide-remote is demoted below Canada-eligible. " +
      "When multiple preferred roles are set, near-peer role-family diversity may reorder close scores. " +
      `Arrangement filter: ${allowedArrangements.length ? allowedArrangements.join("+") : "none (all arrangements)"}; ` +
      `remote preference strength: ${remoteStrength}; ` +
      `salary mode: ${salaryMode} (${salaryMode === "flexible" ? "max may meet floor" : "min must meet floor"}).`,
    filter_semantics: {
      arrangements: allowedArrangements,
      salary_mode: salaryMode,
      role_matching: "family_tokens",
    },
  };
}
