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

Eligibility matches the public shortlist (hard-filter **ELIGIBLE** only). Salaries are advertised annual base only.

## Filters and normalization

- Province filter accepts Canadian two-letter codes (e.g. `ON`) and full names (e.g. `Ontario`), case-insensitively. Unrecognized values return a clear validation error instead of a silent empty set.
- Seniority filter accepts common aliases (`sr` / `s.r.` → `senior`, `jr` / `j.r.` → `junior`) and the values intern, junior, mid, senior, staff, principal, lead.
- Keyword search matches title, company, location, track, seniority and technologies — never the description excerpt alone. Company and skill queries (e.g. `Cohere`, `PySpark`) continue to work.
- MCP `search_jobs` supports pagination via a `cursor` argument and returns `next_cursor` plus `applied_filters` in the response.
