import type { ApiSnapshot, Env } from "./types";

let cached: { snapshot: ApiSnapshot; loadedAt: number; source: string } | null = null;

/** Bundled fallback — replaced by export_api_snapshot.py before deploy. */
import bundled from "../data/jobs.snapshot.json";

function isSnapshot(value: unknown): value is ApiSnapshot {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return Array.isArray(v.jobs) && typeof v.generated_at === "string";
}

export async function loadSnapshot(env: Env, request?: Request): Promise<{
  snapshot: ApiSnapshot;
  source: string;
  cache_hit: boolean;
}> {
  if (cached) {
    return { snapshot: cached.snapshot, source: cached.source, cache_hit: true };
  }

  // Prefer R2 current pointer when bound (data updates without Worker redeploy).
  if (env.DATA) {
    try {
      const obj = await env.DATA.get("snapshots/current.json");
      if (obj) {
        const parsed = await obj.json();
        if (isSnapshot(parsed)) {
          cached = { snapshot: parsed, loadedAt: Date.now(), source: "r2:snapshots/current.json" };
          return { snapshot: parsed, source: cached.source, cache_hit: false };
        }
      }
    } catch {
      // fall through
    }
  }

  if (isSnapshot(bundled)) {
    cached = { snapshot: bundled as ApiSnapshot, loadedAt: Date.now(), source: "bundled" };
    return { snapshot: cached.snapshot, source: cached.source, cache_hit: false };
  }

  throw new Error("No valid GitHired dataset snapshot available");
}

export function clearDatasetCache(): void {
  cached = null;
}

export function datasetFreshness(
  snapshot: ApiSnapshot,
  opts: { staleAfterHours: number },
): { fresh: boolean; age_hours: number; generated_at: string; stale_after_hours: number } {
  const staleAfterHours = opts.staleAfterHours;
  const generated = Date.parse(snapshot.generated_at);
  const ageMs = Number.isFinite(generated) ? Date.now() - generated : Number.POSITIVE_INFINITY;
  const ageHours = ageMs / 3_600_000;
  return {
    fresh: ageHours <= staleAfterHours,
    age_hours: Math.round(ageHours * 10) / 10,
    generated_at: snapshot.generated_at,
    stale_after_hours: staleAfterHours,
  };
}
