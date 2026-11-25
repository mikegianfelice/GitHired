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
const PROVINCE_CODE_TO_NAME: Record<string, string> = {
  ON: "Ontario",
  QC: "Quebec",
  BC: "British Columbia",
  AB: "Alberta",
  MB: "Manitoba",
  SK: "Saskatchewan",
  NS: "Nova Scotia",
  NB: "New Brunswick",
  NL: "Newfoundland and Labrador",
  PE: "Prince Edward Island",
  YT: "Yukon",
  NT: "Northwest Territories",
  NU: "Nunavut",
};
const PROVINCE_NAME_TO_CODE: Record<string, string> = Object.fromEntries(
  Object.entries(PROVINCE_CODE_TO_NAME).map(([code, name]) => [name.toLowerCase(), code]),
);

const SENIORITY_ALIASES: Record<string, string> = {
  sr: "senior",
  jr: "junior",
  "s.r.": "senior",
  "j.r.": "junior",
};
const ALLOWED_SENIORITY = new Set([
  "intern",
  "junior",
  "mid",
  "senior",
  "staff",
  "principal",
  "lead",
]);

function canonicalProvinceCode(input: string | null | undefined): string | undefined {
  if (!input) return undefined;
  const raw = input.trim();
  if (!raw) return undefined;
  // Accept case-insensitive two-letter codes
  const asCode = raw.length <= 3 ? raw.toUpperCase() : raw.toUpperCase();
  if (PROVINCE_CODE_TO_NAME[asCode]) return asCode;
  // Accept full names, case-insensitive
  const code = PROVINCE_NAME_TO_CODE[raw.toLowerCase()];
  if (code) return code;
  return undefined;
}

function canonicalSeniority(input: string | null | undefined): string | undefined {
  if (!input) return undefined;
  const raw = input.trim().toLowerCase();
  if (!raw) return undefined;
  const aliased = SENIORITY_ALIASES[raw] || raw;
  if (ALLOWED_SENIORITY.has(aliased)) return aliased;
  return undefined;
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
  const provinceRaw = params.get("province")?.trim() || undefined;
  let province: string | undefined = undefined;
  if (provinceRaw) {
    province = canonicalProvinceCode(provinceRaw);
    if (!province) {
      throw new SearchFilterValidationError(
        "invalid_province",
        `Unrecognized province '${provinceRaw}'. Accept 2-letter codes (e.g. ON) or full names (e.g. Ontario).`,
      );
    }
  }
  const seniorityCanon = canonicalSeniority(params.get("seniority")?.trim()?.toLowerCase() || undefined);
  if (params.get("seniority") && !seniorityCanon) {
    throw new SearchFilterValidationError(
      "invalid_seniority",
      `Unrecognized seniority '${params.get("seniority")}'. Allowed: intern, junior, mid, senior, staff, principal, lead (case-insensitive; sr/jr accepted).`,
    );
  }
  const REMOTE_SCOPES = new Set([
    "canada",
    "province",
    "americas",
    "global",
    "local",
    "unspecified",
  ]);
  const remoteScopeRaw = params.get("remote_scope")?.trim()?.toLowerCase() || undefined;
  if (remoteScopeRaw && !REMOTE_SCOPES.has(remoteScopeRaw)) {
    throw new SearchFilterValidationError(
      "invalid_remote_scope",
      `Unrecognized remote_scope '${remoteScopeRaw}'. Allowed: canada, province, americas, global, local, unspecified.`,
    );
  }
  return {
    q: params.get("q")?.trim() || undefined,
    location: params.get("location")?.trim() || undefined,
    province,
    remote: parseBool(params.get("remote")),
    work_mode: workModeRaw,
    remote_scope: remoteScopeRaw,
    exclude_global_remote: parseBool(params.get("exclude_global_remote")),
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
    seniority: seniorityCanon,
    company: params.get("company")?.trim() || undefined,
    sort,
    limit: Number.isFinite(limitRaw) ? Math.min(MAX_LIMIT, Math.max(1, Math.floor(limitRaw))) : DEFAULT_LIMIT,
    cursor: params.get("cursor")?.trim() || undefined,
  };
}

/** Lower rank sorts first. canada/province above global. */
export function remoteScopeRank(job: ApiJob): number {
  const s = (job.remote_scope || "").toLowerCase();
  if (s === "canada") return 0;
  if (s === "province" || (job.province && s !== "global")) return 1;
  if (s === "global") return 3;
  return 2;
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

function keywordHitFields(job: ApiJob): string[] {
  // Fields allowed to qualify a keyword filter; description is intentionally excluded (weak signal).
  return [
    job.title || "",
    job.company || "",
    job.location || "",
    job.province || "",
    job.track || "",
    job.seniority || "",
    job.technologies.join(" "),
  ].map((s) => s.toLowerCase());
}

function relevanceScore(job: ApiJob, q: string | undefined): number {
  if (!q) return 0;
  const h = haystack(job);
  let score = 0;
  for (const t of tokens(q)) {
    if (hasToken(job.title, t)) score += 10;
    else if (hasToken(job.track || "", t)) score += 7;
    else if (hasToken(job.company, t)) score += 5;
    else if (job.technologies.some((x) => hasToken(x, t))) score += 4;
    else if (hasToken(h, t)) score += 1; // description/other weak boost only
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
      const fields = keywordHitFields(job);
      // Require every token to appear in at least one non-description field.
      const allHit = all.every((t) => fields.some((f) => hasToken(f, t)));
      if (!allHit) return false;
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
  if (filters.remote_scope) {
    if ((job.remote_scope || "").toLowerCase() !== filters.remote_scope.toLowerCase()) return false;
  }
  if (filters.exclude_global_remote === true) {
    if ((job.remote_scope || "").toLowerCase() === "global") return false;
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
    // Always prefer Canada/province scope above worldwide-remote (global).
    const scopeDiff = remoteScopeRank(a) - remoteScopeRank(b);
    if (scopeDiff !== 0) return scopeDiff;
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

/** Recompute discovered_today from first_seen vs UTC today (export flag goes stale). */
export function withLiveDiscoveredToday(job: ApiJob, now: Date = new Date()): ApiJob {
  const raw = job.first_seen;
  if (!raw) return { ...job, discovered_today: false };
  const dt = new Date(`${raw}T00:00:00.000Z`);
  if (!Number.isFinite(dt.getTime())) return { ...job, discovered_today: false };
  const today = now.toISOString().slice(0, 10);
  const seen = dt.toISOString().slice(0, 10);
  return { ...job, discovered_today: seen === today };
}

export function compactJob(job: ApiJob): Record<string, unknown> {
  const live = withLiveDiscoveredToday(job);
  return {
    id: live.id,
    title: live.title,
    company: live.company,
    location: live.location,
    province: live.province,
    work_arrangement: live.work_arrangement,
    remote_scope: live.remote_scope,
    seniority: live.seniority,
    track: live.track,
    salary_min: live.salary_min,
    salary_max: live.salary_max,
    salary_currency: live.salary_currency,
    salary_available: live.salary_available,
    salary_max_cad: live.salary_max_cad,
    apply_url: live.apply_url,
    technologies: live.technologies,
    last_verified: live.last_verified,
    first_seen: live.first_seen,
    discovered_today: live.discovered_today,
    source: live.source,
  };
}
