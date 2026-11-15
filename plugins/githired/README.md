# GitHired (Cursor plugin)

Connect Cursor to GitHired’s **remote** MCP server for Canada-eligible technology jobs.

- **Endpoint:** `https://api.githired.ca/mcp`
- **Auth:** none
- **Tools:** `search_jobs`, `get_job`, `match_profile`, `get_market_stats`
- **Docs:** https://githired.ca/agents
- **Repo:** https://github.com/mikegianfelice/GitHired

## Install

### One-click (already live)

Use the official Cursor deeplink on https://githired.ca/agents — no Marketplace listing required.

### Marketplace (after Cursor review)

If this plugin is listed on the Cursor Marketplace, install it from Cursor’s marketplace UI.

### Manual

Add to `~/.cursor/mcp.json` or project `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "githired": {
      "url": "https://api.githired.ca/mcp"
    }
  }
}
```

## Example prompts

- Find five remote Senior Data Engineer jobs available in Canada.
- Find Toronto software engineering roles advertising at least CAD $150,000.
- Match me to data engineering jobs: Python 5y, SQL 5y, Databricks 2y, ETL, cloud.
- Show Canadian tech job market stats from GitHired's tracked employers.

## Notes

- Read-only. No résumé upload. Employer-advertised salaries only.
- Publishing this plugin to the Cursor Marketplace requires owner submission at https://cursor.com/marketplace/publish and acceptance of Cursor’s publisher terms.
