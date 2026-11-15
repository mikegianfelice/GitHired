# GitHired MCP tools (for reviewers)

Remote endpoint: `https://api.githired.ca/mcp` (HTTPS, no authentication).

| Tool | Purpose |
| --- | --- |
| `search_jobs` | Search current Canada-eligible technology jobs from tracked employer ATS boards. Filters: keywords, location, province, remote, work_mode, minimum_salary (advertised CAD annual base), seniority, company, limit ≤25. Returns compact results with original apply URLs. Does not invent jobs or salaries. |
| `get_job` | Retrieve detailed information for a GitHired job by stable `id`. |
| `match_profile` | Deterministically match skills/experience preferences to jobs using role-family title matching. Optional work_arrangements hard filter; salary_mode defaults to flexible. Does not store résumés or call an LLM. Scores are relevance, not hire probability. |
| `get_market_stats` | Aggregate statistics from GitHired’s tracked Canadian tech employer dataset — not a full labour-market census. |

All tools declare `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=true` (live ATS-derived data).
