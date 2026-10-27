---
name: rank
description: >-
  Hard-filter and LLM-score discovered jobs for Canada-remote fit. Triggers on:
  rank jobs, score jobs, jobseek rank, shortlist.
---

# Rank jobs

1. Run deterministic filters + LLM scoring:

```bash
python -m jobseek.cli.main rank --limit 25
```

2. For the legacy agent triage workflow, Read `.claude/commands/rank.md` and follow it (uses `tools/rank_state.py`).
3. Never invent Canada eligibility; hard filters require quoted evidence.
