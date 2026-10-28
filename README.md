![GitHired — automated job discovery for engineers on your machine.](assets/readme/hero.svg)

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


| Layer                        | Purpose                                                                                                                                          |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `githired` **CLI** (`jobseek` alias) | Headless discovery from Greenhouse / Lever / Ashby, LinkedIn free/SerpAPI/alerts, Canada hard filters, deterministic ranking (+ optional LLM), digests |
| **Cursor / agent workflows** | Profile setup, fit evaluation, tailored CV + cover letter (`/apply`), interview prep, outcome tracking |
| **Company registry** | ATS boards in [`config/companies.yaml`](config/companies.yaml), validated into SQLite |


**Core promise:** stop manually refreshing LinkedIn and career pages. Run discovery once a day, get the top Canada-relevant engineering roles scored against *your* profile — **no API key required** for discovery and Stage-1 ranking.

Application materials are never auto-submitted. `githired prepare` briefs you; `/apply` drafts only after you confirm.

---



## Canada market defaults

GitHired ships configured for **Canada-remote and Canada-eligible** engineering hiring — not the European demo portals from the upstream template.

- Preferred locations: Canada remote / Remote Canada / hybrid Canada  
- US employers: allowed **only** when the posting explicitly evidences Canada, Canadian applicants, worldwide, or equivalent  
- US-only remote: rejected by deterministic filters (`[jobseek/filters/hard.py](jobseek/filters/hard.py)`)  
- Engineering **tracks** (software, AI, ML, data, platform, cloud, DevOps/SRE, FDE) in [`config/search.yaml`](config/search.yaml)  
- Location modes: remote Canada, province remote, hybrid, on-site cities  
- Salary floors (configurable): CAD / USD in `config/search.yaml`  
- Danish job-board CLIs remain installed but **disabled** by default for Canada ATS discovery

Eligibility is never invented: if Canada is not evidenced in the posting, the role is flagged as unknown or rejected per your config.

---



## Quick start



### Prerequisites


|                            |                                                                                                |
| -------------------------- | ---------------------------------------------------------------------------------------------- |
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

### 2. Install and configure

```bash
python3 -m pip install -e ".[dev]"
githired setup --non-interactive   # or: githired setup
githired doctor
```

Optional: copy `.env.example` → `.env` for LLM / SerpAPI / email. None are required for discover + deterministic rank.

Edit as needed:

- [`config/profile.yaml`](config/profile.yaml) — skills and authorization  
- [`config/search.yaml`](config/search.yaml) — tracks, location modes, salary, sources  
- [`config/companies.yaml`](config/companies.yaml) — ATS board tokens



### 3. Discover, rank, shortlist

```bash
githired discover
githired rank --limit 25
githired jobs --min-score 60
githired digest

# Full daily loop (cron-friendly)
githired run-daily
```

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

Then confirm drafting when the agent asks.

---



## Commands at a glance



### `githired` (headless; `jobseek` alias)


| Command | What it does |
| ------- | ------------ |
| `setup` | Interactive/non-interactive config + legacy migrate |
| `doctor` / `sources` | Environment and company/source health |
| `discover` | ATS boards + LinkedIn (free/SerpAPI/alerts); SQLite upsert |
| `rank` | Deterministic Stage-1 scores; `--llm` for optional Stage-2 |
| `jobs` | Deduplicated shortlist from SQLite |
| `digest` / `email-digest` | Top-N shortlist; optional email |
| `run-daily` | discover → rank → digest → email |
| `prepare` | Briefing only; no auto-draft/submit |
| `migrate` / `import-seen` / `import-alerts` | Legacy + LinkedIn alert import |
| `sync-application` | Record an application into SQLite |




### Agent workflows (Cursor / Claude)


| Command      | What it does                                               |
| ------------ | ---------------------------------------------------------- |
| `/setup`     | Build profile from documents, CV, or interview             |
| `/scrape`    | Portal CLI search (legacy / interactive)                   |
| `/rank`      | Agent triage of scraped jobs                               |
| `/apply`     | Fit eval + tailored CV/cover letter (asks before drafting) |
| `/interview` | Stage-specific prep + mock interview                       |
| `/outcome`   | Track results and archive materials                        |


Full agent command list and LaTeX details live in [SETUP.md](SETUP.md) and `[.claude/commands/](.claude/commands/)`.

---



## LinkedIn and career boards

**Scheduled discovery prefers:**

1. Public **Greenhouse / Lever / Ashby** APIs via the company registry (SQLite-validated)
2. LinkedIn via **free search-index** (best-effort), optional **SerpAPI** (`SERPAPI_KEY`), and/or **saved-alert imports** (`githired import-alerts`)

Missing SerpAPI is a warning, not a discover failure. LinkedIn guest scraping (`.agents/skills/linkedin-search`) is **off** for scheduled runs (`sources.linkedin_guest: false`) because automated access conflicts with LinkedIn’s Terms of Service.

---



## File structure (high level)

```
GitHired/
├── jobseek/                 # Discovery, filters, ranking, digest CLI (githired)
├── config/                  # companies.yaml, search.yaml, profile.yaml
├── data/jobseek.db          # Local SQLite (gitignored; created on first run)
├── docs/discovery.md        # Architecture + Canada eligibility notes
├── .cursor/                 # Cursor rules + thin skills → githired
├── .claude/                 # Canonical agent workflows (apply, setup, …)
├── .agents/skills/          # Optional portal CLIs (legacy / interactive)
├── cv/ · cover_letters/     # LaTeX templates for /apply
├── tools/                   # Legacy agent helpers (rank_state, scrape_state, …)
└── SETUP.md
```

---



## Security

Job postings are **untrusted input**. Agent workflows strip hidden text and refuse to follow instructions embedded in ads ([SECURITY.md](SECURITY.md)). Keep `.env` and personal trackers out of git (already gitignored).

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