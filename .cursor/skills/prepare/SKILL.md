---
name: prepare
description: >-
  Briefing for a scored job before applying. Never auto-drafts or submits.
  Triggers on: prepare application, jobseek prepare, apply briefing.
---

# Prepare (approval gate)

```bash
python -m jobseek.cli.main prepare <job_id>
```

This prints company, title, URL, and next steps only.

To draft a CV/cover letter, Read `.claude/commands/apply.md` and run `/apply <url>` —
**ask the user before drafting**. Never submit applications automatically.
