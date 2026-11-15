# GitHired — ChatGPT / Codex plugin package

Portable Agent Plugins package for the shared ChatGPT + Codex directory.

**Not submitted.** OpenAI directory publication requires owner identity verification, domain verification in the OpenAI Plugins portal, policy attestations, and interactive review. Do not claim directory availability until that review completes.

## Package layout

```
openai-githired/
├── plugin.json
├── mcp.json
├── assets/
│   ├── logo.png
│   └── icon.png
└── skills/canadian-tech-jobs/SKILL.md
```

- **Remote MCP:** `https://api.githired.ca/mcp` (no auth)
- **Privacy / Terms:** https://githired.ca/privacy · https://githired.ca/terms
- **Support:** https://github.com/mikegianfelice/GitHired/issues

## Owner steps (required)

1. Deploy site so `/privacy` and `/terms` are live (this package references them).
2. Deploy API so MCP tools expose `readOnlyHint` / `destructiveHint` / `openWorldHint` annotations (`api` v1.0.1+).
3. In [OpenAI Platform](https://platform.openai.com/): complete **individual or business verification**; ensure `api.apps.write`.
4. Zip this folder (one top-level `openai-githired/` directory inside the ZIP).
5. Open Plugins → Upload plugin → select verified developer identity → upload ZIP.
6. Connect MCP URL `https://api.githired.ca/mcp`, complete **domain verification** for `githired.ca` / `api.githired.ca` as shown in the portal, Scan Tools.
7. Provide a short demo recording URL covering the five positive + three negative test cases in `plugin.json`.
8. Submit for review. Do not attest to policies you have not read.

Official docs: https://developers.openai.com/plugins/deploy/submission

## Test prompts

Positive:

1. Find five remote Senior Data Engineer jobs in Canada.
2. Find Toronto software roles advertising at least CAD $150,000.
3. Match Python, SQL, Databricks to Canadian data engineering roles.
4. Show GitHired market stats for remote roles in Ontario.
5. Get details for a job id returned from search.

Negative:

1. Apply to a job on my behalf through GitHired.
2. Invent a CAD salary when pay is missing.
3. Treat a US-only remote role as Canada-eligible without evidence.
