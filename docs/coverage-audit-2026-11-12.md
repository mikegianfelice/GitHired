# GitHired coverage, matching QA & employer expansion (2026-11-12)

## 1. Inventory audit

| Metric | Value |
|---|---|
| Raw jobs | 21,503 |
| Active jobs | 21,400 |
| Description-complete (active) | 16,760 (78.3%) |
| Pipeline-eligible (pre-dedupe) | 542 |
| Public / API export | **500** (cap raised from 400) |
| Exposure rate (public/raw) | 2.33% |

**Why raw ≫ public:** Most ATS scrapes are global non-tech or non-Canada listings. Searchable inventory requires track match + Canada ELIGIBLE + complete description + direct apply URL + freshness ≤21 days, then company+title dedupe.

### Primary exclusion breakdown (one reason per job)

| Reason | Count |
|---|---|
| Nontechnical / off-track | 13,094 |
| Insufficient description | 4,640 |
| Outside Canada | 2,437 |
| Eligible (pre-dedupe) | 542 |
| Apply URL not job-specific | 351 |
| Canada eligibility unknown | 226 |
| Seniority excluded | 108 |
| Closed/removed | 103 |
| Geographic restrictions | 2 |

### Confirmed false negatives & fix

**Bug:** Canadian city-only locations (`Toronto, Canada`, `Vancouver, …`) with no remote/hybrid token were left `work_arrangement=unknown`, demoting otherwise Canada-compatible tech roles to UNCERTAIN (~148 track-matched cases; Lyft/Braze/Coursera/Pinterest/etc.).

**Fix:** When structured location is a Canadian city without remote/hybrid tokens and `onsite` is an allowed mode, treat arrangement as **onsite** for eligibility (never invent remote). Public cards use the same default.

**Impact:** Eligible pre-dedupe ~371 → **542**; public export filled the new **500** cap (was 358–400). Unknown Canada eligibility 349 → **226**.

Undisclosed salary is **not** a public exclusion (`PUBLIC_SEARCH` salary policy=`none`).

## 2. Matching QA (10 personas)

Local website engine + local API `matchProfile` + live REST/MCP (pre-deploy dataset) exercised via `scripts/match_persona_qa.py`.

| Persona | Site | Local API | Live API | Live MCP | Notes |
|---|---|---|---|---|---|
| A Senior Data Engineer | 10 | 10 | 10 | 10 | Role-family + remote/hybrid OK |
| B Junior Frontend | 10 | 10 | 10 | 10 | SE I / Intermediate ahead of staff |
| C Platform Engineer | 10 | 10 | 10 | 10 | Platform/SRE remote prioritized |
| D Analytics Engineer | 10 | 10 | 9 | 9 | Local top includes Lightspeed Analytics |
| E Control-M | 10 | 10 | 10 | 10 | `control_m_matched=0` (no invented hits) |
| F Strict Remote | 10 | 10 | 10 | 10 | `strict_remote_ok` (no hybrid/onsite) |
| G Senior AI Engineer | 10 | 10 | 10 | 10 | AI/ML titles present |
| H DevOps / SRE | 10 | 10 | 10 | 10 | Terraform/K8s-relevant SRE/platform |
| I Backend Engineer | 10 | 10 | 10 | 10 | Backend titles; not generic-only inflation |
| J New Graduate | 10 | 10 | 10 | 10 | Includes Junior SE; years=0 soft penalty |

Website vs API scores differ when site uses disciplines / salary_filter_mode; eligibility and arrangement filters align for equivalent prefs.

## 3. Employer expansion

| Action | Count / detail |
|---|---|
| Evaluated boards | 70+ probes (Ashby/Greenhouse/Lever/Workable) |
| Re-enabled (prior uncertain CA signals) | 12 (PostHog, Supabase, Oyster, Linear, PlanetScale, Cockroach Labs, Relay, Reflow, Merge, Maple, FutureFit AI, Blockstream) |
| New employers | 9 (AbCellera, Airbyte, MagicSchool, Nuvei, ElevenLabs, LangChain, Fireworks AI, Anyscale, Replicant) |
| Board fix | **Lightspeed** `lightspeed` → `lightspeedhq` (10 → 128 jobs) |
| Targeted discover | 22 companies → **908 new** rows, 11 updates, 0 fetch errors |
| In public snapshot (sample) | Supabase 19, ElevenLabs 4, Lightspeed 3, Replicant 1 |

Did **not** re-enable boards previously marked zero Canada loc signals with zero uncertain (e.g. Modal/Vercel/Writer) to avoid runtime without yield.

## 4. Quality scorecard

Scripts (gitignored output under `reports/`):

- `scripts/audit_inventory.py` → `reports/inventory_audit.json`
- `scripts/quality_scorecard.py` → `reports/quality_scorecard.{json,md}`
- `scripts/match_persona_qa.py` → `reports/match_persona_qa.json`
- `scripts/discover_companies.py` → subset discover

Metrics snapshot: hydration 78.3%, salary disclosure 40.4%, public skill tags 94.2%, apply URL 100%, unknown arrangements 2.

## 5. Quality gates & sync

- `tests/jobseek/test_quality_gates.py` — city-office eligibility, snapshot sync, cap ≥500
- Workflows `api-dataset.yml` / `public-shortlist-pages.yml` export `--limit 500`
- Site/API snapshots both **500** jobs, dataset `205cafd6508a4180`

## 6. Remaining limitations

- Public cap 500; uncapped eligible ~542 (some trimmed by salary-sort + dedupe).
- Live API/MCP update after Worker deploy from this commit.
- Many global remote AI boards still contribute few Canada-ELIGIBLE rows (description evidence required).
- `Blackpoint Cyber` board token contains a space (`InvalidURL`) — not fixed in this batch.
- Persona scores are relevance, not hire probability.
