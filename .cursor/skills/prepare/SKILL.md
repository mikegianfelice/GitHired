---
name: prepare
description: >-
  Briefing for a scored job before applying. Never auto-drafts or submits.
  Triggers on: prepare application, jobseek prepare, githired prepare, apply briefing.
---

# Prepare (briefing only)

```bash
githired prepare <job_id>
```

Prints company, title, URL, and next steps. Does **not** draft a CV/cover letter or submit.
For drafting, ask the user to confirm, then follow `.claude/commands/apply.md`.
