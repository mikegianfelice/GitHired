# Canada-remote job discovery (`githired` / `jobseek`)

Production-oriented discovery and ranking for engineering roles that accept candidates working remotely from Canada (or hybrid/on-site in configured Canadian cities/provinces).

## Architecture

Progressive local-first pipeline (discover ≠ enrich ≠ rank):

| Stage | Command | What you get |
|-------|---------|----------------|
| **Discovered** | `githired discover` | Titles, companies, URLs, list locations — **no** Workday detail HTTP |
| **Enriched** | `githired enrich` | Full descriptions + resolved geo; **priority + employer fairness** (one bank cannot monopolize a batch) |
| **Provisionally ranked** | `githired rank --provisional` | Fit signal from listing metadata only — **never** confirmed Canada ELIGIBLE |
| **Confirmed eligible** | `githired rank` then `jobs` | Complete description + hard filters; default shortlist |

Orchestration: `githired refresh` (progressive enrich/rank loops; reports **TTF10**) or `githired run-daily` (same + digest).

### Relevance vs geographic eligibility

These are separate axes — do not confuse them:

| Axis | Values | Meaning |
|------|--------|---------|
| **Relevance** | `MATCH` / `NO_MATCH` / `REVIEW` | Title/track fit for your configured engineering tracks |
| **Geographic eligibility** | `ELIGIBLE` / `UNCERTAIN` / `INELIGIBLE` | Canada / remote / hybrid evidence |
| **Off-track** | eligibility=`IRRELEVANT` | Title failed track match — **not** “uncertain Canada” |
| **Enrichment** | `pending` → `processing` → `complete` \| `failed` \| `stale` | Detail hydration queue |

**Confirmed match** = complete description + hard-filter `verdict=PASS` + geographic `ELIGIBLE`. Canada-eligible roles that fail salary / seniority / apply-URL gates are **not** confirmed. Missing salary is not auto-rejected.

`githired jobs` (default) shows confirmed matches only. Enrichment modes: **quick** (track-relevant only), **standard** (high-priority), **deep** (allows low-priority backlog).

1. **Three-layer company registry** — builtin [`config/companies.yaml`](../config/companies.yaml) → community [`registry/community/`](../registry/community/) → SQLite discoveries → user [`config/companies.local.yaml`](../config/companies.local.yaml.example) (overrides win; auto-discovery never writes overrides)
2. **Company discovery** — `githired companies discover` validates public ATS boards (Greenhouse, Lever, Ashby, Workable, RSS/XML, Rippling, Workday guest CXS; Gem adapter present but opt-in)
3. **Job discover (list-only)** — `githired discover` fetches enabled boards + LinkedIn search-index / SerpAPI / alert import + optional Freehire. Workday listings persist immediately with `enrichment_status=pending` (or `complete` when a TTL-fresh SQLite description is reused).
4. **Enrich** — scores the **full** pending queue from listing metadata (track, location hints, seniority, salary, freshness), fair-schedules across employers, claims with owner+lease token, retries with exponential backoff, preserves prior complete bodies on failure
5. **SQLite** — `data/jobseek.db` stores jobs (`enrichment_status`, leases, priorities), scores (`deterministic` vs `provisional`), applications, companies, runs
6. **Hard filters** — engineering tracks (relevance), Canada eligibility, salary floors (no LLM)
7. **Stage-1 rank** — confirmed deterministic scores on **complete** descriptions (default)
8. **Stage-2 rank** — optional LLM evidence scores (`--llm` or `GITHIRED_RANK_LLM=1`)
9. **Digest** — top 10 **confirmed** high-score jobs only; SMTP or Resend email
10. **README showcase** — optional public Top Paying Jobs block ([`docs/showcase/ARCHITECTURE.md`](showcase/ARCHITECTURE.md); `githired showcase-readme`)
11. **TTF10** — `githired refresh` reports time to first 10 relevant confirmed matches (never pads with uncertain/off-track)

Resume drafting and application submission stay behind explicit approval (`githired prepare` → `/apply`).

**Fresh install:** you do **not** need to hand-maintain a company list. Builtin boards + `companies discover` expand the registry automatically. Core path needs no paid APIs or LLM keys.

### Enrichment status values

`pending` → `processing` (leased with worker id + token) → `complete` | `failed` | `stale` (TTL expired; re-queued by enrich). Completion requires matching lease ownership so an expired worker cannot overwrite a newer claim. Failed jobs get `enrich_next_retry_at` (exponential backoff). Incomplete jobs are never shown as confirmed matches.

**Provisional vs confirmed scores:** provisional ranks use list-only metadata and never enter the default shortlist. Confirmed scores require a complete description and pass geographic + track hard filters.

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
githired discover                  # list-only (fast); Workday details via enrich
githired discover --mode quick     # shorter list budgets
githired enrich                    # hydrate queued Workday descriptions (resumable)
githired enrich --mode deep        # refresh stale / larger batch
githired refresh                   # discover → enrich → rank
githired rank                      # confirmed scores (complete descriptions only)
githired rank --provisional        # list-only scores (never confirmed ELIGIBLE)
githired rank --limit 25           # cap batch size
githired rank --re-rank            # force full rescore
githired rank --limit 25 --llm     # optional AI stage
githired jobs --min-score 60       # confirmed shortlist
githired jobs --include-incomplete # browse before enrichment finishes
githired digest --save
githired sources
githired email-digest
githired run-daily                 # discover → enrich → rank → digest
githired run-daily --companies     # company discover then jobs pipeline
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

**Performance (important):**

| Setting | Role |
| --- | --- |
| `workday_list_budget_s` | Cap listing pagination only (default 180s) |
| `workday_detail_budget_s` | Cap description hydration only (default 120s) |
| `workday_description_ttl_s` | Reuse complete SQLite descriptions within TTL (default 7d) |
| `company_concurrency` | Parallel non-Workday boards (default 4) |
| `workday_company_concurrency` | Parallel Workday companies (default 2) |

Incomplete listing pagination **never** marks missing jobs removed. Warm daily runs should use `--mode quick`; schedule `--mode deep` weekly for full hydration.

Recommended cadence: `githired discover --mode quick && githired rank` daily; `githired discover --mode deep` weekly.

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
