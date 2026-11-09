import { datasetFreshness, loadSnapshot } from "./dataset";
import { matchProfile } from "./match";
import { checkRateLimit, clientIp } from "./rate-limit";
import { compactJob, getJobById, parseSearchFilters, searchJobs } from "./search";
import type { Env, MatchProfileInput } from "./types";

const CORS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Accept, MCP-Protocol-Version",
  "Access-Control-Max-Age": "86400",
};

export function json(data: unknown, status = 200, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data, null, 0), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=60",
      ...CORS,
      ...extra,
    },
  });
}

export function optionsResponse(): Response {
  return new Response(null, { status: 204, headers: CORS });
}

/** Empty acknowledgment for MCP notifications (Streamable HTTP). */
export function acceptedResponse(): Response {
  return new Response(null, { status: 202, headers: CORS });
}

function staleHours(env: Env): number {
  const n = Number(env.STALE_AFTER_HOURS || 48);
  return Number.isFinite(n) && n > 0 ? n : 48;
}

function rateLimit(env: Env): number {
  const n = Number(env.RATE_LIMIT_PER_MINUTE || 120);
  return Number.isFinite(n) && n > 0 ? n : 120;
}

async function enforceRateLimit(request: Request, env: Env): Promise<Response | null> {
  const ip = clientIp(request);
  const result = checkRateLimit(`rest:${ip}`, { limitPerMinute: rateLimit(env) });
  if (!result.allowed) {
    return json(
      {
        error: "rate_limited",
        message: "Too many requests. GitHired API is free; please slow down.",
        retry_after_ms: result.reset_ms,
      },
      429,
      { "Retry-After": String(Math.ceil(result.reset_ms / 1000)) },
    );
  }
  return null;
}

export async function handleRest(request: Request, env: Env, url: URL): Promise<Response> {
  if (request.method === "OPTIONS") return optionsResponse();

  const limited = await enforceRateLimit(request, env);
  if (limited) return limited;

  const path = url.pathname.replace(/\/+$/, "") || "/";

  if (path === "/api/v1/health" && request.method === "GET") {
    try {
      const { snapshot, source } = await loadSnapshot(env, request);
      const freshness = datasetFreshness(snapshot, { staleAfterHours: staleHours(env) });
      return json({
        status: freshness.fresh ? "ok" : "degraded",
        service: "githired-api",
        dataset: {
          status: freshness.fresh ? "fresh" : "stale",
          ...freshness,
          dataset_id: snapshot.dataset_id,
          count: snapshot.count,
          source,
        },
        environment: env.ENVIRONMENT || "unknown",
      });
    } catch (err) {
      return json(
        {
          status: "error",
          service: "githired-api",
          error: err instanceof Error ? err.message : String(err),
        },
        503,
      );
    }
  }

  const { snapshot, source } = await loadSnapshot(env, request);
  const freshness = datasetFreshness(snapshot, { staleAfterHours: staleHours(env) });

  if (path === "/api/v1/stats" && request.method === "GET") {
    return json({
      ...snapshot.stats,
      dataset_id: snapshot.dataset_id,
      generated_at: snapshot.generated_at,
      dataset_fresh: freshness.fresh,
      dataset_age_hours: freshness.age_hours,
      last_successful_discovery: snapshot.generated_at,
      last_successful_enrichment: snapshot.generated_at,
      source,
      scope_note:
        "Statistics describe GitHired's tracked employer ATS boards, not the entire Canadian labour market.",
      salary_policy: snapshot.salary_policy,
      eligibility: snapshot.eligibility,
    });
  }

  if (path === "/api/v1/companies" && request.method === "GET") {
    return json({
      count: snapshot.companies.length,
      companies: snapshot.companies,
      dataset_id: snapshot.dataset_id,
      generated_at: snapshot.generated_at,
    });
  }

  if (path === "/api/v1/jobs" && request.method === "GET") {
    const filters = parseSearchFilters(url.searchParams);
    const result = searchJobs(snapshot, filters);
    return json({
      ...result,
      dataset_fresh: freshness.fresh,
      salary_filter_note:
        "salary_min/salary_max filter advertised annual base pay only (CAD-normalized). Estimates are never used.",
      source,
    });
  }

  const jobMatch = path.match(/^\/api\/v1\/jobs\/([^/]+)$/);
  if (jobMatch && request.method === "GET") {
    const id = decodeURIComponent(jobMatch[1]);
    const job = getJobById(snapshot, id);
    if (!job) {
      return json({ error: "not_found", message: `No job with id ${id}` }, 404);
    }
    return json({
      job,
      dataset_id: snapshot.dataset_id,
      generated_at: snapshot.generated_at,
    });
  }

  if (path === "/api/v1/match" && request.method === "POST") {
    let body: MatchProfileInput = {};
    try {
      body = (await request.json()) as MatchProfileInput;
    } catch {
      return json({ error: "invalid_json", message: "Request body must be JSON" }, 400);
    }
    // Never persist profile payloads — compute and discard.
    const result = matchProfile(snapshot, body);
    return json({
      ...result,
      dataset_fresh: freshness.fresh,
    });
  }

  if (path === "/api/v1" || path === "/api" || path === "/") {
    return json({
      name: "GitHired API",
      version: "v1",
      website: "https://githired.ca",
      docs: "https://githired.ca/developers",
      agents: "https://githired.ca/agents",
      openapi: "https://githired.ca/openapi.json",
      mcp: "https://api.githired.ca/mcp",
      endpoints: [
        "GET /api/v1/health",
        "GET /api/v1/stats",
        "GET /api/v1/companies",
        "GET /api/v1/jobs",
        "GET /api/v1/jobs/{id}",
        "POST /api/v1/match",
        "POST /mcp",
      ],
      dataset_id: snapshot.dataset_id,
      generated_at: snapshot.generated_at,
      example: compactJob(snapshot.jobs[0] || ({} as never)),
    });
  }

  return json({ error: "not_found", message: `No route for ${path}` }, 404);
}
