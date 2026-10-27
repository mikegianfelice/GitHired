---
name: discover
description: >-
  Run Canada-remote job discovery via the jobseek CLI (Greenhouse, Lever, Ashby,
  compliant LinkedIn sources). Triggers on: discover jobs, jobseek discover, scrape ATS,
  find new jobs (Canada).
---

# Discover jobs

1. Ensure dependencies: `pip install -e .` from the repo root (and copy `.env.example` → `.env` if needed).
2. Run:

```bash
python -m jobseek.cli.main discover --import-tracker
```

Or after install: `jobseek discover --import-tracker`.

3. For the legacy portal `/scrape` agent workflow, Read `.claude/skills/job-scraper/SKILL.md` and follow it.
4. Do not enable LinkedIn guest scraping for scheduled runs. Use `jobseek import-alerts <file>` for saved alerts.
