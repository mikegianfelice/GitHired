# MCP & agent distribution report (2026-11-15)

## 1. Directory readiness

| Platform | Readiness | Blockers for live listing |
| --- | --- | --- |
| **Live MCP (any client)** | **Ready now** | None for custom URL install |
| **Official MCP Registry** | Metadata ready (`server.json`) | Owner must authenticate namespace (`ca.githired/*` domain or `io.github.mikegianfelice/*`) then `mcp-publisher publish` |
| **ChatGPT / Codex directory** | Package ready (`plugins/openai-githired/`) | Owner OpenAI identity verification, portal upload, domain verification, demo recording, policy attestations, review |
| **Cursor Marketplace** | Plugin ready (`plugins/githired/` + marketplace manifest) | Owner submit at cursor.com/marketplace/publish + accept publisher terms; manual Cursor review |

No directory listing was published by this automation.

## 2. Integration audit (Step 1)

| Check | Result |
| --- | --- |
| MCP `initialize` | OK — `serverInfo.name=githired`, `version` bumped to `1.0.1` in source |
| MCP `tools/list` | OK — 4 tools |
| Tool call `search_jobs` | OK — live results |
| HTTPS endpoint | `https://api.githired.ca/mcp` |
| Authentication | None required |
| Tool schemas | Present; **annotations added** (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) |
| REST health | `GET /api/v1/health` → `status=ok`, dataset **fresh** (~22.6h age at audit) |
| Install docs | `/agents`, `/developers`, `/llms.txt`, README |
| Registry collision | Search `githired` / `ca.githired` → empty |

### Fixes applied (confirmed blockers only)

1. MCP tool annotations for directory reviewers (`api/src/mcp.ts`).
2. Public `/privacy` and `/terms` pages (required by OpenAI listing fields).
3. Packaging + docs for the three directories (no false “published” claims).

**Deploy still required** for annotations + privacy/terms to appear on production hosts.

## 3. Files added or changed

| Path | Purpose |
| --- | --- |
| `api/src/mcp.ts` | Tool annotations + version `1.0.1` |
| `api/test/mcp.test.js` | Annotation regression |
| `server.json` | Official registry remote server metadata |
| `docs/mcp-registry-prep.md` | Updated publish procedure |
| `docs/mcp-distribution-report.md` | This report |
| `plugins/githired/**` | Cursor Marketplace plugin |
| `plugins/openai-githired/**` | ChatGPT/Codex plugin ZIP contents |
| `.cursor-plugin/marketplace.json` | Multi-plugin repo manifest |
| `site/privacy/`, `site/terms/` | Privacy + terms |
| `site/agents/index.html` | Directory discoverability |
| `site/llms.txt`, `sitemap.xml`, `robots.txt` | Discoverability |

## 4. Validated submission metadata

### Official MCP Registry (`server.json`)

- **name:** `ca.githired/jobs`
- **title:** GitHired
- **description:** Canada-eligible tech jobs from employer ATS boards. Read-only search, match, stats.
- **version:** 1.0.1
- **remote:** streamable-http → `https://api.githired.ca/mcp`
- **websiteUrl:** https://githired.ca/agents
- **repository:** https://github.com/mikegianfelice/GitHired

### ChatGPT / Codex

- **Package name:** `githired`
- **Display name:** GitHired
- **Short description:** Canadian tech job search
- **Category:** Developer Tools
- **MCP URL:** `https://api.githired.ca/mcp`
- **Privacy / Terms / Support:** `/privacy`, `/terms`, GitHub Issues
- **Icons:** `plugins/openai-githired/assets/{logo,icon}.svg`

### Cursor Marketplace

- **Plugin name:** `githired`
- **MCP URL:** `https://api.githired.ca/mcp`
- **One-click (already live):** Cursor deeplink on https://githired.ca/agents
- **Submit URL:** https://cursor.com/marketplace/publish

## 5. Exact owner actions required

1. **Deploy API** (annotations) and **deploy site** (privacy/terms/agents updates).
2. **MCP Registry:** complete DNS or HTTP domain auth for `githired.ca` (or GitHub login), then `mcp-publisher publish` from repo root. Do not invent alternate namespaces.
3. **OpenAI:** verify developer identity → zip `plugins/openai-githired` → upload → connect MCP → domain verification → scan tools → demo recording → submit. Read and accept OpenAI policies yourself.
4. **Cursor:** open https://cursor.com/marketplace/publish, submit `https://github.com/mikegianfelice/GitHired`, accept [Publisher Terms](https://cursor.com/marketplace-publisher-terms). Expect manual review (often weeks).

## 6. Actual submissions completed

**None.** Registry publish, OpenAI upload, and Cursor marketplace submit all require interactive owner authorization and/or legal acceptance.

## 7. Pending approvals

- Official MCP Registry (after owner `publish`)
- OpenAI ChatGPT/Codex directory review
- Cursor Marketplace review

## 8. Remaining integration blockers

| Item | Notes |
| --- | --- |
| Production deploy lag | Annotations + legal pages exist in git until site/API deploy |
| OpenAI demo recording | Owner must record and host a short demo URL |
| Domain verification challenges | Registry HTTP/DNS proof; OpenAI portal challenge — owner DNS/hosting access required |
| No invented contacts | Support is GitHub Issues only; add a business email later if desired |
