import { datasetFreshness, loadSnapshot } from "./dataset";
import { matchProfile } from "./match";
import { checkRateLimit, clientIp } from "./rate-limit";
import { compactJob, getJobById, searchJobs, SearchFilterValidationError, parseSearchFilters } from "./search";
import type { Env, MatchProfileInput, SearchFilters } from "./types";
import { acceptedResponse, json, optionsResponse } from "./rest";

const PROTOCOL_VERSION = "2024-11-05";
const SERVER_INFO = { name: "githired", version: "1.0.2" };

/** Shared MCP tool hints required by directory reviewers (OpenAI ChatGPT/Codex). */
const READ_ONLY_OPEN_WORLD = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  // openWorldHint: results reflect live employer ATS data outside the model.
  openWorldHint: true,
} as const;

const TOOLS = [
  {
    name: "search_jobs",
    description:
      "Search Canada-eligible technology jobs (plus optional worldwide-remote roles labeled remote_scope=global) tracked by GitHired from employer ATS boards. Canada/province matches rank above global. Returns compact results with original apply URLs and remote_scope. Province accepts codes (ON) or full names (Ontario). Use exclude_global_remote=true or remote_scope to filter. Does not invent jobs or salaries.",
    annotations: READ_ONLY_OPEN_WORLD,
    inputSchema: {
      type: "object",
      properties: {
        keywords: { type: "string", description: "Keyword query (title, company, skills)" },
        location: { type: "string" },
        province: { type: "string", description: "Canadian province (code or full name, e.g. ON or Ontario)" },
        remote: { type: "boolean" },
        work_mode: { type: "string", enum: ["remote", "hybrid", "onsite"] },
        remote_scope: {
          type: "string",
          enum: ["canada", "province", "americas", "global", "local", "unspecified"],
          description:
            "Exact remote_scope match. global = explicit worldwide/anywhere remote (no invented Canadian province).",
        },
        exclude_global_remote: {
          type: "boolean",
          description: "When true, drop remote_scope=global jobs from results.",
        },
        salary_disclosed: { type: "boolean", description: "true: only jobs with advertised salary; false: only jobs without; omit for either" },
        minimum_salary: {
          type: "number",
          description: "Minimum advertised annual base in CAD (employer-advertised only)",
        },
        seniority: { type: "string" },
        company: { type: "string" },
        limit: { type: "number", minimum: 1, maximum: 25 },
        cursor: { type: "string", description: "Opaque cursor from previous page" },
      },
    },
  },
  {
    name: "list_companies",
    description:
      "List companies in the current dataset with their active job counts. Optional name filter performs a case-insensitive substring search.",
    annotations: READ_ONLY_OPEN_WORLD,
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Substring match on company name (case-insensitive)" },
        limit: { type: "number", minimum: 1, maximum: 500 },
      },
    },
  },
  {
    name: "get_job",
    description: "Retrieve detailed information for a GitHired job by stable id.",
    annotations: READ_ONLY_OPEN_WORLD,
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string", description: "GitHired job id" },
      },
      required: ["id"],
    },
  },
  {
    name: "match_profile",
    description:
      "Deterministically match skills/experience preferences to GitHired jobs. Uses role-family title matching (not exact titles). work_arrangements is a hard filter when set; remote_preference=true alone means remote-only. salary_mode defaults to flexible (advertised max may meet floor). Scores are relevance, not hire probability. Does not store résumés or call an LLM.",
    annotations: READ_ONLY_OPEN_WORLD,
    inputSchema: {
      type: "object",
      properties: {
        skills: { type: "array", items: { type: "string" } },
        years_experience: { type: "number" },
        preferred_roles: {
          type: "array",
          items: { type: "string" },
          description: "Preferred titles; matched by role family tokens (e.g. Senior Data Engineer also matches Data Platform Engineer).",
        },
        preferred_locations: { type: "array", items: { type: "string" } },
        remote_preference: {
          type: "boolean",
          description: "Legacy: true → remote-only hard filter when work_arrangements omitted.",
        },
        work_arrangements: {
          type: "array",
          items: { type: "string", enum: ["remote", "hybrid", "onsite"] },
          description: "Hard allow-list of work arrangements. Overrides remote_preference when provided.",
        },
        minimum_salary: { type: "number", description: "CAD-normalized annual base floor." },
        salary_mode: {
          type: "string",
          enum: ["strict", "flexible"],
          description: "strict: advertised min must meet floor. flexible (default): advertised max may meet floor.",
        },
        seniority: { type: "string" },
        limit: { type: "number" },
      },
    },
  },
  {
    name: "get_market_stats",
    description:
      "Aggregate statistics from GitHired's tracked Canadian tech employer dataset — not a full labour-market census. Includes by_remote_scope so worldwide-remote (global) jobs are counted under remote_scope=global, not as Canadian provinces.",
    annotations: READ_ONLY_OPEN_WORLD,
    inputSchema: {
      type: "object",
      properties: {
        role: { type: "string" },
        province: { type: "string" },
        seniority: { type: "string" },
        work_arrangement: { type: "string", enum: ["remote", "hybrid", "onsite"] },
        remote_scope: {
          type: "string",
          enum: ["canada", "province", "americas", "global", "local", "unspecified"],
          description: "Optional exact remote_scope filter before aggregating.",
        },
        exclude_global_remote: {
          type: "boolean",
          description: "When true, exclude remote_scope=global jobs from aggregates.",
        },
      },
    },
  },
] as const;

function rpcResult(id: unknown, result: unknown): object {
  return { jsonrpc: "2.0", id: id ?? null, result };
}

function rpcError(id: unknown, code: number, message: string, data?: unknown): object {
  return { jsonrpc: "2.0", id: id ?? null, error: { code, message, data } };
}

function textContent(payload: unknown): { content: Array<{ type: string; text: string }> } {
  return {
    content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
  };
}

async function callTool(name: string, args: Record<string, unknown>, env: Env, request: Request) {
  const { snapshot } = await loadSnapshot(env, request);
  const freshness = datasetFreshness(snapshot, {
    staleAfterHours: Number(env.STALE_AFTER_HOURS || 48) || 48,
  });

  if (name === "search_jobs") {
    try {
      // Normalize and validate exactly like REST by round-tripping through URLSearchParams.
      const params = new URLSearchParams();
      if (typeof args.keywords === "string" && args.keywords.trim()) params.set("q", args.keywords.trim());
      if (typeof args.location === "string" && args.location.trim()) params.set("location", args.location.trim());
      if (typeof args.province === "string" && args.province.trim()) params.set("province", args.province.trim());
      if (typeof args.remote === "boolean") params.set("remote", String(args.remote));
      if (typeof args.work_mode === "string" && args.work_mode.trim()) params.set("work_mode", args.work_mode.trim());
      if (typeof args.remote_scope === "string" && args.remote_scope.trim()) {
        params.set("remote_scope", args.remote_scope.trim());
      }
      if (typeof args.exclude_global_remote === "boolean") {
        params.set("exclude_global_remote", String(args.exclude_global_remote));
      }
      if (typeof args.salary_disclosed === "boolean") params.set("salary_disclosed", String(args.salary_disclosed));
      if (typeof args.minimum_salary === "number" && Number.isFinite(args.minimum_salary) && args.minimum_salary > 0) {
        params.set("salary_min", String(args.minimum_salary));
      }
      if (typeof args.seniority === "string" && args.seniority.trim()) params.set("seniority", args.seniority.trim());
      if (typeof args.company === "string" && args.company.trim()) params.set("company", args.company.trim());
      if (typeof args.limit === "number") params.set("limit", String(Math.min(25, Math.max(1, Math.floor(args.limit as number)))));
      if (typeof args.cursor === "string" && args.cursor.trim()) params.set("cursor", args.cursor.trim());
      const filters = parseSearchFilters(params);
      const result = searchJobs(snapshot, filters);
      return textContent({
        total: result.total,
        dataset_id: result.dataset_id,
        generated_at: result.generated_at,
        dataset_fresh: freshness.fresh,
        jobs: result.jobs.map(compactJob),
        applied_filters: result.applied_filters,
        next_cursor: result.next_cursor,
        salary_note: "Filters use employer-advertised annual base only.",
      });
    } catch (err) {
      if (err instanceof SearchFilterValidationError) {
        throw new Error(`${err.code}: ${err.message}`);
      }
      throw err;
    }
  }

  if (name === "get_job") {
    const id = String(args.id || "");
    if (!id) throw new Error("id is required");
    const job = getJobById(snapshot, id);
    if (!job) {
      return textContent({ error: "not_found", id });
    }
    return textContent({ job, dataset_id: snapshot.dataset_id, generated_at: snapshot.generated_at });
  }

  if (name === "list_companies") {
    const needle = typeof args.name === "string" ? args.name.trim().toLowerCase() : "";
    const limit =
      typeof args.limit === "number" && Number.isFinite(args.limit) ? Math.min(500, Math.max(1, Math.floor(args.limit))) : 250;
    let rows = snapshot.companies || [];
    if (needle) {
      rows = rows.filter((c) => c.name.toLowerCase().includes(needle));
    }
    const out = rows.slice(0, limit);
    return textContent({
      count: out.length,
      total: rows.length,
      companies: out,
      dataset_id: snapshot.dataset_id,
      generated_at: snapshot.generated_at,
    });
  }

  if (name === "match_profile") {
    const input = args as MatchProfileInput;
    const result = matchProfile(snapshot, input);
    return textContent({ ...result, dataset_fresh: freshness.fresh });
  }

  if (name === "get_market_stats") {
    let jobs = snapshot.jobs;
    const fx = Number(snapshot.usd_to_cad) || 1.35;
    const salaryCad = (j: { salary_max_cad?: number | null; salary_max?: number | null; salary_currency?: string | null }): number | null => {
      if (j.salary_max_cad != null) return j.salary_max_cad as number;
      if (j.salary_max == null || !j.salary_currency) return null;
      const cur = String(j.salary_currency).toUpperCase();
      if (cur === "CAD") return j.salary_max as number;
      if (cur === "USD") return (j.salary_max as number) * fx;
      return null;
    };
    if (typeof args.role === "string" && args.role.trim()) {
      const r = args.role.toLowerCase();
      jobs = jobs.filter(
        (j) =>
          j.title.toLowerCase().includes(r) ||
          (j.track || "").toLowerCase().includes(r.replace(/\s+/g, "_")),
      );
    }
    if (typeof args.province === "string" && args.province.trim()) {
      const p = args.province.toUpperCase();
      jobs = jobs.filter((j) => (j.province || "").toUpperCase() === p);
    }
    if (typeof args.seniority === "string" && args.seniority.trim()) {
      const s = args.seniority.toLowerCase();
      jobs = jobs.filter((j) => (j.seniority || "").toLowerCase() === s);
    }
    if (typeof args.work_arrangement === "string" && args.work_arrangement.trim()) {
      const w = args.work_arrangement.toLowerCase();
      jobs = jobs.filter((j) => j.work_arrangement === w);
    }
    if (typeof args.remote_scope === "string" && args.remote_scope.trim()) {
      const rs = args.remote_scope.toLowerCase();
      jobs = jobs.filter((j) => (j.remote_scope || "").toLowerCase() === rs);
    }
    if (args.exclude_global_remote === true) {
      jobs = jobs.filter((j) => (j.remote_scope || "").toLowerCase() !== "global");
    }
    // Always report remote_scope buckets so global is never mistaken for a province.
    const by_remote_scope: Record<string, number> = {};
    for (const j of jobs) {
      const key = (j.remote_scope || "unspecified").toLowerCase();
      by_remote_scope[key] = (by_remote_scope[key] || 0) + 1;
    }
    // Optional breakdowns to make agent reporting easier
    const groupBy = typeof (args as any).group_by === "string" ? String((args as any).group_by).toLowerCase() : "";
    let breakdown: Record<string, number> | undefined;
    if (groupBy === "province") {
      breakdown = {};
      for (const j of jobs) {
        // Worldwide-remote jobs have null province — count under remote_scope global, not as a province.
        if ((j.remote_scope || "").toLowerCase() === "global") {
          breakdown["global"] = (breakdown["global"] || 0) + 1;
          continue;
        }
        const key = (j.province || "UNKNOWN") as string;
        breakdown[key] = (breakdown[key] || 0) + 1;
      }
    } else if (groupBy === "city") {
      breakdown = {};
      for (const j of jobs) {
        const loc = String(j.location || "");
        const city = loc.split(",")[0].trim() || "UNKNOWN";
        breakdown[city] = (breakdown[city] || 0) + 1;
      }
    }
    const withSalary = jobs.filter((j) => j.salary_available);
    const cadMaxes = withSalary
      .map((j) => salaryCad(j as any))
      .filter((v): v is number => typeof v === "number" && Number.isFinite(v))
      .sort((a, b) => a - b);
    const pct = (p: number) => {
      if (!cadMaxes.length) return null;
      const idx = Math.min(cadMaxes.length - 1, Math.max(0, Math.floor((p / 100) * (cadMaxes.length - 1))));
      return Math.round(cadMaxes[idx]);
    };
    const companies = new Set(jobs.map((j) => j.company));
    return textContent({
      scope_note:
        "These figures describe GitHired's tracked employer ATS boards, not the entire Canadian labour market. " +
        "remote_scope=global means explicit worldwide/anywhere remote — not a Canadian province.",
      filtered_jobs: jobs.length,
      companies: companies.size,
      remote_jobs: jobs.filter((j) => j.work_arrangement === "remote").length,
      hybrid_jobs: jobs.filter((j) => j.work_arrangement === "hybrid").length,
      onsite_jobs: jobs.filter((j) => j.work_arrangement === "onsite").length,
      jobs_with_advertised_salary: withSalary.length,
      by_remote_scope,
      breakdown,
      salary_cad_percentiles: {
        p25: pct(25),
        p50: pct(50),
        p75: pct(75),
      },
      dataset_id: snapshot.dataset_id,
      generated_at: snapshot.generated_at,
      dataset_fresh: freshness.fresh,
      global_stats: snapshot.stats,
    });
  }

  throw new Error(`Unknown tool: ${name}`);
}

export async function handleMcp(request: Request, env: Env): Promise<Response> {
  if (request.method === "OPTIONS") return optionsResponse();

  if (request.method === "GET") {
    // Streamable HTTP: GET may be used for SSE streams; we advertise JSON-only tools.
    return json({
      name: SERVER_INFO.name,
      version: SERVER_INFO.version,
      transport: "streamable-http",
      protocolVersion: PROTOCOL_VERSION,
      endpoint: "/mcp",
      tools: TOOLS.map((t) => t.name),
      docs: "https://githired.ca/agents",
    });
  }

  if (request.method !== "POST") {
    return json({ error: "method_not_allowed" }, 405);
  }

  const ip = clientIp(request);
  const rl = checkRateLimit(`mcp:${ip}`, {
    limitPerMinute: Number(env.RATE_LIMIT_PER_MINUTE || 120) || 120,
  });
  if (!rl.allowed) {
    return json(
      rpcError(null, -32000, "Rate limited"),
      429,
      { "Retry-After": String(Math.ceil(rl.reset_ms / 1000)) },
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json(rpcError(null, -32700, "Parse error"), 400);
  }

  const messages = Array.isArray(body) ? body : [body];
  if (messages.length > 10) {
    return json(rpcError(null, -32600, "Batch too large (max 10)"), 400);
  }

  const responses: object[] = [];
  for (const msg of messages) {
    if (!msg || typeof msg !== "object") {
      responses.push(rpcError(null, -32600, "Invalid Request"));
      continue;
    }
    const m = msg as { jsonrpc?: string; id?: unknown; method?: string; params?: Record<string, unknown> };
    if (m.jsonrpc !== "2.0" || typeof m.method !== "string") {
      responses.push(rpcError(m.id, -32600, "Invalid Request"));
      continue;
    }

    // Notifications (no id) — acknowledge without body items when appropriate.
    const isNotification = !("id" in m);

    try {
      if (m.method === "initialize") {
        responses.push(
          rpcResult(m.id, {
            protocolVersion: PROTOCOL_VERSION,
            capabilities: { tools: {} },
            serverInfo: SERVER_INFO,
            instructions:
              "GitHired exposes Canada-eligible tech jobs from employer ATS boards. " +
              "Use search_jobs / get_job / match_profile / get_market_stats. " +
              "Never invent salaries or Canadian eligibility.",
          }),
        );
      } else if (m.method === "notifications/initialized" || m.method === "initialized") {
        if (!isNotification) responses.push(rpcResult(m.id, {}));
      } else if (m.method === "ping") {
        responses.push(rpcResult(m.id, {}));
      } else if (m.method === "tools/list") {
        responses.push(rpcResult(m.id, { tools: TOOLS }));
      } else if (m.method === "tools/call") {
        const params = m.params || {};
        const name = String(params.name || "");
        const args = (params.arguments || {}) as Record<string, unknown>;
        if (!name) {
          responses.push(rpcError(m.id, -32602, "Tool name required"));
          continue;
        }
        const result = await callTool(name, args, env, request);
        responses.push(rpcResult(m.id, result));
      } else if (m.method === "resources/list") {
        responses.push(rpcResult(m.id, { resources: [] }));
      } else if (m.method === "prompts/list") {
        responses.push(rpcResult(m.id, { prompts: [] }));
      } else {
        if (!isNotification) responses.push(rpcError(m.id, -32601, `Method not found: ${m.method}`));
      }
    } catch (err) {
      responses.push(
        rpcError(m.id, -32000, err instanceof Error ? err.message : String(err)),
      );
    }
  }

  if (Array.isArray(body)) {
    // Batch of notifications only → 202 with no body.
    if (responses.length === 0) return acceptedResponse();
    return json(responses);
  }
  // Single notification (no id / no result) must not become Internal error.
  if (responses.length === 0) return acceptedResponse();
  return json(responses[0]);
}
