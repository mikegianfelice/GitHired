---
name: digest
description: >-
  Build or email the daily top-10 job digest. Triggers on: daily digest, email digest,
  jobseek digest, run-daily.
---

# Digest

```bash
python -m jobseek.cli.main digest --save
python -m jobseek.cli.main email-digest   # requires SMTP_* or RESEND_API_KEY
python -m jobseek.cli.main run-daily --email
```

Scheduling example (launchd/cron): run `jobseek run-daily --email` once per day.
See `docs/discovery.md` and `SETUP.md`.
