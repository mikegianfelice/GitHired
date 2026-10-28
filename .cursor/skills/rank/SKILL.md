---
name: rank
description: >-
  Deterministic (and optional LLM) scoring of discovered jobs for Canada-remote fit.
  Triggers on: rank jobs, score jobs, jobseek rank, githired rank, shortlist.
---

# Rank jobs

1. Run Stage-1 deterministic scoring (no API key required):

```bash
githired rank --limit 25
```

2. Optional Stage-2 LLM scoring (requires Anthropic or OpenAI key):

```bash
githired rank --limit 25 --llm
```

3. List the shortlist: `githired jobs --min-score 60`.
4. For the legacy Danish portal triage workflow, Read `.claude/commands/rank.md` (uses `tools/rank_state.py`). Prefer `githired` for Canada ATS jobs.
5. Never invent Canada eligibility; hard filters require quoted evidence. Deterministic scores are not AI evaluations.
