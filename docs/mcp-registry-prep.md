# MCP Registry preparation

GitHired’s remote MCP server is ready for publication to the
[official MCP Registry](https://modelcontextprotocol.io/registry/about)
(preview). **Nothing has been submitted from this automation.**

Live check (2026-11-15): `GET`/`POST https://api.githired.ca/mcp` works;
`tools/list` returns `search_jobs`, `get_job`, `match_profile`, `get_market_stats`.
Registry search for `githired` / `ca.githired` returned **zero** existing entries.

## Canonical metadata

Validated draft lives at repo-root [`server.json`](../server.json):

| Field | Value |
| --- | --- |
| Preferred name | `ca.githired/jobs` (domain auth for `githired.ca`) |
| Fallback name | `io.github.mikegianfelice/githired` (GitHub auth) |
| Title | GitHired |
| Description | Canada-eligible tech jobs from employer ATS boards. Read-only search, match, stats. (≤100 chars) |
| Version | `1.0.1` |
| Transport | `streamable-http` |
| URL | `https://api.githired.ca/mcp` |
| Auth on remote | None |
| Website | https://githired.ca/agents |
| Repository | https://github.com/mikegianfelice/GitHired |
| Schema | `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json` |

If using the GitHub namespace, change `server.json` `"name"` to
`io.github.mikegianfelice/githired` before publish.

## Owner actions to publish (domain namespace)

Official docs: [Authentication](https://modelcontextprotocol.io/registry/authentication) ·
[Remote servers](https://modelcontextprotocol.io/registry/remote-servers) ·
[Quickstart](https://modelcontextprotocol.io/registry/quickstart)

1. Install CLI: follow the quickstart for `mcp-publisher`.
2. Generate an Ed25519 keypair (**OpenSSL 3+** on macOS; LibreSSL cannot `genpkey` Ed25519).
3. Host proof at `https://githired.ca/.well-known/mcp-registry-auth` **or** publish an apex TXT on `githired.ca`:
   `v=MCPv1; k=ed25519; p=<base64-public-key>`
   - HTTP: must return `200` with the proof body (no redirects); Registry fetches with `User-Agent: mcp-registry/1.0`.
   - DNS: record on the **apex** (`githired.ca`), not `_mcp-auth.githired.ca`.
4. Login:
   ```bash
   mcp-publisher login http --domain githired.ca --private-key "<hex-private-key>"
   # or: mcp-publisher login dns --domain githired.ca --private-key "<hex-private-key>"
   ```
5. From the repo root (with `server.json` present):
   ```bash
   mcp-publisher publish
   ```
6. Verify:
   ```bash
   curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=ca.githired/jobs"
   ```

## Owner actions (GitHub namespace alternative)

```bash
mcp-publisher login github
# edit server.json name → io.github.mikegianfelice/githired
mcp-publisher publish
```

Device flow grants the **personal** `io.github.mikegianfelice/*` namespace.
Org namespaces need GitHub Actions OIDC or a PAT with org membership read — see auth docs.

## Client install (already public)

- Cursor official deeplink: https://githired.ca/agents
- Claude / ChatGPT custom connector: paste `https://api.githired.ca/mcp` (no third-party one-click)
