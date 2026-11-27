# GitHired MCP QA Audit (pass 2) — 2026-11-27

Findings reproduced against dataset `c93daf41a38830ab`. Builds on [`qa-mcp-audit-2026-11-25.md`](qa-mcp-audit-2026-11-25.md). Deterministic fixes only; prior skill-matching improvements preserved.

## 1. Confirmed root causes

### P0 — `first_seen` reset on refresh
CI (`api-dataset.yml`) checks out a clean tree and discovers into a **fresh SQLite DB**, so every job gets `first_seen = rebuild day`. Public stable ids (`sha256(company|title|url)`) stay continuous across datasets, so Spellbook/`17c9fd3c7ceb9813` etc. reappeared with `first_seen: 2026-11-26` despite existing in the Nov 23 snapshot.

### P0 — Compensation (Hopper)
Live Ashby `includeCompensation=true` for AI Trust / Travel Intelligence:
- **Base** Salary component: 250–320k (USD on Canada AI Trust & US; CAD on Montréal / some Canada Travel twins).
- **Total compensation** prose: 360–420k in matching currency (equity + base).
GitHired correctly kept base in `salary_*`. Gap: total band was not exposed separately, so agents could not distinguish base vs total. Canada AI Trust USD is employer-stamped (tier prose also USD) — not a false currency inference.

### P1 — Geo ranking over relevance
`match_profile` (and search) sorted by `remoteScopeRank` **before** `match_score`, so canada-wide remote (score 57) could outrank province hybrid Solutions Architect (score 84).

### P1 — Multi-role ranking
Long skill lists diluted `matching/skills.length`. Unspecified seniority penalized FDE-style titles. Exact title credit was weak. Many DE-family hits crowded out near-peer FDE scores without diversity.

### P1 — Location semantics
`"Canada"` in `preferred_locations` matched any `"…, Canada"` hybrid (QC/BC), expanding hybrid eligibility unintentionally when combined with Ontario/Toronto.

### P2 — Description transparency
`description_complete: true` described the **stored** JD while clients only received a truncated `description_excerpt`, with no way to request longer text.

## 2. Changes implemented

| Area | Change |
|------|--------|
| Discovery history | `jobseek/discovery_history.py` + export merge from prior `api/data/jobs.snapshot.json` — keep earliest `first_seen`; recompute `discovered_today`; leave `last_verified` as this run |
| Compensation | Ashby annotates `salary_raw` with `total_comp CUR min-max`; API exposes `total_compensation_*` + note; filters still use base only |
| Ranking | Sort by score first; demote `remote_scope=global` only; canada vs province is tie-break only |
| Arrangements | Flat allow-list credit; optional `remote_preference_strength: equal \| prefer_remote` |
| Skills | Coverage vs soft expected band (not raw matching/total) |
| Multi-role | Exact-title bonus; soft FDE/null-seniority floor; `diversifyByRoleFamily` for near-peer families |
| Locations | Country vs regional prefs; Canada+Ontario no longer opens QC/BC hybrid; Canada-eligible remote always OK when remote allowed |
| get_job | Semantics note; `include_description` / `?include_description=true` for on-demand `description_full`; `description_excerpt_truncated` + `posted_date` on snapshot rows |
| Site | `match-engine.js` location filter aligned |

## 3. Before → after (tests / expected behaviour)

| Scenario | Before | After |
|----------|--------|--------|
| Stable id across rebuild | `first_seen` resets to rebuild day | Earliest prior `first_seen` preserved |
| Solutions Architect: score 84 hybrid vs 57 remote | Remote first (scope sort) | Higher score first |
| Canada+Ontario+Toronto hybrid QC | Included via “Canada” | Excluded; ON hybrid + CA remote kept |
| Multi-role FDE near DE peers | Buried under DE cluster | Near-peer diversity can surface FDE without promoting weak (score slack) |
| Hopper base vs total | Base only, total invisible | Base unchanged; total_comp annotated/exported |
| get_job complete+excerpt | Ambiguous | Explicit semantics + optional full fetch |

**Tests:** `api` `npm test` — **51/51**. Python: `test_discovery_history` + `test_ashby_compensation` — **23 pass**. Prior match-quality regressions (DevOps false opens, PySpark→Python, freshness) still green.

## 4. Remaining limitations

- Prior-snapshot merge requires the previous `jobs.snapshot.json` on disk at export (true for Actions checkout). Cold start with no prior file cannot invent history.
- Repost with a **new** apply URL → new stable id → new `first_seen` (intentional).
- Total compensation only when Ashby (or similar) prose matches the extractor; not a full multi-component ledger (bonus/OTE/equity % still not structured beyond EquityPercentage ignore).
- `description_full` is on-demand ATS fetch (latency/token cost); not stored in the Worker bundle.
- Candidate residence / commute / relocation remain implicit via `preferred_locations` + arrangements (backward compatible); no new required schema fields.

## 5. Deployment / dataset refresh status

| Item | Status |
|------|--------|
| Code changes | Local working tree (this pass) |
| Dataset refresh | Next `API dataset sync` export will preserve `first_seen` from the checked-out prior snapshot |
| Worker / MCP deploy | Not deployed in this pass |

## Key files

- `jobseek/discovery_history.py`, `jobseek/api_snapshot.py`, `scripts/export_api_snapshot.py`
- `jobseek/adapters/ashby.py`
- `api/src/match.ts`, `api/src/search.ts`, `api/src/mcp.ts`, `api/src/rest.ts`, `api/src/excerpt.ts`, `api/src/types.ts`
- `site/match-engine.js`
- `api/test/match_quality.test.js`, `tests/jobseek/test_discovery_history.py`, `tests/jobseek/test_ashby_compensation.py`
