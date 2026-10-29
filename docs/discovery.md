# Canada-remote job discovery (`githired` / `jobseek`)

Production-oriented discovery and ranking for engineering roles that accept candidates working remotely from Canada (or hybrid/on-site in configured Canadian cities/provinces).

## Architecture

1. **Three-layer company registry** — builtin [`config/companies.yaml`](../config/companies.yaml) → community [`registry/community/`](../registry/community/) → SQLite discoveries → user [`config/companies.local.yaml`](../config/companies.local.yaml.example) (overrides win; auto-discovery never writes overrides)
2. **Company discovery** — `githired companies discover` validates public ATS boards (Greenhouse, Lever, Ashby, Workable, RSS/XML, Rippling, Workday guest CXS; Gem adapter present but opt-in)
3. **Job discover** — `githired discover` fetches enabled boards (Workday included when `sources.workday: true`, the default) + LinkedIn search-index / SerpAPI / alert import + optional Freehire (`sources.freehire`, default **off**)
4. **SQLite** — `data/jobseek.db` stores raw responses, normalized jobs (`first_seen` / `last_seen` / `removed_at`), scores, applications, companies, runs
5. **Hard filters** — engineering tracks, Canada eligibility modes, salary floors (no LLM)
6. **Stage-1 rank** — transparent deterministic scores (default; no API key)
7. **Stage-2 rank** — optional LLM evidence scores (`--llm` or `GITHIRED_RANK_LLM=1`)
8. **Digest** — top 10 high-score jobs; SMTP or Resend email
9. **README showcase** — optional public Top Paying Jobs block refreshed from SQLite salaries only ([`docs/showcase/ARCHITECTURE.md`](showcase/ARCHITECTURE.md); `githired showcase-readme`)

Resume drafting and application submission stay behind explicit approval (`githired prepare` → `/apply`).

**Fresh install:** you do **not** need to hand-maintain a company list. Builtin boards + `companies discover` expand the registry automatically. Core path needs no paid APIs or LLM keys.

## CLI

```bash
pip install -e .
githired setup --non-interactive   # or interactive: githired setup
githired doctor
githired companies discover        # expand/validate company boards (optional daily)
githired companies validate
githired companies list
githired companies stats
githired companies export --validated --out /tmp/companies.v1.yaml
githired companies import registry/community/companies.v1.yaml
githired discover                  # fetch jobs from enabled boards
githired rank --limit 25           # deterministic
githired rank --limit 25 --llm     # optional AI stage
githired jobs --min-score 60
githired digest --save
githired sources
githired email-digest
githired run-daily                 # jobs only
githired run-daily --companies     # company discover then jobs
githired showcase-readme           # refresh README Top Paying section from DB
githired showcase-readme --from-snapshot
githired prepare 42
githired import-alerts path/to/alert.html
githired migrate                   # seen_jobs.json + tracker.csv → SQLite
```

`jobseek` remains a backward-compatible alias for the same commands.

## Company registry layers

| Layer | Location | Written by |
|-------|----------|------------|
| Builtin | `config/companies.yaml` | Maintainers / you (version-controlled) |
| Community | `registry/community/companies.v1.yaml` | PRs only — never auto-published |
| Local discoveries | SQLite `companies` | `companies discover` / validate |
| User overrides | `config/companies.local.yaml` | You only (gitignored) |

Dedup uses verified `(ats, board_token)` first, else canonical domain, else normalized name. Board tokens are **never invented** — they must come from real careers/ATS URLs.

Validation outcomes: `ok` | `empty` | `invalid` | `unsupported` | `transient` | `excluded`. HTTP 200 alone is not sufficient. Empty boards are not marked invalid. Invalid/unsupported boards are not re-probed until `--force` (transient boards cool down ~7 days).

## Engineering tracks

Configure `tracks` in `config/search.yaml` instead of dozens of titles. Aliases and seniority live under `track_aliases` / `seniority`. Use `custom_title_overrides` for one-off phrases.

## LinkedIn compliance

Scheduled discovery **does not** call LinkedIn `jobs-guest` endpoints (ToS risk). Prefer:

1. Free search-engine indexing when accessible (optional `duckduckgo-search` via `pip install 'githired[linkedin-free]'`)
2. Search-engine indexing via `SERPAPI_KEY` + queries in `config/search.yaml`
3. `githired import-alerts` for saved job alert HTML/JSON exports

Missing SerpAPI is a **warning**, not a discover failure. `githired sources` shows which LinkedIn modes are active. Company search-index discovery degrades the same way.

## Workday

Verified Canadian employers with public Workday guest CXS boards are fetched automatically when `sources.workday` is enabled (default). Discovery paginates list endpoints and hydrates job details with bounded concurrency and connection reuse. No paid API is required.

## Optional Freehire aggregator

[`sources.freehire`](../config/search.yaml) defaults to **false**. When enabled:

- Uses the public Freehire JSON API (`FREEHIRE_API_URL` override supported); **no API key** and **no Bun** dependency for `githired discover`
- Normalizes hits into the same job model and Canada eligibility rules as other sources
- Deduplicates against existing ATS/Workday URLs where identity matches
- **Direct employer ATS apply URLs** (Greenhouse, Lever, Ashby, Workday, …) may enter the confirmed shortlist when geography passes
- **Affiliate-only** links (e.g. WhatJobs) are stored as `freehire_review` and excluded from confirmed (`ELIGIBLE`) recommendations — we do not invent employer URLs or follow untrusted redirect chains
- Provider failures are warnings; they do not fail the whole discover run

Freehire is best-effort hosted software. Do not advertise it as a reliable primary source unless your own benchmark supports that claim. Core discovery does **not** require Freehire or any paid API.

## Canada eligibility

Three-state classification (never invent eligibility from employer brand alone):

| State | Meaning | Effect |
|-------|---------|--------|
| **ELIGIBLE** | Explicit Canada / province / city, or genuine worldwide remote | Priority in ranking |
| **UNCERTAIN** | Ambiguous remote / US-primary without Canada evidence | Visible; ranking penalty + warning |
| **INELIGIBLE** | US-only, foreign work-auth, or on-site outside Canada | Hard-filter FAIL |

Supported modes: `remote_canada`, `remote_province`, `hybrid`, `onsite`.

## Seniority

Default config includes mid+ (`mid`, `senior`, `staff`, `principal`, `lead`) and excludes intern / co-op / student / new-grad / junior. Titles with no seniority keywords are **unknown** and are not rejected solely for that.

## Scoring honesty

- Deterministic scores are labeled `score_kind=deterministic` / `model=deterministic` — not AI.
- LLM scores are labeled `score_kind=llm` with the provider model name.
- Digests and `githired jobs` surface the score kind.

## Community contributions

See [`registry/community/README.md`](../registry/community/README.md). Export validated local rows, open a PR — never upload profiles, application history, API keys, or SQLite dumps.

## Scheduling

See `SETUP.md` for cron/launchd examples. Use `run-daily --companies` on a slower cadence if you want automatic board expansion. Failures during `run-daily --email` attempt a failure-alert email when a provider is configured.
