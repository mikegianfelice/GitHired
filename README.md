<p align="center">
  <img src="assets/readme/hero.svg" alt="GitHired — automated job discovery for engineers on your machine." width="100%">
</p>

<p align="center">
  <a href="https://github.com/mikegianfelice/GitHired/actions/workflows/ci.yml"><img src="https://github.com/mikegianfelice/GitHired/actions/workflows/ci.yml/badge.svg" alt="CI" height="20"></a>
  &nbsp;
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2A9D8F?style=flat" alt="MIT license" height="20"></a>
</p>

<p align="center">
  <b>GitHired</b> — automated job discovery and ranking for software, AI, data,<br>
  forward-deployed, and cloud engineers targeting the <b>Canada developer market</b>.
</p>

<p align="center">
  <a href="#who-this-is-for"><b>Who this is for</b></a>
  &nbsp;&nbsp;&nbsp;
  <a href="#what-it-does"><b>What it does</b></a>
  &nbsp;&nbsp;&nbsp;
  <a href="#quick-start"><b>Quick start</b></a>
  &nbsp;&nbsp;&nbsp;
  <a href="#canada-market-defaults"><b>Canada defaults</b></a>
  &nbsp;&nbsp;&nbsp;
  <a href="SETUP.md"><b>Setup guide</b></a>
  &nbsp;&nbsp;&nbsp;
  <a href="docs/discovery.md"><b>Discovery docs</b></a>
</p>

---

## Who this is for

Built by **[Michael Gianfelice](https://www.linkedin.com/in/michaelgianfelice/)** — Toronto-based technical consultant and engineer who builds data systems and AI applications (currently at Intact).

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
|---|---|
| **`jobseek` CLI** | Headless discovery from Greenhouse / Lever / Ashby boards, optional LinkedIn index/alerts, Canada-remote hard filters, LLM ranking, daily digest |
| **Cursor / agent workflows** | Profile setup, fit evaluation, tailored CV + cover letter (`/apply`), interview prep, outcome tracking |
| **Company registry** | Configurable ATS boards in [`config/companies.yaml`](config/companies.yaml) tuned for eng hiring |

**Core promise:** stop manually refreshing LinkedIn and career pages. Run discovery once a day, get the top Canada-relevant engineering roles scored against *your* profile.

Application materials are never auto-submitted. `jobseek prepare` briefs you; `/apply` drafts only after you confirm.

---

## Canada market defaults

GitHired ships configured for **Canada-remote and Canada-eligible** engineering hiring — not the European demo portals from the upstream template.

- Preferred locations: Canada remote / Remote Canada / hybrid Canada  
- US employers: allowed **only** when the posting explicitly evidences Canada, Canadian applicants, worldwide, or equivalent  
- US-only remote: rejected by deterministic filters ([`jobseek/filters/hard.py`](jobseek/filters/hard.py))  
- Target titles: AI / Applied AI / FDE / Senior–Staff Data / AI Solutions Architect (+ ML aliases) in [`config/search.yaml`](config/search.yaml) — extend for SWE / cloud as needed  
- Salary floors (configurable): CAD / USD in `config/search.yaml`  
- Danish job-board CLIs remain installed but **disabled** by default  

Eligibility is never invented: if Canada is not evidenced in the posting, the role is flagged or rejected per your config.

---

## Quick start

### Prerequisites

| | |
|---|---|
| **Python 3.10+** | Required for `jobseek` (3.11+ recommended) |
| **Cursor** *(recommended)* | Agent workflows via thin skills in `.cursor/` |
| **LLM API key** | Anthropic and/or OpenAI-compatible — for real ranking (heuristic fallback exists for dry runs) |
| **Bun** *(optional)* | Only if you use portal CLIs under `.agents/skills/` |
| **LaTeX** *(optional)* | Only if you use `/apply` CV/cover letter compile |

### 1. Clone

```bash
git clone https://github.com/mikegianfelice/GitHired.git
cd GitHired
```

Keep personal data in a **private** clone if you write profile details into tracked files (`CLAUDE.md`, skill profiles). See [SETUP.md](SETUP.md).

### 2. Install the discovery CLI

```bash
python3 -m pip install -e ".[dev]"
cp .env.example .env   # add ANTHROPIC_API_KEY / OPENAI_API_KEY, SMTP or Resend
```

Edit:

- [`config/profile.yaml`](config/profile.yaml) — your skills and authorization  
- [`config/search.yaml`](config/search.yaml) — titles, salary floors, sources  
- [`config/companies.yaml`](config/companies.yaml) — ATS board tokens to watch  

### 3. Discover, rank, digest

```bash
jobseek discover --import-tracker
jobseek rank --limit 25
jobseek digest

# Full daily loop (cron-friendly)
jobseek run-daily --email
```

Details: [docs/discovery.md](docs/discovery.md).

### 4. Apply with approval (agent)

Fill your narrative profile (`CLAUDE.md` / `/setup`), then:

```text
/apply <job-url>
```

Or from a scored job:

```bash
jobseek prepare <job_id>   # briefing only — does not draft or submit
```

Then confirm drafting when the agent asks.

---

## Commands at a glance

### `jobseek` (headless)

| Command | What it does |
|---|---|
| `discover` | Pull ATS boards (+ optional LinkedIn index); upsert SQLite |
| `rank` | Hard-filter then LLM-score new jobs |
| `digest` / `email-digest` | Top-N shortlist; optional email |
| `run-daily` | discover → rank → digest → email |
| `prepare` | Briefing only; no auto-draft/submit |
| `import-alerts` | Import LinkedIn saved-alert HTML/JSON |
| `import-seen` | Migrate legacy `seen_jobs.json` |

### Agent workflows (Cursor / Claude)

| Command | What it does |
|---|---|
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

1. Public **Greenhouse / Lever / Ashby** APIs via the company registry  
2. LinkedIn via **search-index** (`SERPAPI_KEY`) and/or **saved-alert imports** (`jobseek import-alerts`)  

LinkedIn guest scraping (`.agents/skills/linkedin-search`) is **off** for scheduled runs (`sources.linkedin_guest: false`) because automated access conflicts with LinkedIn’s Terms of Service. Use it only for low-volume personal interactive sessions if you accept that risk.

---

## File structure (high level)

```
GitHired/
├── jobseek/                 # Discovery, filters, ranking, digest CLI
├── config/                  # companies.yaml, search.yaml, profile.yaml
├── docs/discovery.md        # Architecture + Canada eligibility notes
├── .cursor/                 # Cursor rules + thin skills
├── .claude/                 # Canonical agent workflows (apply, setup, …)
├── .agents/skills/          # Optional portal CLIs (LinkedIn, freehire, …)
├── cv/ · cover_letters/     # LaTeX templates for /apply
├── tools/                   # Shared helpers (job_key, posting_guard, …)
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

<p align="center">
  <img src="assets/mascot/pip_flight_loop.gif" alt="Courier bird mascot" width="120"><br>
  <sub>Good luck out there.</sub>
</p>
