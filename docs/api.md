# GitHired public API & MCP

Architecture: GitHub Actions discovery/enrichment → ranked SQLite → versioned API snapshot → Cloudflare Worker (`githired-api`) → REST + MCP.

- Website remains on GitHub Pages at https://githired.ca
- API target: https://api.githired.ca
- MCP target: https://api.githired.ca/mcp

See `api/README.md` for Worker development and `site/developers/` / `site/agents/` for human docs.

## Snapshot

```bash
python3 scripts/export_api_snapshot.py --out api/data/jobs.snapshot.json
```

Eligibility matches the public shortlist: hard-filter **ELIGIBLE**, plus optional worldwide-remote roles when `include_global_remote` is enabled (default **true**). Those roles are labeled `remote_scope=global` with a null province. Salaries are advertised annual base only.

## Filters and normalization

- Province filter accepts Canadian two-letter codes (e.g. `ON`) and full names (e.g. `Ontario`), case-insensitively. Unrecognized values return a clear validation error instead of a silent empty set.
- Seniority filter accepts common aliases (`sr` / `s.r.` → `senior`, `jr` / `j.r.` → `junior`) and the values intern, junior, mid, senior, staff, principal, lead.
- Keyword search matches title, company, location, track, seniority and technologies — never the description excerpt alone. Company and skill queries (e.g. `Cohere`, `PySpark`) continue to work.
- MCP `search_jobs` supports pagination via a `cursor` argument and returns `next_cursor` plus `applied_filters` in the response.
- `remote_scope` (REST query + MCP): exact match on `canada` | `province` | `americas` | `global` | `local` | `unspecified`. Results always include `remote_scope`.
- `exclude_global_remote=true` (REST query + MCP): drops `remote_scope=global` jobs. Use this when callers want Canada-specific listings only.
- Ranking: `search_jobs` and `match_profile` always sort Canada / province scopes above `remote_scope=global` (worldwide-remote).
- `get_market_stats` returns `by_remote_scope` so global jobs are counted under `global`, not as Canadian provinces. Optional `remote_scope` / `exclude_global_remote` filters apply before aggregation.
