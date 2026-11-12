# GitHired Quality Fixes — 2026-11-12

Targeted release from [`qa-production-assessment-2026-11-12.md`](qa-production-assessment-2026-11-12.md). Goal: fix confirmed defects, preserve working matching/salary/UX, prepare for public distribution. **Production is not claimed fixed until live deploy is verified.**

Local post-fix dataset (committed snapshots, not yet live):

| Field | Value |
|---|---|
| Job count | **524** (was 525 locally / 450 on production at QA time) |
| API `dataset_id` | `266ba13f4680c62a` |
| Mexico-only ElevenLabs `540ecf64ae26b6a1` | **removed** |
| Soft publish cap | 10000 (not binding) |

Artifacts: [`qa-artifacts-2026-11-12/`](qa-artifacts-2026-11-12/).

---

## 1. Root causes identified

### 1.1 Canada eligibility leak (P0)

**Symptom:** ElevenLabs *Forward Deployed Engineer - Software Engineer - Mexico* (`540ecf64ae26b6a1`, location `Mexico (Remote)`) published as Canada-eligible.

**Cause:** `_OVERSEAS_LOCATION` in `jobseek/filters/location.py` matched `mexico city` but **not bare `mexico`**. Combined with work-from-anywhere marketing copy (`remote-first` + `anywhere`), the classifier treated the job as worldwide remote → `ELIGIBLE`.

**Not the cause:** intentional Canada/US dual listings, or multi-country remotes that explicitly include Canada (e.g. GitLab `Remote, Canada; Remote, United Kingdom`).

### 1.2 Remote-only matching (P1)

**Symptom:** `work_arrangements: ["remote"]` returned `work_arrangement: "unspecified"` jobs (e.g. PointClickCare / RBC under P02).

**Cause:** arrangement filter soft-passed unknown/unspecified when the user had explicitly selected arrangements.

### 1.3 Junior / career-switcher ranking (P1)

**Symptom:** P09 (0 YOE, junior) ranked mid-level Data Engineer titles above PolicyMe Junior Software Engineer; unknown seniority treated too generously.

**Cause:** seniority weight + skill overlap outweighed band mismatch; no junior-title boost / mid-senior demotion for junior profiles.

### 1.4 Site vs API dataset drift (investigated — no code defect)

**Symptom:** QA saw 450 jobs on both surfaces but **six differing IDs**; timestamps ~1.5h apart (`18:57Z` site vs `20:28Z` API).

**Cause:** independent schedules and exporters:

- Pages shortlist: `.github/workflows/public-shortlist-pages.yml` cron `17 11 * * *`
- API Worker snapshot: `.github/workflows/api-dataset.yml` cron `40 12 * * *`

Both call the same selection logic (`select_public_jobs` / shared export path) but against discovery state at different times. Drift within the daily window is **expected temporary divergence**, not a sync bug.

Local re-export of both artifacts from the same DB produced **identical 524 IDs**.

### 1.5 Invalid `work_mode` (P2)

**Symptom:** `GET /api/v1/jobs?work_mode=telepathy` returned 200 with full inventory.

**Cause:** unknown enum values were ignored instead of rejected.

### 1.6 Inventory funnel (~21.4k → ~524)

Not a defect in the publish cap. Primary attrition is role track + description completeness + geography (see §5). Cap is already 10000.

---

## 2. Changes implemented

| Area | Change | Files |
|---|---|---|
| Eligibility | Add bare `(?<!new\s)mexico` to overseas location patterns (preserve `New Mexico`) | `jobseek/filters/location.py` |
| Eligibility tests | Mexico-only + WFA, US-only, Canada-only, Canada/US, worldwide remote, New Mexico | `tests/jobseek/test_foreign_geo_ineligible.py` |
| Matching | Hard allow-list for explicit arrangements; unspecified excluded when remote-only | `api/src/match.ts`, `site/match-engine.js` |
| Junior ranking | Title junior/senior signals; boost confirmed junior; demote mid/senior/staff for junior profiles; unknown seniority cautious (0.35) | same |
| API validation | `SearchFilterValidationError` → HTTP 400 `invalid_work_mode`; MCP tool error for bad `work_mode` | `api/src/search.ts`, `rest.ts`, `mcp.ts` |
| Snapshots | Re-exported shortlist + API snapshot (Mexico removed) | `site/jobs.json`, `api/data/jobs.snapshot.json`, `site/api-dataset.json` |
| Tests | Match + search validation regressions | `api/test/match.test.js`, `api/test/search_validation.test.js`, `tests/jobseek/test_match_engine.js` |

**Left unchanged (working):** salary extraction/policy, skill dictionaries, website UX/layout, LLM absence, discovery adapters, soft publish cap (10000).

---

## 3. Before / after results

### Eligibility

| Case | Before | After |
|---|---|---|
| `Mexico (Remote)` + WFA body | ELIGIBLE (leak) | **INELIGIBLE** |
| `Remote - Mexico` | often leak / uncertain | **INELIGIBLE** |
| `New Mexico-Remote` | US-ineligible | **INELIGIBLE** (still US; not confused as country Mexico) |
| `Remote - Canada Only` | ELIGIBLE | ELIGIBLE |
| `Remote (United States \| Canada)` | ELIGIBLE | ELIGIBLE |
| Bare `Remote` + genuine worldwide | ELIGIBLE | ELIGIBLE |
| `Remote, USA` | INELIGIBLE | INELIGIBLE |
| Multi-country **including Canada** (GitLab etc.) | ELIGIBLE | ELIGIBLE (preserved) |

Published audit of local `site/jobs.json` after fix: **0** Mexico-only (non–New Mexico) locations. ElevenLabs id `540ecf64ae26b6a1` absent.

### Remote-only matching

| Profile | Before (production QA) | After (local snapshot) |
|---|---|---|
| P02 Senior DE, `["remote"]` | Unspecified jobs in top 10 (PointClickCare, Waabi, RBC) | **0 unspecified**; all matches `remote` |
| P04 / P09 remote-only | Unspecified / Mexico leaks possible | **0 unspecified**; Mexico gone |

Flexible behavior when arrangements omitted: unspecified jobs still match (regression covered).

### Junior / career switcher (P09)

| | Before | After (site match-engine) |
|---|---|---|
| #1 | Samsara Data Engineer (mid-ish, score 87) | **PolicyMe Junior Software Engineer** (92) |
| #2 | Loopio Data Engineer | **PointClickCare Canada- Jr Software Engineer (SRE)** (80) |
| Genuine junior rank | #7 (82) behind six mid roles | **#1** |
| Mexico leak | #8 | **gone** |

API `matchProfile` agrees: PolicyMe Junior #1 (score 94).

### Senior / staff non-regression (local)

| Profile | After #1 | Notes |
|---|---|---|
| P02 Senior Data Engineer | Later Senior Data Platform Engineer (92) | Still strong data-platform alignment |
| P04 Staff AI Engineer | Twilio Staff Machine Learning Engineer (92) | Staff AI path preserved |
| P08 Backend Engineer | Manulife Full Stack Software Engineer (75) | Still returns backend-adjacent SE |

---

## 4. Regression test results

All run locally after the changes:

| Suite | Result |
|---|---|
| `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/jobseek/test_foreign_geo_ineligible.py tests/jobseek/test_api_snapshot.py` | **28 passed** |
| `node --test tests/jobseek/test_match_engine.js tests/jobseek/test_match_qa_personas.js` | **48 passed** |
| `cd api && npm test` | **22 passed** (incl. remote-only, junior ranking, `work_mode=telepathy`) |

Local 10-profile sweep: [`qa-artifacts-2026-11-12/post_fix_local_regression.json`](qa-artifacts-2026-11-12/post_fix_local_regression.json)

| Check | Result |
|---|---|
| Mexico leak in any profile top-10 | **false** for P01–P10 |
| Unspecified under remote-only (P02/P04/P09) | **0** |
| Dedup / salary honesty | unchanged (existing tests still green) |

**Production REST/MCP/website re-run of the 10 mock profiles is still required after deploy** — local results prove code + snapshot, not live Worker/Pages.

---

## 5. Updated inventory funnel

From [`qa-artifacts-2026-11-12/inventory_funnel.json`](qa-artifacts-2026-11-12/inventory_funnel.json) against `data/jobseek.db`:

| Stage | Count |
|---|---|
| Raw jobs | 21,503 |
| Active (not removed) | 21,400 |
| Primary: nontechnical / off-track | 13,094 |
| Primary: insufficient description | 4,640 |
| Primary: outside Canada | 2,442 |
| Primary: Canada eligibility unknown (FLAG) | 223 |
| Primary: apply URL not job-specific | 351 |
| Primary: seniority excluded | 108 |
| Closed/removed | 103 |
| Pipeline eligible (pre-dedupe) | **541** |
| Public export after dedupe / URL rules | **524** |
| Soft publish cap | **10,000** (not binding) |
| Active → public | ~2.45% |

### Are legitimate Canadian tech jobs excluded unnecessarily?

| Bucket | Verdict |
|---|---|
| Nontechnical / off-track | Expected — public product is engineering/tech tracks |
| Insufficient description | Mostly Workday/bank listings without usable JD text — enrich more, don’t loosen eligibility |
| Outside Canada | Correct rejects (incl. Mexico-only after this fix) |
| Unknown eligibility (223) | Correct caution — do **not** auto-promote to ELIGIBLE |
| Apply URL not job-specific | Correct quality gate |
| Publish cap | **Not a limiter** at 524 ≪ 10000 |

**Recommendation: do not raise the publishing cap.** Coverage gains come from description enrichment (esp. Workday) and employer expansion, not from publishing more weakly evidenced rows.

---

## 6. Unresolved issues

1. **Live production still serves the pre-fix snapshot** until Pages + Worker are redeployed (see §8).
2. Niche inventory limits (pure Frontend / Data Analyst / Cyber) remain — matching overbreadth is secondary; do not expand skill dictionaries without evidence.
3. Site vs API can still diverge for ~1–2h daily by design (separate crons). Acceptable for soft launch.
4. 142 `unspecified` arrangement jobs remain in the public set — visible in browse when no arrangement filter is set; correctly hidden from remote-only match.
5. `canada_eligibility_unknown` (223) may hide some recoverable Canada hires — investigate with targeted phrase mining later; out of scope here.

---

## 7. Explicit “leave unchanged” recommendations

- **Do not** redesign the website or rebuild the matcher.
- **Do not** add an LLM ranker.
- **Do not** expand skill synonym dictionaries without measured false-negative evidence.
- **Do not** change salary extraction / “advertised only” policy.
- **Do not** weaken Canada eligibility to grow counts.
- **Do not** raise the soft publish cap (already 10000).
- **Do not** merge Pages + Worker into one deploy pipeline solely for the 6-ID drift window — optional future hardening only if drift becomes user-visible after launch.
- **Do not** hard-exclude unknown-seniority jobs for junior profiles (kept cautious soft score).

---

## 8. Production deployment instructions

Code + regenerated snapshots are committed; **nothing was deployed from this session.**

### Required for the eligibility + dataset fix to reach users

1. **Merge/push** this commit to `main` (triggers static site workflow when `site/` changes; confirm Pages deploy of new `jobs.json`).
2. **API/MCP Worker** — either:
   - Wait for scheduled `API dataset sync` (`40 12 * * *` UTC), or
   - Manually run workflow **“API dataset sync”** (`workflow_dispatch`) so the Worker bundles the new snapshot and redeploys.
3. Optionally re-run **“Public shortlist (GitHub Pages)”** if Pages did not pick up `site/jobs.json` from the push path you use.
4. **Verify live** (do not claim fixed until these pass):

```bash
# Mexico job must 404 / be absent
curl -sS https://api.githired.ca/api/v1/jobs/540ecf64ae26b6a1 | jq .
python3 -c "import json,urllib.request; d=json.load(urllib.request.urlopen('https://githired.ca/jobs.json')); print(any(j['id']=='540ecf64ae26b6a1' for j in d['jobs']))"

# Invalid enum
curl -sS -o /tmp/wm.json -w '%{http_code}\n' 'https://api.githired.ca/api/v1/jobs?work_mode=telepathy'
# expect 400 + invalid_work_mode

# Remote-only match: no unspecified arrangements in results
curl -sS -X POST https://api.githired.ca/api/v1/match \
  -H 'content-type: application/json' \
  -d '{"preferred_roles":["Senior Data Engineer"],"skills":["Python","SQL","Spark"],"years_experience":6,"work_arrangements":["remote"],"minimum_salary":150000,"limit":10}' \
  | jq '[.matches[].work_arrangement] | unique'

# Re-run full 10-profile harness
python3 docs/qa-artifacts-2026-11-12/run_production_qa.py
```

### Worker code (match + 400 validation)

Redeploying the Worker is required for remote-only / junior ranking / `work_mode` validation even if the dataset were unchanged — snapshot-only refresh is **not** enough for those API behaviors.

---

## Summary

| Item | Outcome |
|---|---|
| Mexico eligibility | **Fixed** in classifier + snapshots |
| Remote-only semantics | **Fixed** (API + site; MCP uses same matcher) |
| Junior ranking | **Small boost/demote** applied; experienced personas still strong locally |
| Site/API sync | **No change** — expected schedule drift |
| `work_mode` validation | **400** for unsupported enums |
| Inventory cap | **Leave at 10000**; not the bottleneck |
| Production | **Pending deploy + live verification** |
