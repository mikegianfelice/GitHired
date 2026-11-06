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

export function parseSearchFilters(params: URLSearchParams): SearchFilters {
  const sortRaw = (params.get("sort") || "relevance").toLowerCase();
  const sort =
    sortRaw === "salary" || sortRaw === "freshness" || sortRaw === "relevance"
      ? sortRaw
      : "relevance";
  const limitRaw = Number(params.get("limit") || DEFAULT_LIMIT);
  return {
    q: params.get("q")?.trim() || undefined,
    location: params.get("location")?.trim() || undefined,
    province: params.get("province")?.trim()?.toUpperCase() || undefined,
    remote: parseBool(params.get("remote")),
    work_mode: params.get("work_mode")?.trim()?.toLowerCase() || undefined,
    salary_min: params.get("salary_min") != null ? Number(params.get("salary_min")) : undefined,
    salary_max: params.get("salary_max") != null ? Number(params.get("salary_max")) : undefined,
    salary_disclosed: parseBool(params.get("salary_disclosed")),
    seniority: params.get("seniority")?.trim()?.toLowerCase() || undefined,
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
    const h = haystack(job);
    const all = tokens(filters.q);
    if (all.length) {
      const hits = all.filter((t) => hasToken(h, t) || hasToken(job.title, t)).length;
      // Single token: must match. Multi-token: require all tokens (precision over recall).
      if (hits < all.length) return false;
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
