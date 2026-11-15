# Employer expansion audit (2026-11-15)

Source leads: `githired_expansion_candidates.csv` (73 employers). Treated as discovery leads only; each board was revalidated live against supported adapters (Ashby, Lever, Greenhouse, Workday). **Do nothing** was the default for unverified, inaccessible, unsupported, or zero-relevant employers.

## Summary

| Metric | Before | After | Δ |
|---|---:|---:|---:|
| Builtin `companies.yaml` | 145 (134 enabled) | 171 (160 enabled) | +26 (+26 enabled) |
| Jobs in SQLite (all) | 21503 | 22685 | +1182 |
| Open jobs | 21400 | 22582 | +1182 |
| Description-complete open | 16760 | 17942 | +1182 |
| Canada ELIGIBLE (desc-complete) | 2008 | 2451 | +443 |
| Canada UNCERTAIN (desc-complete) | 1358 | 1618 | +260 |
| Track-matched (desc-complete) | 3396 | 3593 | +197 |
| **Mid+ tech × Canada ELIGIBLE** | **517** | **584** | **+67** |
| Net-new eligible from added employers (sum) | — | 68 | — |

### Decisions

- **Added (enabled):** 26 employers
- **Skipped:** 47 employers (including already-present Wealthsimple)
- **New ATS integrations:** none (Workday/Ashby/Lever only)
- **Filters:** unchanged — no weakening of Canada eligibility, track, or seniority gates

### Runtime & adapter health (targeted discover of 26 adds)

- Wall clock: **157.6s** for 26 boards
- Jobs fetched: **1182 new** / 0 updated / **0 adapter failures**
- Dominated by Workday: Desjardins ≈115s (415 jobs), Canadian Tire ≈29s (128 jobs); remaining Ashby/Lever boards <3s each
- Accenture Workday was probed but **not added** (≈173s / ~1970 jobs / 0 Canada-eligible tech) — avoided as pure runtime cost
- Loblaw `myview/paradox_careers` (~15k retail) was **not added** for the same reason

### Public / API caps

- Public shortlist / API export caps were **not changed**.
- Eligible inventory rose (~+67 mid+ tech×Canada). Existing 500 public cap will continue to select by quality/freshness; a future export refresh may reshuffle cards but does not require a cap increase based on this expansion alone.

### False positives avoided

- Kepler Communications: only track match was an **intern** (seniority-excluded)
- Fellow new-grad posting seniority-excluded; mid+ Canada Remote SWE still qualifies → added
- ShyftLabs intern excluded; remaining AI/Data/FDE roles kept
- Enbridge Workday: Canada locations present but **0** track-matched engineering titles
- Consulting/enterprise boards on Phenom / SuccessFactors / iCIMS / Ultipro / SmartRecruiters / njoyn: unsupported → skipped (no new ATS adapter)

## Per-candidate audit

| Employer | Already present | ATS | Board URL | Live tech×Canada (mid+) | Decision | Reason | Net-new eligible |
|---|---|---|---|---:|---|---|---:|
| Terminal | no | ashby | https://jobs.ashbyhq.com/terminal | 2 | added | Live validated ashby/terminal; mid+ Canada tech roles=2 | 2 |
| Lago | no | ashby | https://jobs.ashbyhq.com/lago | 0 | skipped | Ashby board token lago → HTTP 404 | 0 |
| Scalar | no | ashby | https://jobs.ashbyhq.com/scalar | 0 | skipped | Board live (5 jobs) but 0 Canada-eligible tech track roles | 0 |
| Kong | no | ashby | https://jobs.ashbyhq.com/kong | 3 | added | Live validated ashby/kong; mid+ Canada tech roles=3 | 3 |
| GC AI | no | ashby | https://jobs.ashbyhq.com/gc-ai | 0 | skipped | Board live (28 jobs) but 0 Canada-eligible roles | 0 |
| ShyftLabs | no | lever | https://jobs.lever.co/shyftlabs | 7 | added | Live validated lever/shyftlabs; mid+ Canada tech roles=7 | 7 |
| AltaML | no | lever | https://jobs.lever.co/altaml | 3 | added | Live validated lever/altaml; mid+ Canada tech roles=3 | 3 |
| NerdWallet | no | ashby | https://jobs.ashbyhq.com/nerdwallet | 1 | added | Live validated ashby/nerdwallet; mid+ Canada tech roles=1 | 1 |
| Fellow | no | ashby | https://jobs.ashbyhq.com/fellowai | 1 | added | Live validated ashby/fellowai; mid+ Canada tech roles=1 | 1 |
| Reacher | no | ashby | https://jobs.ashbyhq.com/reacher | 0 | skipped | Board live (16 jobs) but 0 Canada-eligible roles | 0 |
| Super.com | no | ashby | https://jobs.ashbyhq.com/super.com | 3 | added | Live validated ashby/super.com; mid+ Canada tech roles=3 | 3 |
| Superhuman | no | ashby | https://jobs.ashbyhq.com/superhuman%20platform%20inc | 1 | added | Live validated ashby/superhuman platform inc; mid+ Canada tech roles=1 | 1 |
| Novara | no | lever | https://jobs.lever.co/novara | 1 | added | Live validated lever/novara; mid+ Canada tech roles=1 | 1 |
| Boson AI | no | lever | https://jobs.lever.co/bosonai | 2 | added | Live validated lever/bosonai; mid+ Canada tech roles=2 | 2 |
| Tali AI | no | lever | https://jobs.lever.co/tali-ai | 0 | skipped | 5 Canada-location jobs but 0 track-matched technical titles (non-eng roles) | 0 |
| Lime | no | ashby | https://jobs.ashbyhq.com/lime | 0 | skipped | Ashby board token lime → HTTP 404 | 0 |
| Canals | no | ashby | https://jobs.ashbyhq.com/canals | 1 | added | Live validated ashby/canals; mid+ Canada tech roles=1 | 1 |
| RAVL | no | lever | https://jobs.lever.co/ravl_io | 10 | added | Live validated lever/ravl_io; mid+ Canada tech roles=10 | 10 |
| H2 Analytics | no | ashby | https://jobs.ashbyhq.com/h2analytics | 1 | added | Live validated ashby/h2analytics; mid+ Canada tech roles=1 | 1 |
| Fig Financial | no | lever | https://jobs.lever.co/figfinancial | 2 | added | Live validated lever/figfinancial; mid+ Canada tech roles=2 | 2 |
| DuckDuckGo | no | ashby | https://jobs.ashbyhq.com/duck-duck-go | 0 | skipped | Board live (10 jobs) but 0 Canada-eligible roles | 0 |
| Kepler Communications | no | lever | https://jobs.lever.co/kepler | 0 | skipped | Only tech_ca hit is Software Engineering Intern (seniority-excluded); 0 mid+ tech Canada | 0 |
| Badge | no | lever | https://jobs.lever.co/badge-group | 1 | added | Live validated lever/badge-group; mid+ Canada tech roles=1 | 1 |
| SkyBox Labs | no | lever | https://jobs.lever.co/skyboxlabs | 0 | skipped | Board live (9 jobs) but 0 Canada-eligible roles | 0 |
| Saviynt | no | lever | https://jobs.lever.co/saviynt | 0 | skipped | Board live (58 jobs) but 0 Canada-eligible roles | 0 |
| Parallel Domain | no | lever | https://jobs.lever.co/paralleldomain | 2 | added | Live validated lever/paralleldomain; mid+ Canada tech roles=2 | 2 |
| Warner Music Group | no | lever | https://jobs.lever.co/wmg | 1 | added | Live validated lever/wmg; mid+ Canada tech roles=1 | 1 |
| Mythic | no | lever | https://jobs.lever.co/mythic-ai.com | 0 | skipped | Board live (27 jobs) but 0 Canada-eligible roles | 0 |
| Hive.co | no | ashby | https://jobs.ashbyhq.com/Hive.co | 1 | added | Live validated ashby/Hive.co; mid+ Canada tech roles=1 | 1 |
| Paires | no | ashby | https://jobs.ashbyhq.com/paires | 0 | skipped | Ashby board token paires → HTTP 404 | 0 |
| Leadership Connect | no | lever | https://jobs.lever.co/leadershipconnect | 1 | added | Live validated lever/leadershipconnect; mid+ Canada tech roles=1 | 1 |
| Nomic | no | ashby | https://jobs.ashbyhq.com/nomic | 0 | skipped | Board live with Canada signals but 0 track-matched technical titles; not previously configured | 0 |
| Jane App | no | ashby | https://jobs.ashbyhq.com/jane | 3 | added | Live validated ashby/jane; mid+ Canada tech roles=3 | 3 |
| Xsolla | no | lever | https://jobs.lever.co/xsolla | 8 | added | Live validated lever/xsolla; mid+ Canada tech roles=8 | 8 |
| Overstory | no | ashby | https://jobs.ashbyhq.com/overstory | 0 | skipped | Board live (6 jobs) but 0 Canada-eligible roles | 0 |
| SOVRA | no | ashby | https://jobs.ashbyhq.com/sovra | 3 | added | Live validated ashby/sovra; mid+ Canada tech roles=3 | 3 |
| Aduna Global | no | lever | https://jobs.lever.co/adunaglobal | 3 | added | Live validated lever/adunaglobal; mid+ Canada tech roles=3 | 3 |
| Wagmo | no | ashby | https://jobs.ashbyhq.com/wagmo | 1 | added | Live validated ashby/wagmo; mid+ Canada tech roles=1 | 1 |
| NimbleRx | no | lever | https://jobs.lever.co/nimblerx | 0 | skipped | Lever board returns 0 jobs (empty) | 0 |
| Boston Consulting Group (BCG X) | no | — | https://careers.bcg.com/ | 0 | skipped | Unsupported ATS (Phenom); no Greenhouse/Lever/Ashby/Workday guest board verified | 0 |
| Oliver Wyman | no | — | https://careers.marshmclennan.com/ | 0 | skipped | Unsupported ATS (Phenom via Marsh careers); no supported public board verified | 0 |
| McKinsey (QuantumBlack) | no | — | https://www.mckinsey.com/careers | 0 | skipped | Careers page timed out / no supported public ATS board verified | 0 |
| Bain & Company | no | — | https://www.bain.com/careers/ | 0 | skipped | No Greenhouse/Lever/Ashby/Workday guest board discovered from careers pages | 0 |
| Deloitte | no | — | — | 0 | skipped | No supported public ATS board verified (careers redirect only) | 0 |
| Accenture | no | — | — | 0 | skipped | Workday AccentureCareers live (≈1970 jobs) but 0 Canada-eligible tech roles after location classification; runtime cost unjustified | 0 |
| PwC | no | — | — | 0 | skipped | No supported public ATS board verified | 0 |
| EY | no | — | — | 0 | skipped | Unsupported ATS (SuccessFactors); not already in registry under EY | 0 |
| KPMG | no | — | — | 0 | skipped | Unsupported ATS (iCIMS); no supported adapter board | 0 |
| Slalom | no | — | — | 0 | skipped | No Greenhouse/Lever/Ashby/Workday board verified (careers SSL/errors) | 0 |
| Capgemini | no | — | — | 0 | skipped | No supported public ATS board discovered | 0 |
| CGI | no | — | — | 0 | skipped | Unsupported ATS (njoyn / bot-protected); no supported adapter | 0 |
| IBM Consulting | no | — | — | 0 | skipped | No supported public ATS board verified from careers search | 0 |
| Publicis Sapient | no | — | — | 0 | skipped | Lever tokens publicissapient/sapient 404; careers.publicissapient.com has no extractable supported board | 0 |
| National Bank | no | — | — | 0 | skipped | No Workday/Greenhouse/Lever/Ashby guest board verified | 0 |
| Desjardins | no | workday | https://desjardins.wd10.myworkdayjobs.com/Desjardins2 | 3 | added | Live validated workday/desjardins.wd10.myworkdayjobs.com/desjardins/Desjardins2; mid+ Canada tech roles=3 | 3 |
| Scotiabank | no | — | — | 0 | skipped | Unsupported ATS (SuccessFactors) | 0 |
| Equitable Bank | no | — | — | 0 | skipped | No supported public ATS board verified | 0 |
| Wealthsimple | yes (ashby/wealthsimple) | — | — | 0 | skipped | Already configured (ashby/wealthsimple); not duplicated | 0 |
| Aviva Canada | no | — | — | 0 | skipped | No supported public ATS board verified | 0 |
| Definity | no | — | — | 0 | skipped | Careers page present but no supported ATS board token verified | 0 |
| Co-operators | no | — | — | 0 | skipped | Unsupported ATS (Ultipro); no supported adapter | 0 |
| Wawanesa | no | — | — | 0 | skipped | Careers URL 404 / no supported board verified | 0 |
| Canada Life | no | — | — | 0 | skipped | Unsupported ATS (SuccessFactors) | 0 |
| Rogers | no | — | — | 0 | skipped | Unsupported ATS (SuccessFactors) | 0 |
| Bell | no | — | — | 0 | skipped | Unsupported ATS (Phenom) | 0 |
| Quebecor | no | — | — | 0 | skipped | Unsupported ATS (SmartRecruiters); no supported adapter | 0 |
| Loblaw | no | — | — | 0 | skipped | Workday myview/paradox_careers exists (~15k mostly retail); skipped to avoid runtime without meaningful tech yield | 0 |
| Canadian Tire | no | workday | https://canadiantirecorporation.wd3.myworkdayjobs.com/Enterprise_External_Careers_Site | 3 | added | Live validated workday/canadiantirecorporation.wd3.myworkdayjobs.com/canadiantirecorporation/Enterprise_External_Careers_Site; mid+ Canada tech roles=3 | 3 |
| Walmart Canada | no | — | — | 0 | skipped | Workday probe returned 422 for WalmartCanada; no verified accessible guest board | 0 |
| McDonald's Canada | no | — | — | 0 | skipped | No supported public ATS board verified | 0 |
| Hydro One | no | — | — | 0 | skipped | Unsupported ATS (SuccessFactors) | 0 |
| Enbridge | no | — | — | 0 | skipped | Workday enbridge_careers live (64 jobs) but 0 track-matched tech titles | 0 |
| CN Rail | no | — | — | 0 | skipped | No supported public ATS board verified | 0 |

## Added employers (detail)

| Employer | ATS / token | Jobs fetched | Mid+ tech×Canada |
|---|---|---:|---:|
| Aduna Global | `lever/adunaglobal` | 24 | 3 |
| AltaML | `lever/altaml` | 5 | 3 |
| Badge | `lever/badge-group` | 3 | 1 |
| Boson AI | `lever/bosonai` | 11 | 2 |
| Canadian Tire | `workday/canadiantirecorporation.wd3.myworkdayjobs.com/canadiantirecorporation/Enterprise_External_Careers_Site` | 128 | 3 |
| Canals | `ashby/canals` | 20 | 1 |
| Desjardins | `workday/desjardins.wd10.myworkdayjobs.com/desjardins/Desjardins2` | 415 | 3 |
| Fellow | `ashby/fellowai` | 5 | 1 |
| Fig Financial | `lever/figfinancial` | 4 | 2 |
| H2 Analytics | `ashby/h2analytics` | 2 | 1 |
| Hive.co | `ashby/Hive.co` | 1 | 1 |
| Jane App | `ashby/jane` | 27 | 3 |
| Kong | `ashby/kong` | 116 | 3 |
| Leadership Connect | `lever/leadershipconnect` | 3 | 1 |
| NerdWallet | `ashby/nerdwallet` | 29 | 1 |
| Novara | `lever/novara` | 6 | 1 |
| Parallel Domain | `lever/paralleldomain` | 8 | 2 |
| RAVL | `lever/ravl_io` | 21 | 10 |
| SOVRA | `ashby/sovra` | 12 | 3 |
| ShyftLabs | `lever/shyftlabs` | 27 | 7 |
| Super.com | `ashby/super.com` | 12 | 3 |
| Superhuman | `ashby/superhuman platform inc` | 71 | 1 |
| Terminal | `ashby/terminal` | 7 | 2 |
| Wagmo | `ashby/wagmo` | 9 | 1 |
| Warner Music Group | `lever/wmg` | 30 | 1 |
| Xsolla | `lever/xsolla` | 186 | 8 |

## Deployment action (manual — not performed)

1. Commit config + audit + regression test (this change set).
2. On the machine/environment that builds the public dataset: `githired discover` (or targeted discover for the 26) → enrich → rank → `scripts/export_public_shortlist.py` / `scripts/export_api_snapshot.py` as usual.
3. Smoke-check public/API cards for new employers (RAVL, ShyftLabs, Jane App, Xsolla, Desjardins, Canadian Tire).
4. Deploy only after that export passes existing QA — **no automatic deploy from this expansion**.

## Notes

- Wealthsimple was already in `config/companies.yaml` (`ashby/wealthsimple`) and was left unchanged.
- Board tokens were never invented: Ashby/Lever tokens came from CSV URLs; Workday host/tenant/site came from live CXS probes + careers-page detection.
- Validation date in company notes: 2026-11-15.

