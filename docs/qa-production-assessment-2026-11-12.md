# GitHired Production QA Assessment — 2026-11-12

Independent end-to-end quality assessment of **production** surfaces:

| Surface | Endpoint |
|---|---|
| Website | https://githired.ca |
| REST API | https://api.githired.ca |
| MCP | https://api.githired.ca/mcp |

**Assessor stance:** test and report only. No production data changes. No deploys. Code was not modified.

**Production dataset at test time**

| Field | Value |
|---|---|
| `dataset_id` (API/MCP) | `dfa8455b7d3e060f` |
| API `generated_at` | `2026-11-12T20:28:54Z` |
| Site `jobs.json` `generated_at` | `2026-11-12T18:57:49Z` |
| Published job count | **450** (site + API health; MCP `get_market_stats` agrees) |
| Companies | 72 |
| Arrangements (site) | remote 220 · hybrid 106 · onsite 23 · unspecified 101 |

Artifacts for reproduction:

- `docs/qa-artifacts-2026-11-12/run_production_qa.py` — REST harness
- `docs/qa-artifacts-2026-11-12/production_qa_results.json` — full machine-readable results
- `docs/qa-artifacts-2026-11-12/apply_url_checks.json` — ATS link probes
- `docs/qa-artifacts-2026-11-12/profile_tables.md` — top matches per profile

---

## 1. Executive summary

GitHired is **ready for public distribution**, with a small set of concrete defects that should be fixed soon but do not block a soft launch.

**What works well**

- Production connectivity is solid across website, REST, and MCP.
- Canada-eligible inventory is coherent (450 jobs), salaries are advertised-only, apply links resolve.
- Deterministic matching is fast, explainable, and consistent between REST and MCP.
- Website browse/search/filters/Load More/match flow works on desktop and mobile.

**What does not**

1. **P0 eligibility leak:** ElevenLabs `Forward Deployed Engineer - Software Engineer - Mexico` (`540ecf64ae26b6a1`) is published as Canada-eligible despite location `Mexico (Remote)`.
2. **P1 matching semantics:** `work_arrangements: ["remote"]` still admits `work_arrangement: "unspecified"` jobs (documented soft-pass in code, but surprising to users who selected remote-only).
3. **P1 sync drift:** site Pages snapshot and Worker API snapshot can diverge by a few job IDs and ~1.5h timestamps while both reporting count 450.
4. **P2 ranking breadth:** niche profiles (Data Analyst, Career Switcher, Frontend) often receive adjacent engineering roles; this is partly inventory limitation, partly role-family over-match.

**Overall quality score: 8.0 / 10**

| Area | Score | Notes |
|---|---|---|
| Website | 8.5 | Browse/match UX solid; long-lived tabs can show stale counts until reload |
| REST API | 9.0 | Health, search, match, errors, pagination all PASS |
| MCP | 9.0 | Live initialize + tools/list + tools/call PASS; matches REST |
| Matching | 7.0 | Strong for SE/data/AI core; weak on niche + junior intent |
| Data quality | 7.5 | Salaries honest; one clear non-Canada publish; multi-country remotes noisy |

**Recommendation:** Ship and distribute. Prioritize removing the Mexico listing (and similar non-Canada offices) before a loud launch. Do **not** rebuild matching, expand skill dictionaries, or weaken eligibility further.

---

## 2. Production connectivity results

| Check | Result | Evidence |
|---|---|---|
| `GET /api/v1/health` | **PASS** | 200, `status=ok`, `dataset.fresh=true`, count 450, ~185 ms |
| `GET /api/v1/stats` | **PASS** | 200, salary policy + eligibility present |
| `GET /api/v1/companies` | **PASS** | 200 |
| `GET /api/v1/jobs` | **PASS** | 200, pagination via `next_cursor` |
| `GET /api/v1/jobs/{id}` | **PASS** | 200 for known IDs; **404** `not_found` for bogus ID |
| `POST /api/v1/match` | **PASS** | 200; invalid JSON → **400** `invalid_json` |
| `GET https://githired.ca/` | **PASS** | 200 |
| `GET https://githired.ca/jobs.json` | **PASS** | 200, count 450 |
| `GET https://githired.ca/openapi.json` | **PASS** | 200 |
| MCP `GET /mcp` | **PASS** | 200 |
| MCP JSON-RPC `initialize` | **PASS** | protocol `2024-11-05`, server `githired` |
| MCP `tools/list` | **PASS** | `search_jobs`, `get_job`, `match_profile`, `get_market_stats` |
| MCP `tools/call search_jobs` | **PASS** | live results, same `dataset_id` |
| MCP Cursor namespace tools | **PASS** | `match_profile` / `search_jobs` / `get_market_stats` executed |

### Edge cases

| Case | Status | Observation |
|---|---|---|
| Empty keyword search | **PASS** | `q=zzzznonexistentxyz` → `total=0` |
| Extreme salary floor | **PASS** | `salary_min=900000` → `total=0` |
| Invalid `work_mode=telepathy` | **FAIL (soft)** | 200 with `total=450` — invalid enum ignored, not rejected |
| Pagination page 2 | **PASS** | cursor returns distinct IDs |
| Empty match body `{}` | **PASS** | returns matches (open profile) |

Reproduce:

```bash
curl -sS https://api.githired.ca/api/v1/health | jq .
python3 docs/qa-artifacts-2026-11-12/run_production_qa.py
```

---

## 3–4. Ten candidate profiles and top matches

Full tables: [`docs/qa-artifacts-2026-11-12/profile_tables.md`](qa-artifacts-2026-11-12/profile_tables.md).

Legend for relevance judgments below: **Strong** / **Acceptable** / **Weak** / **Bad**.  
Sparse results for niche roles are marked as **inventory limit**, not automatic matching defects.

### P01 — Junior Python Developer (Toronto, hybrid, $65k+)

| Status | **PASS with defects** |
|---|---|
| REST matches | 10 |
| MCP matches | 10 (same top IDs as REST) |

Top results include strong hits (`PolicyMe` Junior Software Engineer, TD Software Engineer I) and one **Bad** result: ElevenLabs Mexico (`540ecf64ae26b6a1`). Junior → mid/senior adjacent roles are common when job seniority is unspecified.

### P02 — Senior Data Engineer (remote Canada, Python/SQL/Spark, $150k+)

| Status | **PASS** |
|---|---|
| REST/MCP matches | 10 |

Strong data-platform alignment (Later, Northbeam, Waabi, RBC Senior Data Engineer).  
**Caveat:** with `work_arrangements=["remote"]`, PointClickCare Mississauga (`unspecified`) still appears — soft arrangement pass. Salary flexible mode correctly allows max-only floor meets and labels gaps.

### P03 — Frontend Developer (Vancouver, React/TS, $90k+)

| Status | **PASS / inventory+matching mix** |
|---|---|
| Matches | 10 |

Few true “Frontend” titles; results skew full-stack / general SE. Affirm Frontend role is **Strong**; several others **Weak** title match despite React/TS skills. Treat primarily as **inventory limit** for pure frontend Canada roles, with role-family overbreadth as secondary.

### P04 — Staff AI Engineer (remote, LLM/RAG/AWS, $200k+)

| Status | **PASS with weak mid-list** |
|---|---|
| Matches | 10 |

Twilio Staff ML Engineer and Wrapbook Applied AI are **Strong**. Blackpoint/Affirm Staff SE and ClickHouse SRE are **Weak** AI-title matches (skills may hit via excerpt tags). Unspecified RBC Senior AI Engineer appears under remote-only filter (same soft-pass).

### P05 — DevOps Engineer (Calgary, K8s/TF/AWS, $130k+)

| Status | **PASS / geo soft** |
|---|---|
| Matches | 10 |

Platform/SRE/cloud roles surface (GitLab, Air-tek, Affirm compute). Calgary-specific inventory is thin; remote Canada fills the list — acceptable if user allows remote, otherwise city preference is soft.

### P06 — Data Analyst (Montreal, SQL/Power BI, $75k+)

| Status | **PASS as inventory limit** |
|---|---|
| Matches | 8 |

Almost all results are **Data Engineer** roles. GitHired’s public corpus is engineering-heavy; analyst titles are scarce. Matching defect secondary: role family maps analyst → data engineering too eagerly.

### P07 — Cybersecurity Engineer (Ottawa, SIEM/cloud security, $140k+)

| Status | **PASS as inventory limit** |
|---|---|
| Matches | 6 |

Security-flavored SE roles (GitLab Security Factory, Docker Desktop Security, Tailscale Security Infra). True SIEM/SOC titles scarce — dataset limitation. Results still security-adjacent, not random.

### P08 — Backend Engineer (Toronto, Java/Spring, $110k+)

| Status | **PASS** |
|---|---|
| Matches | 10 |

Manulife backend/fullstack hybrid Toronto roles and PointClickCare intermediate SE are **Acceptable/Strong**. Java/Spring exact matches are thinner than Python SE inventory.

### P09 — Career Switcher (0 YOE, Python/SQL, remote, no salary floor)

| Status | **FAIL (matching intent)** |
|---|---|
| Matches | 10 |

Top ranks are mid-level Data Engineer / SE roles. PolicyMe Junior is present but not first. Mexico job appears again. System does not adequately hard-constrain to junior/entry when `years_experience=0` + `seniority=junior` if job seniority is null.

### P10 — Senior Solutions Architect (Databricks/cloud/customer-facing, $170k+)

| Status | **PASS as inventory limit** |
|---|---|
| Matches | 4 |

Sparse by design. Forward Deployed Engineer roles (Tailscale, Camunda) are the closest family. Mexico FDE also appears — eligibility defect, not ranking logic.

---

## 5. Website vs API vs MCP consistency

| Comparison | Result |
|---|---|
| API health count vs MCP `get_market_stats` | **PASS** — both 450, same `dataset_id` |
| Site `jobs.json` count vs API | **PASS** count (450); **FAIL soft** on ID set — 6 IDs only-on-site, 6 only-on-API |
| Site vs API top-20 salary order | **PASS** when both fresh — identical ID order at test time |
| REST `match` vs MCP `match_profile` (P01/P02/P09) | **PASS** — same IDs/scores for equivalent payloads |
| Website in-browser match (P02-like) | **PASS** — 14 matches, overlapping Northbeam/Waabi/Supabase/RBC; client engine can return Amplify new-grad roles the API also ranks low |

**Documented semantic differences (not bugs):**

- MCP/REST `search_jobs` `total` is filter-scoped; health/stats count is full inventory.
- Website match uses local `match-engine.js` over `jobs.json` (Pages); API/MCP use Worker snapshot — can differ during sync windows.
- Match `work_arrangements` soft-allows `unspecified` (code comment in `api/src/match.ts`).

**Stale-tab observation:** a long-open browser tab showed “358 jobs · Nov 9” until hard navigation; fresh load shows 450 · Nov 12. Fetch with `cache: no-cache` returns current JSON. Not a corrupt deploy — client cache / long-lived session.

---

## 6. Data quality findings

| Check | Result | Notes |
|---|---|---|
| Estimated salaries as confirmed | **PASS** | `salary_kind` only `advertised_base` / `undisclosed` in samples |
| Missing excerpts on detail | **PASS** | 0 missing in sampled details |
| Company+title duplicates in export | **PASS** | 0 |
| Apply URL liveness (15 jobs, Greenhouse/Ashby/Workday) | **PASS** | 15/15 HTTP OK |
| Non-Canada office published | **FAIL** | ElevenLabs Mexico Remote |
| CA\|US multi-country remotes | **PASS with noise** | GitLab/1Password/ClickHouse etc. correctly Canada-eligible but location strings are busy |
| Remote without Canada token | Present | 42 remote jobs with `remote_scope=unspecified` (e.g. Remote Global) — eligibility path dependent; needs ongoing audit |
| Skill tags | Mostly honest | Occasional over-hit (AI skills on non-AI titles) via excerpt/title substring |

ATS diversity sampled: Greenhouse, Ashby, Workday, Lever — not single-source.

---

## 7. Bugs

### BUG-1 — Mexico remote published as Canada-eligible  
**Severity:** P0  
**Status:** FAIL  
**Evidence:** `GET /api/v1/jobs/540ecf64ae26b6a1` → location `Mexico (Remote)`, `work_arrangement=remote`, appears in site/API/MCP search for “Mexico” and in junior/career-switcher matches.  
**Steps:**

```bash
curl -sS 'https://api.githired.ca/api/v1/jobs?q=Mexico&limit=5' | jq '.jobs[]|{id,title,location}'
```

**Expected:** not in Canada-eligible export.  
**Impact:** credibility risk on the product’s core promise.

### BUG-2 — Remote-only match admits unspecified arrangement  
**Severity:** P1  
**Status:** FAIL (product expectation) / PASS (current coded semantics)  
**Evidence:** P02 remote-only returns PointClickCare Mississauga `unspecified` and RBC Toronto `unspecified`. Code: `arrangementAllowed` returns true for unspecified.  
**Recommendation:** either hard-exclude unspecified when user selected explicit arrangements, or label UI/API note more prominently (“unspecified arrangements are included”).

### BUG-3 — Site Pages vs API Worker snapshot drift  
**Severity:** P1 (ops)  
**Evidence:** identical counts (450) but 6 divergent IDs; `generated_at` differs (~18:57 site vs ~20:28 API).  
**Impact:** website match vs API/MCP match can disagree briefly after sync.

### BUG-4 — Invalid `work_mode` silently ignored  
**Severity:** P2  
**Evidence:** `GET /api/v1/jobs?work_mode=telepathy` returns full inventory.  
**Expected:** 400 or empty with validation error.

### BUG-5 — Junior / 0-YOE ranking too senior  
**Severity:** P2  
**Evidence:** P09 top results are mid Data Engineer roles; junior PolicyMe ranked #7 on MCP.  
**Note:** Distinguish from inventory scarcity of true junior roles (PolicyMe exists and ranks, but not first).

### BUG-6 — Role-family over-match for Analyst / Frontend / Architect  
**Severity:** P2  
**Evidence:** P06→Data Engineer; P03→many non-frontend SE; P10 sparse but FDE-skewed.

---

## 8. What GitHired does particularly well

1. **Honest salary handling** — advertised annual base only; flexible vs strict floors explained in match gaps.
2. **Fast deterministic matching** — website scored P02 in ~19 ms client-side; API match ~100–160 ms.
3. **Triple-surface coherence** — website, REST, MCP share one Canada-eligible model and stable IDs.
4. **Clean public UX** — search chips, arrangement filters, salary sort default, Load More, mobile hamburger, privacy copy for résumé matching.
5. **Agent DX** — OpenAPI, MCP initialize/tools, no auth wall for read paths.
6. **Apply URL quality** — sampled Greenhouse/Ashby/Workday links live.

---

## 9. Recommended improvements (P0–P3)

| Priority | Item | Why |
|---|---|---|
| **P0** | Exclude non-Canada office remotes (Mexico, and audit similar) from export | Core trust |
| **P1** | Align Pages + Worker dataset publish (same export job / shared artifact) | Consistency |
| **P1** | Tighten remote-only filter **or** document unspecified inclusion in UI/OpenAPI | Expectation match |
| **P2** | Stronger junior/0-YOE demotion when job seniority missing | Career switcher intent |
| **P2** | Validate `work_mode` enum on REST search | API correctness |
| **P2** | Narrow analyst/frontend role-family mapping slightly | Precision |
| **P3** | Reduce excerpt-based skill false positives for LLM/RAG tags | Match quality |
| **P3** | Consider Cache-Control / version query on `jobs.json` for long-lived tabs | Stale UI |

---

## 10. Explicit “do nothing” recommendations

Do **not**:

- Rebuild the matcher or introduce an LLM ranker for v1 public launch.
- Expand skill dictionaries or salary parsers “for completeness.”
- Weaken Canada eligibility to grow inventory.
- Block public distribution solely because Data Analyst / Solutions Architect inventories are thin — disclose engineering focus instead.
- Treat CA\|US dual remotes as defects when Canada is evidenced.
- Churn website UI; filters and match flow are already usable.

---

## 11. Scores and launch verdict

| Area | /10 |
|---|---|
| Website | 8.5 |
| REST API | 9.0 |
| MCP | 9.0 |
| Matching | 7.0 |
| Data quality | 7.5 |
| **Overall** | **8.0** |

### Launch verdict

**Ready for public distribution**, preferably after **BUG-1 (Mexico eligibility)** is removed from the next export. Remaining items are polish and expectation-tuning, not blockers for a soft public launch and distribution push.

If forced to choose one sentence: *GitHired’s production stack works; fix the one non-Canada publish, then focus on distribution rather than more features.*

---

## Appendix A — Sample requests

### REST match (P02)

```bash
curl -sS https://api.githired.ca/api/v1/match \
  -H 'content-type: application/json' \
  -d '{
    "skills":["Python","SQL","Spark"],
    "years_experience":6,
    "preferred_roles":["Senior Data Engineer","Data Engineer"],
    "preferred_locations":["Canada"],
    "work_arrangements":["remote"],
    "remote_preference":true,
    "minimum_salary":150000,
    "seniority":"senior",
    "limit":10,
    "salary_mode":"flexible"
  }' | jq '{dataset_id,count:(.matches|length),ids:[.matches[].id]}'
```

### MCP initialize + tool call

```bash
curl -sS https://api.githired.ca/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"qa","version":"1"}}}'

curl -sS https://api.githired.ca/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_jobs","arguments":{"keywords":"data engineer","remote":true,"minimum_salary":150000,"limit":5}}}'
```

### Full harness

```bash
python3 docs/qa-artifacts-2026-11-12/run_production_qa.py
```

## Appendix B — Website browser tests (summary)

| Test | Result |
|---|---|
| Fresh load inventory meta | **PASS** — 450 · Nov 12 |
| Default sort salary | **PASS** |
| Search `data engineer` | **PASS** — 62 matches |
| Arrangement = Remote | **PASS** — 62→22 |
| Load More control present | **PASS** |
| Find My Matches manual profile → results | **PASS** — 14 matches / 19 ms |
| Mobile (390×844) hamburger + load | **PASS** |
| Stale long-lived tab | **OBSERVED** — showed 358 until hard navigation |

Browser automation used Cursor IDE browser tools against https://githired.ca (not localhost).
