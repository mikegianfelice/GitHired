---
name: digest
description: >-
  Build or email the daily top-10 job digest. Triggers on: daily digest, email digest,
  jobseek digest, githired digest, run-daily.
---

# Daily digest

```bash
githired digest --save
githired email-digest          # optional SMTP/Resend
githired run-daily             # discover → rank → digest
githired run-daily --email
```

Fallback: `jobseek` instead of `githired`.
