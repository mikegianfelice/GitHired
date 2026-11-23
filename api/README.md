# GitHired API Worker

Cloudflare Worker serving:

- REST: `/api/v1/*`
- MCP: `/mcp` (Streamable HTTP JSON-RPC)

## Local development

```bash
# From repo root — refresh the bundled dataset
python3 scripts/export_api_snapshot.py

cd api
npm install
npm test
npx tsc --noEmit
npx wrangler dev
```

Then:

```bash
curl -s 'http://127.0.0.1:8787/api/v1/health' | jq .
curl -s 'http://127.0.0.1:8787/api/v1/jobs?q=data%20engineer&remote=true&salary_min=150000&limit=5' | jq .
```

## Deploy

Requires GitHub Actions secrets / local Wrangler auth:

- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

```bash
npx wrangler deploy
```

After `workers.dev` verification, attach custom domain `api.githired.ca` in Cloudflare.
Do **not** change root `githired.ca` GitHub Pages DNS.

## Dataset updates

`scripts/export_api_snapshot.py` writes `api/data/jobs.snapshot.json`.
The scheduled **API dataset sync** workflow (`api-dataset.yml`) discovers, exports,
commits the snapshot, and **deploys the Worker** so production does not stay on a
stale bundled dataset. (`GITHUB_TOKEN` commits do not trigger `api-worker.yml`.)

Optional R2 binding `DATA` with object `snapshots/current.json` enables data-only
swaps without redeploying Worker code.

## Salary policy

Filters use **employer-advertised annual base** only. Estimates are never produced or filtered as if real.

## Filters and pagination (2026-11-23)

- Province accepts two-letter codes (e.g. `ON`) or full names (e.g. `Ontario`), case-insensitive. Invalid values return a validation error (`invalid_province`).
- Seniority accepts common aliases (`sr`/`jr`) and validates against known bands.
- Keyword search precision: description text no longer qualifies results; it contributes a weak rank boost only. Company/skill searches unaffected.
- MCP `search_jobs` supports `cursor` and returns `next_cursor`, `total`, and `applied_filters` for deterministic agent pagination.
