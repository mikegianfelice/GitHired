# Public shortlist (GitHub Pages)

Zero-install browsing of **confirmed Canada-eligible engineering jobs**. No clone, Python install, account, or profile required.

## Public browsing vs personalized CLI

| | Public site (`site/`) | CLI (`githired`) |
| --- | --- | --- |
| Audience | Anyone | You (private machine) |
| Eligibility | Hard-filter **ELIGIBLE** + direct ATS apply URL | Same filters + **your** modes/city/salary |
| Ranking | Shared snapshot order (salary when present, then company) | Deterministic / optional LLM scores vs your profile |
| Data stored | Static `jobs.json` on Pages only | Local SQLite + `config/profile.yaml` |
| Never published | Profiles, resumes, credentials, private scores | — |

The public exporter **never** writes full job descriptions, emails, phones, API keys, or ranking fingerprints.

## How data is generated

1. GitHub Actions runs list-only `githired discover` (budgeted ATS concurrency).
2. Bounded `githired enrich` hydrates promising descriptions.
3. `scripts/export_public_shortlist.py` selects up to **300** jobs that:
   - match engineering tracks,
   - are geographically **ELIGIBLE** (not UNCERTAIN),
   - have a **direct, posting-specific** employer apply URL,
   - have a complete description (required to label **Verified**),
   - are not stale / removed.
4. Writes `site/jobs.json` and deploys the `site/` folder to GitHub Pages.
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
python scripts/export_public_shortlist.py --site-dir site --limit 300
cd site && python3 -m http.server 8080
```

## Files

| Path | Role |
| --- | --- |
| `site/` | Static frontend + `jobs.json` |
| `jobseek/public_shortlist/` | Selection + schema helpers |
| `scripts/export_public_shortlist.py` | CLI exporter |
| `.github/workflows/public-shortlist-pages.yml` | Daily / manual Pages publish |
