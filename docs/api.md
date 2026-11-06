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
