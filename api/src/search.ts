import type { ApiJob, ApiSnapshot, SearchFilters } from "./types";

const MAX_LIMIT = 50;
const DEFAULT_LIMIT = 20;

export function parseBool(value: string | null | undefined): boolean | undefined {
  if (value == null || value === "") return undefined;
  const v = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(v)) return true;
  if (["0", "false", "no", "off"].includes(v)) return false;
  return undefined;
}

export class SearchFilterValidationError extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "SearchFilterValidationError";
    this.code = code;
  }
}

const WORK_MODES = new Set(["remote", "hybrid", "onsite"]);

const PROVINCE_NAME_TO_CODE: Record<string, string> = {
  "ontario": "ON",
  "quebec": "QC",
  "british columbia": "BC",
  "alberta": "AB",
  "manitoba": "MB",
  "saskatchewan": "SK",
  "nova scotia": "NS",
  "new brunswick": "NB",
  "newfoundland": "NL",
  "newfoundland and labrador": "NL",
  "prince edward island": "PE",
  "yukon": "YT",
  "northwest territories": "NT",
  "nunavut": "NU",
};

function normalizeProvinceInput(raw: string | null | undefined): string | undefined {
  if (!raw) return undefined;
  const txt = raw.trim();
  if (!txt) return undefined;
  const up = txt.toUpperCase();
  // Accept valid two-letter codes in any case
  if (Object.values(PROVINCE_NAME_TO_CODE).includes(up)) return up;
  // Accept full names case-insensitively
  const code = PROVINCE_NAME_TO_CODE[txt.trim().toLowerCase()];
  if (code) return code;
  throw new SearchFilterValidationError(
    "invalid_province",
    `Unrecognized province '${raw}'. Use a two-letter code (e.g. ON) or full name (e.g. Ontario).`,
  );
}

function normalizeSeniority(raw: string | null | undefined): string | undefined {
  if (raw == null) return undefined;
  const s = raw.trim().toLowerCase();
  if (!s) return undefined;
  if (s === "sr") return "senior";
  if (s === "jr") return "junior";
  if (s === "intermediate") return "mid";
  return s;
}

export function parseSearchFilters(params: URLSearchParams): SearchFilters {
  const sortRaw = (params.get("sort") || "relevance").toLowerCase();
  const sort =
    sortRaw === "salary" || sortRaw === "freshness" || sortRaw === "relevance"
      ? sortRaw
      : "relevance";
  const limitRaw = Number(params.get("limit") || DEFAULT_LIMIT);
  const salaryMinRaw =
    params.get("salary_min") != null ? Number(params.get("salary_min")) : undefined;
  const salaryMaxRaw =
    params.get("salary_max") != null ? Number(params.get("salary_max")) : undefined;
  const workModeRaw = params.get("work_mode")?.trim()?.toLowerCase() || undefined;
  if (workModeRaw && !WORK_MODES.has(workModeRaw)) {
    throw new SearchFilterValidationError(
      "invalid_work_mode",
      `Unsupported work_mode '${workModeRaw}'. Allowed values: remote, hybrid, onsite.`,
    );
  }
  return {
    q: params.get("q")?.trim() || undefined,
    location: params.get("location")?.trim() || undefined,
    province: normalizeProvinceInput(params.get("province") || undefined),
    remote: parseBool(params.get("remote")),
    work_mode: workModeRaw,
    // Non-positive / NaN salary bounds are ignored (never invent floors/ceilings).
    salary_min:
      salaryMinRaw != null && Number.isFinite(salaryMinRaw) && salaryMinRaw > 0
        ? salaryMinRaw
        : undefined,
    salary_max:
      salaryMaxRaw != null && Number.isFinite(salaryMaxRaw) && salaryMaxRaw > 0
        ? salaryMaxRaw
        : undefined,
    salary_disclosed: parseBool(params.get("salary_disclosed")),
    seniority: normalizeSeniority(params.get("seniority")),
    company: params.get("company")?.trim() || undefined,
    sort,
    limit: Number.isFinite(limitRaw) ? Math.min(MAX_LIMIT, Math.max(1, Math.floor(limitRaw))) : DEFAULT_LIMIT,
    cursor: params.get("cursor")?.trim() || undefined,
  };
}

function tokens(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9+#.]+/i)
    .filter((t) => t.length >= 2);
}

function haystack(job: ApiJob): string {
  return [
    job.title,
    job.company,
    job.location,
    job.province || "",
    job.track || "",
    job.seniority || "",
    job.technologies.join(" "),
    job.description_excerpt || "",
  ]
    .join(" ")
    .toLowerCase();
}

function hasToken(hay: string, token: string): boolean {
  // Tokenize haystack so "data" does not hit "Database".
  return tokens(hay).includes(token.toLowerCase());
}

function titleOrRoleFields(job: ApiJob): string {
  return [job.title, job.track || "", job.seniority || ""].join(" ").toLowerCase();
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

function relevanceScore(job: ApiJob, q: string | undefined): number {
  if (!q) return 0;
  const h = haystack(job);
  let score = 0;
  for (const t of tokens(q)) {
    if (hasToken(job.title, t)) score += 8;
    else if (hasToken(job.company, t)) score += 5;
    else if (job.technologies.some((x) => hasToken(x, t))) score += 4;
    else if (hasToken(h, t)) score += 2;
  }
  if (job.salary_available) score += 1;
  if (job.verified) score += 1;
  return score;
}

function salaryCad(job: ApiJob, fx: number): number | null {
  if (job.salary_max_cad != null) return job.salary_max_cad;
  if (job.salary_max == null || !job.salary_currency) return null;
  const cur = job.salary_currency.toUpperCase();
  if (cur === "CAD") return job.salary_max;
  if (cur === "USD") return job.salary_max * fx;
  return null;
}

/** Salary filters apply to advertised annual base only (never estimates). */
export function jobMatchesFilters(job: ApiJob, filters: SearchFilters, fx: number): boolean {
  if (filters.q) {
    const all = tokens(filters.q);
    if (all.length) {
      // Token presence across any field
      const inAny = all.filter(
        (t) =>
          hasToken(job.title, t) ||
          hasToken(job.company, t) ||
          job.technologies.some((x) => hasToken(x, t)) ||
          hasToken(haystack(job), t),
      ).length;
      if (inAny < all.length) return false;
      // Guardrail: exclude description-only matches for role-family queries.
      const roleHits = all.filter(
        (t) =>
          !SENIORITY_TOKENS.has(t) &&
          !GENERIC_ROLE_TOKENS.has(t) &&
          hasToken(titleOrRoleFields(job), t),
      ).length;
      const companyHits = all.filter((t) => hasToken(job.company, t)).length;
      const techHits = all.filter((t) => job.technologies.some((x) => hasToken(x, t))).length;
      // If none of the tokens hit title/track/seniority/company/tech, it's a weak description-only match → exclude.
      if (roleHits === 0 && companyHits === 0 && techHits === 0) return false;
    }
  }
  if (filters.location) {
    const needle = filters.location.toLowerCase();
    if (!`${job.location} ${job.province || ""}`.toLowerCase().includes(needle)) return false;
  }
  if (filters.province) {
    if ((job.province || "").toUpperCase() !== filters.province.toUpperCase()) return false;
  }
  if (filters.remote === true) {
    if (job.work_arrangement !== "remote" && job.remote_scope === "local") return false;
    if (job.work_arrangement !== "remote" && !["canada", "province"].includes(job.remote_scope)) {
      if (job.work_arrangement !== "remote") return false;
    }
  }
  if (filters.remote === false && job.work_arrangement === "remote") return false;
  if (filters.work_mode) {
    const mode = filters.work_mode;
    if (mode === "remote" && job.work_arrangement !== "remote") return false;
    if (mode === "hybrid" && job.work_arrangement !== "hybrid") return false;
    if (mode === "onsite" && job.work_arrangement !== "onsite") return false;
  }
  if (filters.salary_disclosed === true && !job.salary_available) return false;
  if (filters.salary_disclosed === false && job.salary_available) return false;
  if (filters.salary_min != null && Number.isFinite(filters.salary_min)) {
    const cad = salaryCad(job, fx);
    if (cad == null || cad < filters.salary_min) return false;
  }
  if (filters.salary_max != null && Number.isFinite(filters.salary_max)) {
    const cad = salaryCad(job, fx);
    // Compare against max advertised CAD; if undisclosed, exclude when max filter set.
    if (cad == null || cad > filters.salary_max) return false;
  }
  if (filters.seniority) {
    if ((job.seniority || "").toLowerCase() !== filters.seniority.toLowerCase()) return false;
  }
  if (filters.company) {
    if (!job.company.toLowerCase().includes(filters.company.toLowerCase())) return false;
  }
  return true;
}

function decodeCursor(cursor: string | undefined): number {
  if (!cursor) return 0;
  try {
    const raw = atob(cursor);
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? Math.floor(n) : 0;
  } catch {
    return 0;
  }
}

function encodeCursor(offset: number): string {
  return btoa(String(offset));
}

export interface SearchResult {
  jobs: ApiJob[];
  total: number;
  limit: number;
  next_cursor: string | null;
  applied_filters: SearchFilters;
  dataset_id: string;
  generated_at: string;
}

export function searchJobs(snapshot: ApiSnapshot, filters: SearchFilters): SearchResult {
  const fx = Number(snapshot.usd_to_cad) || 1.35;
  const matched = snapshot.jobs.filter((j) => jobMatchesFilters(j, filters, fx));

  const sort = filters.sort || "relevance";
  matched.sort((a, b) => {
    if (sort === "salary") {
      return (salaryCad(b, fx) || 0) - (salaryCad(a, fx) || 0);
    }
    if (sort === "freshness") {
      return String(b.last_verified).localeCompare(String(a.last_verified));
    }
    const rb = relevanceScore(b, filters.q);
    const ra = relevanceScore(a, filters.q);
    if (rb !== ra) return rb - ra;
    return (salaryCad(b, fx) || 0) - (salaryCad(a, fx) || 0);
  });

  const limit = filters.limit || DEFAULT_LIMIT;
  const offset = decodeCursor(filters.cursor);
  const page = matched.slice(offset, offset + limit);
  const next = offset + limit < matched.length ? encodeCursor(offset + limit) : null;

  // List responses omit bulky excerpts unless single-id fetch.
  const jobs = page.map((j) => {
    const { description_excerpt: _d, ...rest } = j;
    return rest as ApiJob;
  });

  return {
    jobs,
    total: matched.length,
    limit,
    next_cursor: next,
    applied_filters: filters,
    dataset_id: snapshot.dataset_id,
    generated_at: snapshot.generated_at,
  };
}

export function getJobById(snapshot: ApiSnapshot, id: string): ApiJob | null {
  const job = snapshot.jobs.find((j) => j.id === id);
  return job || null;
}

export function compactJob(job: ApiJob): Record<string, unknown> {
  return {
    id: job.id,
    title: job.title,
    company: job.company,
    location: job.location,
    province: job.province,
    work_arrangement: job.work_arrangement,
    remote_scope: job.remote_scope,
    seniority: job.seniority,
    track: job.track,
    salary_min: job.salary_min,
    salary_max: job.salary_max,
    salary_currency: job.salary_currency,
    salary_available: job.salary_available,
    salary_max_cad: job.salary_max_cad,
    apply_url: job.apply_url,
    technologies: job.technologies,
    last_verified: job.last_verified,
    source: job.source,
  };
}
