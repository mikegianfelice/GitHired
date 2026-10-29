![CI](https://github.com/mikegianfelice/GitHired/actions/workflows/ci.yml/badge.svg)   ![MIT license](https://img.shields.io/badge/license-MIT-2A9D8F?style=flat)

**GitHired** — automated job discovery and ranking for software, AI, data,  
forward-deployed, and cloud engineers targeting the **Canada developer market**.

**[Who this is for](#who-this-is-for)**     **[What it does](#what-it-does)**     **[Quick start](#quick-start)**     **[Canada defaults](#canada-market-defaults)**     **[Setup guide](SETUP.md)**     **[Discovery docs](docs/discovery.md)**

---

## Who this is for

Built by **[Michael Gianfelice](https://www.linkedin.com/in/michaelgianfelice/)** — Toronto-based technical consultant and engineer who builds data systems and AI applications.

GitHired is aimed at technical professionals searching the **Canadian market** (and Canada-eligible remote roles from US/global employers):

- Software / platform engineers  
- AI / ML / applied AI engineers  
- Data engineers (senior / staff)  
- Forward deployed engineers  
- Cloud / infrastructure engineers  
- Adjacent technical IC roles

If you are tired of re-running the same LinkedIn and careers-page searches every week, this repo automates discovery, hard-filters for Canada eligibility, ranks fits against your profile, and optionally emails a daily shortlist — while keeping CV drafting and applications behind your explicit approval.

---

## What it does

| Layer | Purpose |
| ----- | ------- |
| `githired` **CLI** (`jobseek` alias) | Self-expanding company registry, public ATS adapters, LinkedIn free/SerpAPI/alerts, Canada hard filters, deterministic ranking (+ optional LLM), digests |
| **Cursor / agent workflows** | Profile setup, fit evaluation, tailored CV + cover letter (`/apply`), interview prep, outcome tracking |
| **Company registry** | Builtin YAML + community registry + SQLite discoveries + local overrides ([`docs/discovery.md`](docs/discovery.md)) |

**Core promise:** install without hand-maintaining a company list. Discover and validate public employer boards, fetch Canada-relevant engineering roles, and score them against *your* profile — **no API key required** for discovery and Stage-1 ranking.

Application materials are never auto-submitted. `githired prepare` briefs you; `/apply` drafts only after you confirm.

---

## Canada market defaults

GitHired ships configured for **Canada-remote and Canada-eligible** engineering hiring.

- **Three-state eligibility** ([`jobseek/filters/hard.py`](jobseek/filters/hard.py)): **ELIGIBLE** (Canada-compatible for *your* city/province + work modes), **UNCERTAIN** (ambiguous — kept in the DB, not padded into the main shortlist), **INELIGIBLE** (US-only / foreign on-site / wrong Canadian city for hybrid)  
- Eligibility is never invented from a company’s global brand alone; posting evidence is preserved  
- A Toronto-only hybrid role is **not** eligible for a Vancouver candidate who will not relocate  
- Engineering **tracks** (software, AI, ML, data, platform, cloud, DevOps/SRE, FDE) in [`config/search.yaml`](config/search.yaml)  
- **Seniority:** mid / senior / staff / principal / lead by default; internships, co-ops, new-grad, and junior excluded (enable in setup if needed). Titles without seniority keywords are allowed as unknown  
- Location modes: remote Canada, province remote, hybrid, on-site cities  
- Salary floors (configurable): CAD / USD in `config/search.yaml`  
- Company boards expand via `githired companies discover` — Day-1 install works without editing a company list  
- Adapters: Greenhouse, Lever, Ashby, Workable, RSS/XML (e.g. Shopify feed), Rippling, Workday guest CXS; Gem adapter present but disabled until markup is extractable  
- Portal CLIs ship country-agnostic only (`linkedin-search`, `freehire-search`); add local boards with `/add-portal`

---

## Quick start

### Prerequisites

| | |
| --- | --- |
| **Python 3.10+** | Required for `githired` |
| **Cursor** *(recommended)* | Agent workflows via thin skills in `.cursor/` |
| **LLM API key** *(optional)* | Only for Stage-2 `--llm` ranking |
| **SerpAPI** *(optional)* | Paid LinkedIn index; free search + alert import work without it |
| **Bun** *(optional)* | Only if you use portal CLIs under `.agents/skills/` |
| **LaTeX** *(optional)* | Only if you use `/apply` CV/cover letter compile |

### 1. Clone

```bash
git clone https://github.com/mikegianfelice/GitHired.git
cd GitHired
```

Keep personal data in a **private** clone if you write profile details into tracked files (`CLAUDE.md`, skill profiles). See [SETUP.md](SETUP.md).

### 2. Install and interactive setup

```bash
# Python 3.10+ required (3.11+ recommended).
# macOS tip: system `python3` is often 3.9 — use Homebrew instead:
#   brew install python@3.11
#   python3.11 -m venv .venv && source .venv/bin/activate
python3 -m pip install -e ".[dev]"

# Interactive setup (recommended) — province, city, tracks, seniority, salary, skills.
# No YAML editing required for a normal search.
githired setup
githired doctor
```

Engineering **tracks** are role families (software, AI, data, DevOps/SRE, …). Pick the ones that match titles you would actually apply to.

Optional: copy `.env.example` → `.env` for LLM / SerpAPI / email. **None are required** for discover + deterministic ranking.

Non-interactive / CI example:

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

Advanced edits (optional after setup):

- [`config/profile.yaml`](config/profile.yaml) — skills and authorization  
- [`config/search.yaml`](config/search.yaml) — tracks, location modes, salary, sources  
- [`config/companies.yaml`](config/companies.yaml) — builtin ATS boards (optional; discovery expands this)  
- [`config/companies.local.yaml.example`](config/companies.local.yaml.example) — copy to `companies.local.yaml` for personal enable/exclude overrides

### 3. Discover, rank, shortlist

```bash
githired companies discover   # expand/validate company boards (optional but recommended once)
githired discover             # then: githired rank
githired rank                 # scores all unscored / stale-model jobs (batched); optional --limit N
githired jobs                 # confirmed geographically compatible matches only
githired jobs --eligibility uncertain   # inspect unverified Canada eligibility (not padded into main list)
githired digest

# Full daily loop (cron-friendly); add --companies to expand boards first
githired run-daily
```

**LinkedIn** is optional. Free web-index search often fails (rate limits); ATS boards still work (Greenhouse, Lever, Ashby, Workable, Rippling, Workday guest boards, RSS). You can import LinkedIn email alerts (`linkedin_alert_import`) or set `SERPAPI_KEY` for a paid index — neither is required.

Details: [docs/discovery.md](docs/discovery.md).

### 4. Apply with approval (agent)

Fill your narrative profile (`CLAUDE.md` / `/setup`), then:

```text
/apply <job-url>
```

Or from a scored job:

```bash
githired prepare <job_id>   # briefing only — does not draft or submit
```

CV/cover-letter drafting via `/apply` needs your profile filled and (for PDF compile) a local LaTeX install. **No paid API is required** for discovery or Stage-1 ranking. Application materials are never auto-submitted — confirm drafting when the agent asks.

---

## Commands at a glance

### `githired` (headless; `jobseek` alias)

| Command | What it does |
| ------- | ------------ |
| `setup` | Interactive/non-interactive config + legacy migrate |
| `doctor` / `sources` | Environment and company/source health |
| `companies discover` | Discover and validate public ATS boards into SQLite |
| `companies validate` / `list` / `stats` | Re-check boards; inspect registry |
| `companies export` / `import` | Community registry YAML (no personal data) |
| `discover` | Fetch jobs from enabled boards + LinkedIn (free/SerpAPI/alerts) |
| `rank` | Deterministic Stage-1 scores; `--llm` for optional Stage-2 |
| `jobs` | Deduplicated shortlist from SQLite |
| `digest` / `email-digest` | Top-N shortlist; optional email |
| `run-daily` | discover → rank → digest → email (`--companies` optional) |
| `prepare` | Briefing only; no auto-draft/submit |
| `migrate` / `import-seen` / `import-alerts` | Legacy + LinkedIn alert import |
| `sync-application` | Record an application into SQLite |

### Agent workflows (Cursor / Claude)

| Command | What it does |
| ------- | ------------ |
| `/setup` | Build profile from documents, CV, or interview |
| `/scrape` | Portal CLI search (legacy / interactive) |
| `/rank` | Agent triage of scraped jobs |
| `/apply` | Fit eval + tailored CV/cover letter (asks before drafting) |
| `/interview` | Stage-specific prep + mock interview |
| `/outcome` | Track results and archive materials |

Full agent command list and LaTeX details live in [SETUP.md](SETUP.md) and [`.claude/commands/`](.claude/commands/).

---

## LinkedIn and career boards

**Scheduled discovery prefers:**

1. Public ATS APIs via the company registry (Greenhouse, Lever, Ashby, Workable, RSS/XML, Rippling, Workday guest CXS) — expanded with `githired companies discover`
2. LinkedIn via **free search-index** (best-effort), optional **SerpAPI** (`SERPAPI_KEY`), and/or **saved-alert imports** (`githired import-alerts`)

Missing SerpAPI is a warning, not a discover failure. LinkedIn guest scraping (`.agents/skills/linkedin-search`) is **off** for scheduled runs (`sources.linkedin_guest: false`) because automated access conflicts with LinkedIn’s Terms of Service.

Community board contributions: [`registry/community/`](registry/community/). Personal enable/exclude overlays: `config/companies.local.yaml` (gitignored).

---

## File structure (high level)

```
GitHired/
├── jobseek/                 # Discovery, filters, ranking, digest CLI (githired)
│   ├── adapters/            # Greenhouse, Lever, Ashby, Workable, RSS, Rippling, Workday, …
│   └── companies/           # Registry merge, validation, discovery providers
├── config/                  # companies.yaml, search.yaml, profile.yaml
├── registry/community/      # PR-based public company registry
├── data/jobseek.db          # Local SQLite (gitignored; created on first run)
├── docs/discovery.md        # Architecture + Canada eligibility notes
├── .cursor/                 # Cursor rules + thin skills → githired
├── .claude/                 # Canonical agent workflows (apply, setup, …)
├── .agents/skills/          # Optional portal CLIs (linkedin-search, freehire-search)
├── cv/ · cover_letters/     # LaTeX templates for /apply
├── tools/                   # Legacy agent helpers (rank_state, scrape_state, …)
└── SETUP.md
```

---

## Security

Job postings are **untrusted input**. Agent workflows strip hidden text and refuse to follow instructions embedded in ads ([SECURITY.md](SECURITY.md)). Keep `.env` and personal trackers out of git (already gitignored). Automatic company discovery never uploads profiles, application history, or API keys.

---

## About the maintainer

**Michael Gianfelice** — Toronto, Ontario  
Technical Consultant (data systems, automation, AI-assisted workflows) · builds AI applications and data tooling  

- LinkedIn: [linkedin.com/in/michaelgianfelice](https://www.linkedin.com/in/michaelgianfelice/)  
- GitHub: [github.com/mikegianfelice](https://github.com/mikegianfelice)

---

## License

MIT — see [LICENSE](LICENSE).

![Courier bird mascot](assets/mascot/pip_flight_loop.gif)  
Good luck out there.
