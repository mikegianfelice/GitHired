# Canada-remote job discovery (`githired` / `jobseek`)

Production-oriented discovery and ranking for engineering roles that accept candidates working remotely from Canada (or hybrid/on-site in configured Canadian cities/provinces).

## Architecture

1. **Company registry** — `config/companies.yaml` seeded into SQLite `companies` (Greenhouse / Lever / Ashby board tokens)
2. **Discover** — public ATS APIs + free LinkedIn search-index attempt / SerpAPI / alert import
3. **SQLite** — `data/jobseek.db` stores raw responses, normalized jobs (`first_seen` / `last_seen` / `removed_at`), scores, applications, companies, runs
4. **Hard filters** — engineering tracks, Canada eligibility modes, salary floors (no LLM)
5. **Stage-1 rank** — transparent deterministic scores (default; no API key)
6. **Stage-2 rank** — optional LLM evidence scores (`--llm` or `GITHIRED_RANK_LLM=1`)
7. **Digest** — top 10 high-score jobs; SMTP or Resend email

Resume drafting and application submission stay behind explicit approval (`githired prepare` → `/apply`).

## CLI

```bash
pip install -e .
githired setup --non-interactive   # or interactive: githired setup
githired doctor
githired discover
githired rank --limit 25           # deterministic
githired rank --limit 25 --llm     # optional AI stage
githired jobs --min-score 60
githired digest --save
githired sources
githired email-digest
githired run-daily
githired prepare 42
githired import-alerts path/to/alert.html
githired migrate                   # seen_jobs.json + tracker.csv → SQLite
```

`jobseek` remains a backward-compatible alias for the same commands.

## Engineering tracks

Configure `tracks` in `config/search.yaml` instead of dozens of titles. Aliases and seniority live under `track_aliases` / `seniority`. Use `custom_title_overrides` for one-off phrases.

## LinkedIn compliance

Scheduled discovery **does not** call LinkedIn `jobs-guest` endpoints (ToS risk). Prefer:

1. Free search-engine indexing when accessible (optional `duckduckgo-search` via `pip install 'githired[linkedin-free]'`)
2. Search-engine indexing via `SERPAPI_KEY` + queries in `config/search.yaml`
3. `githired import-alerts` for saved job alert HTML/JSON exports

Missing SerpAPI is a **warning**, not a discover failure. `githired sources` shows which LinkedIn modes are active.

## Canada eligibility

Hard filters never invent Canadian hiring eligibility. Supported modes: `remote_canada`, `remote_province`, `hybrid`, `onsite`. Ambiguous geography is `unknown` / FLAG. US-only remote is rejected when configured.

## Scoring honesty

- Deterministic scores are labeled `score_kind=deterministic` / `model=deterministic` — not AI.
- LLM scores are labeled `score_kind=llm` with the provider model name.
- Digests and `githired jobs` surface the score kind.

## Scheduling

See `SETUP.md` for cron/launchd examples. Failures during `run-daily --email` attempt a failure-alert email when a provider is configured.
