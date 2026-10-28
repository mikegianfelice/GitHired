---
name: discover
description: >-
  Run Canada-remote job discovery via the githired CLI (Greenhouse, Lever, Ashby,
  compliant LinkedIn sources). Triggers on: discover jobs, jobseek discover, githired discover,
  scrape ATS, find new jobs (Canada).
---

# Discover jobs

1. Ensure dependencies: `pip install -e .` from the repo root (and copy `.env.example` → `.env` if needed). Prefer `githired setup` for first-time config.
2. Run:

```bash
githired discover
```

Fallback: `jobseek discover` or `python -m jobseek.cli.main discover`.

3. Check source health: `githired sources` / `githired doctor`.
4. For the legacy Danish portal `/scrape` agent workflow, Read `.claude/skills/job-scraper/SKILL.md` and follow it.
5. Do not enable LinkedIn guest scraping for scheduled runs. Use `githired import-alerts <file>` for saved alerts.
