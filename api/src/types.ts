/** Shared API / MCP job types (mirrors jobseek.api_snapshot). */

export interface ApiJob {
  id: string;
  title: string;
  company: string;
  location: string;
  province: string | null;
  work_arrangement: string;
  remote_scope: string;
  seniority: string | null;
  track: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_available: boolean;
  salary_max_cad: number | null;
  salary_period: string | null;
  salary_kind: string;
  apply_url: string;
  verified: boolean;
  first_seen: string;
  last_verified: string;
  discovered_today: boolean;
  technologies: string[];
  source: string;
  description_excerpt?: string | null;
  description_complete?: boolean;
}

export interface CompanyStat {
  name: string;
  active_jobs: number;
}

export interface ApiSnapshot {
  schema_version: number;
  dataset_id: string;
  generated_at: string;
  source: string;
  limit: number;
  count: number;
  usd_to_cad: number;
  repo_url: string;
  website_url?: string;
  api_base_url?: string;
  salary_policy: Record<string, unknown>;
  eligibility: Record<string, unknown>;
  stats: {
    total_jobs: number;
    total_companies: number;
    remote_jobs: number;
    jobs_with_advertised_salary: number;
  };
  companies: CompanyStat[];
  disclaimer: string;
  jobs: ApiJob[];
}

export interface SearchFilters {
  q?: string;
  location?: string;
  province?: string;
  remote?: boolean;
  work_mode?: string;
  salary_min?: number;
  salary_max?: number;
  salary_disclosed?: boolean;
  seniority?: string;
  company?: string;
  sort?: "relevance" | "salary" | "freshness";
  limit?: number;
  cursor?: string;
}

export interface MatchProfileInput {
  skills?: string[];
  years_experience?: number;
  preferred_roles?: string[];
  preferred_locations?: string[];
  remote_preference?: boolean;
  minimum_salary?: number;
  seniority?: string;
  limit?: number;
}

export interface Env {
  ASSETS?: Fetcher;
  DATA?: R2Bucket;
  DATASET_PATH?: string;
  ENVIRONMENT?: string;
  RATE_LIMIT_PER_MINUTE?: string;
  STALE_AFTER_HOURS?: string;
}
