# GitHired MCP QA Audit — 2026-11-25

Targeted audit against ChatGPT MCP failures on dataset `2221b573ce23086b`. Deterministic fixes only (no new LLM dependency). **Not claimed live until Worker + snapshot redeploy.**

## Root causes

### 1. Profile matching ranked DevOps / Full Stack over FDE / data roles

- **Cause:** Role-family scoring treated generic tokens (`engineer`, `software`) as sufficient; `ROLE_TRACK_HINTS` for “platform” opened `devops_sre` for Data Platform profiles; track affinity could effectively inflate non-title matches.
- **Fix (`api/src/match.ts`, `site/match-engine.js`):** Require at least one *specific* role token (e.g. `data`, `ai`, `forward`/`deployed`); keep short tokens `ai`/`ml`; title-only gate (track is boost-only); data↔lakehouse/etl aliases; partial specific overlap still clears ≥0.6 so Data Platform ↔ Data Engineer remains discoverable.

### 2. `match_profile` confirmed skills absent from `get_job` technologies

- **Cause:** `RELATED` mapped PySpark→Python (and similar), inventing confirmed overlap; raw substring prose hits (e.g. `rag` in `storage`).
- **Fix:** RELATED limited to specialization→broader *job tag* only (PostgreSQL→SQL). Job-side `JOB_EXPAND` still lets profile Python match a job tagged PySpark. Prose uses word-boundary checks only. Unconfirmed skills stay in gaps, not as matches.

### 3. Salary / currency (Hopper Canada vs Montréal)

- **Cause (confirmed on live Ashby `includeCompensation=true`):** Canada Remote FDE stamped `currencyCode: USD` on the 360–425k *base* Salary component while tier prose says CAD (and total-comp 400–520 CAD). Montréal twin publishes the same base band as CAD. US Remote correctly uses USD.
- **Not a currency bug:** Cohere Toronto “Canada” tier that explicitly lists USD (e.g. Senior Staff Data Engineer 380–450 USD) — employer-labeled; kept as USD (CAD conversion via FX for floors only).
- **Fix (`jobseek/adapters/ashby.py`):** Prefer geo-matched tiers (Canada / USA); reconcile Canada+USD structured codes against CAD prose (relabel base amounts to CAD when prose evidences CAD and no Canada-named USD tier); refuse only on explicit CAD+USD-base conflict; never publish equity/total-comp as base.

### 4. Dataset freshness (`dataset_fresh: false` on Nov 25 for Nov 23 export)

- **Expected:** `STALE_AFTER_HOURS=48` correctly marks a Nov 23 snapshot stale on Nov 25 — threshold was not raised to hide staleness.
- **Real serve bug:** Worker snapshot cache had no TTL (infinite isolate cache).
- **Fix:** 15-minute cache TTL in `api/src/dataset.ts`; MCP/REST already expose `dataset_fresh`, `dataset_age_hours`, `stale_after_hours`. Refresh failures remain observable via freshness fields; ops still need the scheduled export/deploy to land new R2/bundled snapshots.

### 5. Search vs `match_profile` inconsistency

- Keyword `search_jobs` is lexical; `match_profile` was over-broad on role family, so skill-overlapping DevOps floated above title-relevant FDE/DE roles. Tightening the title gate aligns ranking with intent while search remains available for exploration.
- `discovered_today` was frozen at export; now recomputed at serve from `first_seen` (`withLiveDiscoveredToday`).

## Before → after (synthetic regression slate)

| Metric | Before (reproduced) | After (`api/test/match_quality.test.js`) |
|--------|---------------------|------------------------------------------|
| Multi-role DE/AI/FDE top ranks | DevOps / Full Stack / SRE in top set | Only FDE / DE / lakehouse; DevOps/FS/SRE excluded |
| AI Engineer vs Full Stack / DevOps | Family score ≥0.6 (false open) | <0.6 |
| PySpark confirmed on Python-only job | Yes (RELATED) | No |
| Precision@5 across 10 personas | N/A (gold titles) | 1.0 on gold id per persona |
| Hopper Canada Remote base currency | USD 360–425k | CAD 360–425k (same amounts) |
| Hopper Montréal / US | CAD / USD | Unchanged |
| `discovered_today` days after `first_seen` | Stuck `true` | Live `false` |
| Snapshot cache | Forever | 15 minutes |

## Tests run

- `api`: `npm test` — **31/31 pass** (includes new `match_quality.test.js`)
- `tests/jobseek/test_ashby_compensation.py` + `test_salary_between_and_ashby.py` — **30/30 pass**
- Broader `tests/jobseek/` — 507 pass; 5 fail on **pre-existing** empty/fixture snapshot sync (`test_api_snapshot`, `test_public_shortlist`, `test_quality_gates`) unrelated to this change set

## Remaining limitations

- Employer-published USD on named Canada tiers (some Cohere bands) stay USD; unusually high bands may still be total-comp-adjacent if Ashby mis-tags components — we only strip non-`Salary` types.
- Base vs OTE: we keep Ashby `Salary` + `1 YEAR` only; Hopper total-comp prose (400–520) is not used as base.
- Freshness messaging is correct; curing `dataset_fresh: false` requires a successful discover→export→R2/deploy pipeline, not a longer stale window.
- Site `match-engine.js` is parity-updated; production site assets need the same deploy path as the API Worker.

## Deployment status

| Artifact | Status |
|----------|--------|
| Code fixes (match, ashby salary, cache TTL, discovered_today) | Implemented locally |
| Regression tests | Green for scoped suites |
| Commit / push / Worker deploy / snapshot refresh | **Not done** (awaiting explicit deploy) |

## Key files

- `api/src/match.ts`, `api/src/dataset.ts`, `api/src/search.ts`, `api/src/mcp.ts`
- `site/match-engine.js`
- `jobseek/adapters/ashby.py`
- `api/test/match_quality.test.js`, `tests/jobseek/test_ashby_compensation.py`
