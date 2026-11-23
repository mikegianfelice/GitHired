GitHired scaling and policy toggles

This document captures code-only levers and deferred decisions for Michael. No deployment config or secrets changes are applied here.

Decisions for Michael

- include_global_remote (default: false)
  - When true, publish worldwide-remote jobs that have no explicit Canada evidence, labeled remote_scope='global' and ranked below province matches and remote_scope='canada'.
  - Current impact if enabled: +33 jobs (Supabase 21, Camunda 8, ElevenLabs 4). With it off (default), these remain excluded.
- Americas/NAMER remote at Canadian-HQ companies
  - Shopify and some others advertise “Americas/NAMER (Remote)”. Policy remains strict for now: eligibility unchanged (not Canada-eligible). We tag remote_scope='americas' for analysis. Count of jobs affected is tracked in the funnel reports; enablement would be a separate toggle if adopted.

Snapshot size and field slimming

- Current bundle cap: ~950 KB. Measured effective size per job after slimming: ~0.43–0.73 KB, so roughly 1,300–2,200 jobs fit without moving descriptions to object storage.
- Space contributors:
  - description_excerpt dominated prior size; it is excluded from the public mirror and trimmed in the Worker snapshot.
  - Remaining dominant fields: company, title, location/province/remote_scope, seniority/track, salary_max_cad, apply_url, technologies.
- Code-only savings already landed:
  - Strip description excerpts from the public mirror (site/api-dataset.json) and prefer short codes for provinces in export.
  - Deduplicate company+title pairs in the final shortlist.
- If more headroom is needed pre-R2:
  - Consider trimming optional fields in the Worker bundle (e.g., drop technologies or salary_max_cad when salary_available is false). This is a code-path change only; keep the public mirror stable.

R2 plan (deferred)

If supply grows beyond ~2,000 publishable jobs, move full descriptions to R2 and fetch them on-demand in get_job. Steps:

1) Create an R2 bucket jobs-descriptions with 7-day TTL for hot objects.
2) In the enrichment pipeline, persist description blobs under a stable key (e.g., sha256 of company|title|apply_url).
3) Store only the key in the Worker bundle; fetch and cache on API get_job when needed.
4) Add backoff + integrity checks; keep fallbacks to ATS detail endpoints when a blob is missing.

Do not apply this plan yet — it requires infra/secrets. This file is a design note for later.

# API dataset scaling plan (to 5,000+ jobs)

This doc outlines a safe path to scale the API/MCP dataset beyond Cloudflare Worker bundle limits without changing secrets at code-review time. Apply these steps in infra as needed.

## Current state

- Worker imports a bundled `api/data/jobs.snapshot.json`.
- Optional R2 binding `DATA` is already supported in code (`api/src/dataset.ts`). When present, the Worker loads `snapshots/current.json` from R2 at runtime (no redeploy needed for data-only updates).
- Budgeting: the snapshot builder trims using a compact-JSON byte budget (default `MAX_SNAPSHOT_BYTES=950_000`).
- As of 2026‑11‑23, 447 jobs compact to ~744 KB with description excerpts; pretty JSON on disk is ~868 KB. Excerpts dominate size.

## Code-only improvements (already implemented)

1. Budget-aware slimming before trimming jobs:
   - Prefer removing `description_excerpt` from all rows.
   - Then zero out `technologies`.
   - Only then drop lowest-ranked jobs until within budget.
2. Province derivation and title-suffix matching fixes reduce false negatives and improve data quality.

These keep bundle size roughly ~0.73 KB/job after removing excerpts, but 5,000 jobs would still exceed 950 KB.

## Recommended infra path to 5,000+ jobs

Use R2 for dataset delivery; the Worker already supports it.

1) Enable R2 binding in `wrangler.toml` (production Worker)
   [[r2_buckets]]
   binding = "DATA"
   bucket_name = "githired-api-data"

2) Create the R2 bucket (one-time)
   - In Cloudflare dashboard → R2 → Create bucket `githired-api-data`

3) Grant the GitHub Actions environment (api) R2 write permissions
   - Add `CLOUDFLARE_API_TOKEN` with R2 write scope and `CLOUDFLARE_ACCOUNT_ID`

4) Update the dataset sync workflow to upload the snapshot to R2
   - After “Export API snapshot”, add:
     - `npx wrangler r2 object put githired-api-data/snapshots/current.json --file=api/data/jobs.snapshot.json`

5) Deploy the Worker with the R2 binding enabled
   - `npx wrangler deploy --var ENVIRONMENT:production`
   - The Worker will now prefer `DATA.get("snapshots/current.json")` with auto-refresh on next request; the bundled file remains a safe fallback.

6) (Optional) Keep the pretty-printed snapshot in the repo for auditing; the Worker uses the compact budget during trimming, not the pretty size.

## Rollback and safety
- If R2 is unavailable, the Worker falls back to the bundled snapshot.
- The dataset sync job refuses to publish empty or stale snapshots.

## Alternatives considered
- Splitting the dataset across multiple static assets and fetching segments on demand: higher complexity and cache consistency issues compared to R2 pointer.
- Removing key fields (province, salary flags) to shrink per-row size: harms filtering and UX; not recommended for public APIs.

## Decisions for Michael

- Policy: whether “Americas/NAMER (Remote)” at a Canadian‑HQ employer should be treated as Canada‑eligible. Current policy requires explicit Canada evidence; these rows are excluded.
- Impact estimate (current DB snapshot):
  - Considered (Shopify + any posting with Americas/NAMER remote): 170
  - Would publish if treated as Canada‑eligible: 32
- If you choose to allow this, we will:
  - Keep remote_scope tagged as 'americas'.
  - Mark eligibility ELIGIBLE for Americas/NAMER remote only when the employer is verifiably Canadian‑HQ (registry), and all other gates (engineering track, apply URL, freshness) pass.
  - Add tests for NAMER/Americas remote eligibility and keep strict “no province inference”.

