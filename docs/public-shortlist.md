# Public shortlist (GitHub Pages)

Zero-install browsing of **confirmed Canada-eligible engineering jobs**. No clone, Python install, account, or profile required to browse.

## Public browsing vs personalized CLI

| | Public site (`site/`) | CLI (`githired`) |
| --- | --- | --- |
| Audience | Anyone | You (private machine) |
| Eligibility | Hard-filter **ELIGIBLE** + direct ATS apply URL | Same filters + **your** modes/city/salary |
| Ranking | Shared snapshot + optional client-side relevance | Deterministic / optional LLM scores vs your profile |
| Matching | Browser-only Find My Matches (deterministic) | Private rank pipeline |
| Data stored | Static `jobs.json` on Pages only | Local SQLite + `config/profile.yaml` |
| Never published | Profiles, résumés, credentials, private scores | — |

The public exporter **never** writes full job descriptions, emails, phones, API keys, or ranking fingerprints. Client matching uses title, location, track, seniority, technologies, and salary metadata only.

## Salary filtering (browser)

- Label: **Minimum Salary (CAD)** — range `$0`–`$300,000+`, step `$10,000`, default `$0`.
- Filtering uses advertised **annual** CAD/USD base compensation. USD→CAD uses `usd_to_cad` from `jobs.json` (default `1.35`).
- If a range is advertised, the job passes when **max** ≥ the slider value; cards show when only the max meets the floor.
- Hourly/contract/other currencies are treated as undisclosed for filtering when they cannot be normalized.
- Checkbox **Include jobs without advertised salaries** (default on).

## Find My Matches (browser)

Optional flow: upload / paste / manual entry → editable profile → scored shortlist.

- Parsing (PDF/DOCX/TXT) runs **locally** after lazy-loading parser libraries; file bytes are not retained.
- Extraction is deterministic pattern matching (skills, disciplines, seniority) — it does **not** invent experience.
- Scoring weights (approximate): title 30%, skills 30%, seniority 15%, discipline 15%, other preferences 10%.
- Geographic eligibility preferences are a **hard filter**. Missing listing details → **unconfirmed**, not a confirmed skill gap.
- Match % is explainable relevance, **not** AI-powered intelligence.

Privacy copy on the site: *Your résumé stays in your browser. We don't upload or store it on our servers.*

## How data is generated

1. GitHub Actions runs list-only `githired discover` (budgeted ATS concurrency).
2. Bounded `githired enrich` hydrates promising descriptions.
3. `scripts/export_public_shortlist.py` selects up to **400** jobs that:
   - match engineering tracks,
   - are geographically **ELIGIBLE** (not UNCERTAIN),
   - have a **direct, posting-specific** employer apply URL,
   - have a complete description (required to label **Verified**),
   - are not stale / removed.
4. Writes `site/jobs.json` (schema v2, includes `salary_max_cad`) and deploys the `site/` folder to GitHub Pages.
5. If the new snapshot is **empty**, deploy is **skipped** so the last good Pages site remains.

Salaries appear only when employers advertise CAD/USD annual figures — never estimated. Province-restricted remote is labeled `remote_scope: province`, not Canada-wide.

## Enable GitHub Pages (one-time, repository Settings)

1. Open **Settings → Pages** on `mikegianfelice/GitHired` (or your fork).
2. Under **Build and deployment → Source**, choose **GitHub Actions**.
3. Ensure the **Public shortlist (GitHub Pages)** workflow is allowed (Actions enabled).
4. Run **Actions → Public shortlist (GitHub Pages) → Run workflow**, or wait for the daily `17 11 * * *` UTC schedule.
5. When the deploy job succeeds, open `https://<owner>.github.io/GitHired/`.

Project Pages use the `/GitHired/` base path; the static assets use **relative** URLs so CSS/JS/`jobs.json` resolve correctly.

## Local export

```bash
python -m pip install -e .
githired discover && githired enrich
python scripts/export_public_shortlist.py --site-dir site
cd site && python3 -m http.server 8080
```

## Frontend modules

| Path | Role |
| --- | --- |
| `site/index.html` | Browse + Find My Matches UI |
| `site/app.js` | Filters, navigation, profile editor |
| `site/match-engine.js` | Salary filter + extract + match (pure JS) |
| `site/resume.js` | Local PDF/DOCX/TXT extraction |
| `site/jobs.json` | Public snapshot |
| `jobseek/public_shortlist/` | Selection + schema helpers |
| `scripts/export_public_shortlist.py` | CLI exporter |
| `.github/workflows/public-shortlist-pages.yml` | Daily / manual Pages publish |

## Tests

```bash
python -m unittest tests.jobseek.test_public_shortlist -v
node --test tests/jobseek/test_match_engine.js tests/jobseek/test_resume_privacy.js
```
