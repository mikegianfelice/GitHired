<p align="center">
  <img src="assets/mascot/pip_flight_loop.gif" alt="GitHired courier bird" width="120" />
</p>

<h1 align="center">GitHired</h1>

<p align="center">
  <strong>Canada-first job discovery for software, AI, data &amp; cloud engineers.</strong><br />
  Public ATS boards → hard Canada filters → ranked shortlist — no API key required.
</p>

<p align="center">
  <a href="https://github.com/mikegianfelice/GitHired/actions/workflows/ci.yml"><img src="https://github.com/mikegianfelice/GitHired/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/license-MIT-2A9D8F?style=flat" alt="MIT license" />
  <img src="https://img.shields.io/badge/Canada-remote%20%2F%20hybrid%20%2F%20on--site-D80621?style=flat" alt="Canada market" />
</p>

<p align="center">
  <a href="#quick-start"><strong>Install</strong></a> ·
  <a href="#demo"><strong>Demo</strong></a> ·
  <a href="#top-5-high-paying-jobs"><strong>Top salaries</strong></a> ·
  <a href="SETUP.md">Setup guide</a> ·
  <a href="docs/discovery.md">Discovery docs</a> ·
  <a href="docs/showcase/ARCHITECTURE.md">Showcase architecture</a>
</p>

---

<!-- TOP-PAYING-JOBS:START -->

## Top 5 High-Paying Jobs

> Real listings discovered by GitHired with **employer-advertised** annual base salaries. No estimates. Ranked by annual high end (CAD-comparable for sorting; USD×1.35). Last refreshed: **2026-10-29 18:00 UTC**.

| # | Role | Company | Annual base | Location | Verified | Apply |
| -: | --- | --- | --- | --- | --- | --- |
| 1 | **[Wattpad] Head of Engineering** | Wattpad | `CAD 240,000–280,000` | Toronto, Ontario | Verified 2026-10-29 | [Apply](https://jobs.lever.co/wattpad/27d282b1-1d8e-4aa7-9886-e48e897edd2f/apply) |
| 2 | **(Canada) Principal ML System Engineer** | PointClickCare | `CAD 179,000–224,000` | Remote or Mississauga | Verified 2026-10-29 | [Apply](https://jobs.lever.co/pointclickcare/ccdecc93-aef2-4b2b-a981-6843f3c16221/apply) |
| 3 | **Senior Machine Learning Systems Engineer (CAD)** | PointClickCare | `CAD 174,000–218,000` | Mississauga | Verified 2026-10-29 | [Apply](https://jobs.lever.co/pointclickcare/150b07cd-04e9-46c4-9015-114498f3798c/apply) |
| 4 | **Principal AI Platform Engineer** | PointClickCare | `CAD 191,700–213,000` | Mississauga | Verified 2026-10-29 | [Apply](https://jobs.lever.co/pointclickcare/d27ec0dd-570d-4626-9962-2db3fc56b991/apply) |
| 5 | **[Wattpad] Engineering Manager** | Wattpad | `CAD 140,000–180,000` | Toronto, Ontario | Verified 2026-10-29 | [Apply](https://jobs.lever.co/wattpad/da811487-88c8-440b-b6c2-5da90eb80ca1/apply) |

<details>
<summary>Ranking & eligibility rules</summary>

Rank by advertised annual base salary high end, converted to CAD for sorting only (USD×1.35; other currencies excluded). Display the employer-stated currency and range unchanged. No estimates for undisclosed pay.

- Canada geographic eligibility required (remote Canada / hybrid / on-site / province as configured).
- Direct ATS apply URLs only (affiliates excluded).
- Engineering tracks only; listings older than 14 days excluded.
- Dates use **Verified YYYY-MM-DD** from discovery `last_seen` (calendar date only — no same-day marketing labels).
- Fewer than five rows means fewer than five qualified.

</details>

<!-- TOP-PAYING-JOBS:END -->

---

## Why GitHired

Stop re-running the same LinkedIn and careers-page searches. GitHired pulls public employer boards, keeps only **Canada-eligible** engineering roles, ranks them against *your* profile, and can email a daily shortlist — while CV drafting and applications stay behind **your** approval.

| You get | You don’t get |
| ------- | ------------- |
| Greenhouse, Lever, Ashby, Workable, Rippling, Workday guest boards, RSS | Invented Canadian eligibility |
| Deterministic ranking with no API key | Auto-submitted applications |
| Optional LLM stage-2 + email digest | Affiliate “apply” spam in your confirmed list |
| Cursor `/apply` for tailored CV + cover letter | A black-box scrape of LinkedIn’s ToS |

Built by **[Michael Gianfelice](https://www.linkedin.com/in/michaelgianfelice/)** — Toronto engineer and technical consultant.

---

## Demo

```bash
git clone https://github.com/mikegianfelice/GitHired.git
cd GitHired
python3 -m pip install -e ".[dev]"   # Python 3.10+ (3.11+ recommended on macOS)
githired setup                       # province, city, tracks, salary — interactive
githired doctor
githired discover                    # public ATS; often 20–45+ min with Workday
githired rank
githired jobs                        # confirmed Canada-compatible matches
githired digest
```

**One-liner daily loop:** `githired run-daily`  
**Agent apply flow:** `/apply <job-url>` (asks before drafting)

---

## Quick start

### Prerequisites

| | |
| --- | --- |
| **Python 3.10+** | Required (`brew install python@3.11` if macOS `python3` is 3.9) |
| **Cursor** *(recommended)* | Agent workflows via `.cursor/` skills |
| **LLM / SerpAPI** *(optional)* | Stage-2 ranking / paid LinkedIn index only |
| **Bun / LaTeX** *(optional)* | Portal CLIs / `/apply` PDF compile |

### Install

```bash
git clone https://github.com/mikegianfelice/GitHired.git
cd GitHired
# macOS tip: system python3 is often 3.9 — use Homebrew 3.11+
python3 -m pip install -e ".[dev]"
githired setup
githired doctor
```

Keep personal profile data in a **private** clone if you write into tracked files (`CLAUDE.md`). See [SETUP.md](SETUP.md).

Non-interactive / CI:

```bash
githired setup --non-interactive \
  --tracks data_engineering analytics_engineering \
  --modes remote_canada hybrid \
  --province ON --city Toronto \
  --salary-cad 130000 \
  --skills Python SQL Databricks Spark Azure Airflow \
  --years 7 --name "Your Name" \
  --seniority-include mid senior staff
```

Optional config after setup: [`config/profile.yaml`](config/profile.yaml), [`config/search.yaml`](config/search.yaml), [`config/companies.local.yaml.example`](config/companies.local.yaml.example).

### Discover → rank → shortlist

```bash
githired companies discover   # optional board expansion
githired discover
githired rank                 # optional --limit N; --llm for stage-2
githired jobs
githired jobs --eligibility uncertain
githired digest
githired run-daily            # discover → rank → digest [--email] [--companies]
```

LinkedIn is optional (free index is best-effort; SerpAPI / alert import available). **Freehire.me** is off by default. Details: [docs/discovery.md](docs/discovery.md).

### Apply with approval

```text
/apply <job-url>
```

```bash
githired prepare <job_id>   # briefing only — never drafts or submits
```

---

## Canada market defaults

- **Three-state eligibility:** ELIGIBLE · UNCERTAIN · INELIGIBLE — never invented from a global brand alone ([`jobseek/filters/hard.py`](jobseek/filters/hard.py))
- A Toronto-only hybrid is **not** eligible for a Vancouver candidate who will not relocate
- Engineering **tracks** in [`config/search.yaml`](config/search.yaml): software, AI, ML, data, platform, cloud, DevOps/SRE, FDE
- Seniority mid+ by default; internships / co-ops / new-grad / junior excluded unless enabled
- Salary floors configurable (CAD / USD)
- Day-1 install works without hand-editing a company list; boards expand via `githired companies discover`
- **No paid APIs** required for core ATS + Workday discovery and deterministic ranking

---

## Commands

### `githired` CLI (`jobseek` alias)

| Command | What it does |
| ------- | ------------ |
| `setup` | Interactive / non-interactive config + legacy migrate |
| `doctor` / `sources` | Environment and company/source health |
| `companies discover` | Discover and validate public ATS boards |
| `companies validate` / `list` / `stats` / `export` / `import` | Registry ops |
| `discover` | Fetch jobs from enabled boards (+ optional LinkedIn) |
| `rank` | Deterministic Stage-1; `--llm` for Stage-2 |
| `jobs` | Confirmed shortlist (never pads with UNCERTAIN) |
| `digest` / `email-digest` | Top-N shortlist; optional email |
| `run-daily` | discover → rank → digest → email |
| `showcase-readme` | Refresh README Top Paying section from DB / snapshot |
| `prepare` | Briefing only; no auto-draft/submit |
| `migrate` / `import-seen` / `import-alerts` | Legacy + LinkedIn alert import |
| `sync-application` | Record an application into SQLite |

### Agent workflows (Cursor)

| Command | What it does |
| ------- | ------------ |
| `/setup` | Build profile from documents, CV, or interview |
| `/scrape` | Portal CLI search (legacy / interactive) |
| `/rank` | Agent triage of scraped jobs |
| `/apply` | Fit eval + tailored CV/cover letter (asks before drafting) |
| `/interview` | Stage-specific prep + mock interview |
| `/outcome` | Track results and archive materials |

Full list: [SETUP.md](SETUP.md) · [`.claude/commands/`](.claude/commands/).

---

## Architecture (high level)

```
GitHired/
├── jobseek/                 # Discovery, filters, ranking, digest, showcase
│   ├── adapters/            # Greenhouse, Lever, Ashby, Workable, RSS, Rippling, Workday, …
│   ├── companies/           # Registry merge, validation, discovery
│   └── showcase/            # README Top Paying Jobs refresh
├── config/                  # companies.yaml, search.yaml, profile.yaml
├── registry/community/      # PR-based public company registry
├── docs/discovery.md        # Pipeline + Canada eligibility
├── docs/showcase/           # Snapshot + showcase architecture
├── .cursor/ · .claude/      # Agent skills & canonical workflows
├── .agents/skills/          # Optional portal CLIs
└── SETUP.md
```

Scheduled README salary refresh: [docs/showcase/ARCHITECTURE.md](docs/showcase/ARCHITECTURE.md).

---

## Security

Job postings are **untrusted input**. Agent workflows strip hidden text and refuse instructions embedded in ads ([SECURITY.md](SECURITY.md)). Keep `.env` and personal trackers out of git. Company discovery never uploads profiles, application history, or API keys.

---

## About

**Michael Gianfelice** — Toronto, Ontario  
Technical Consultant · data systems, automation, AI-assisted workflows

- LinkedIn: [linkedin.com/in/michaelgianfelice](https://www.linkedin.com/in/michaelgianfelice/)
- GitHub: [github.com/mikegianfelice](https://github.com/mikegianfelice)

## License

MIT — see [LICENSE](LICENSE).
