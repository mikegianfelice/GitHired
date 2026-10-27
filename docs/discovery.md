# Canada-remote job discovery (`jobseek`)

Production-oriented discovery and ranking for engineering roles that accept candidates working remotely from Canada.

## Architecture

1. **Company registry** — `config/companies.yaml` (Greenhouse / Lever / Ashby board tokens)
2. **Discover** — public ATS APIs + optional SerpAPI LinkedIn index + alert import
3. **SQLite** — `data/jobseek.db` stores raw responses, normalized jobs (`first_seen` / `last_seen` / `removed_at`), scores, applications, runs
4. **Hard filters** — title, Canada-remote evidence, salary floors (no LLM)
5. **LLM rank** — 0–100 evidence scores (Anthropic primary, OpenAI-compatible alternate)
6. **Digest** — top 10 new high-score jobs; SMTP or Resend email

Resume drafting and application submission stay behind explicit approval (`jobseek prepare` → `/apply`).

## CLI

```bash
pip install -e .
jobseek discover --import-tracker
jobseek rank --limit 25
jobseek digest --save
jobseek email-digest
jobseek run-daily --email
jobseek prepare 42
jobseek import-alerts path/to/alert.html
jobseek import-seen   # migrate job_scraper/seen_jobs.json
```

## LinkedIn compliance

Scheduled discovery **does not** call LinkedIn `jobs-guest` endpoints (ToS risk). Prefer:

- Search-engine indexing via `SERPAPI_KEY` + queries in `config/search.yaml`
- `jobseek import-alerts` for saved job alert HTML/JSON exports
- Interactive low-volume `linkedin-search` CLI only when `sources.linkedin_guest: true`

## Canada eligibility

Hard filters never invent Canadian hiring eligibility. US remote roles require explicit evidence phrases (Canada, Canadian, worldwide, work from anywhere, etc.) or they FAIL / FLAG per `config/search.yaml`.

## Scheduling

See `SETUP.md` for cron/launchd examples. Failures during `run-daily --email` attempt a failure-alert email when a provider is configured.
