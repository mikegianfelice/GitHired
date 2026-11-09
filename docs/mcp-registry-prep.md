# MCP Registry preparation (do not submit without approval)

GitHired’s remote MCP server is ready for eventual publication to the
[official MCP Registry](https://modelcontextprotocol.io/registry/about).
**Nothing has been submitted.**

## Proposed identity

| Field | Value |
| --- | --- |
| Preferred name | `ca.githired/jobs` (domain auth for `githired.ca`) **or** `io.github.mikegianfelice/githired` (GitHub auth) |
| Transport | Streamable HTTP |
| URL | `https://api.githired.ca/mcp` |
| Auth | None required |

## Draft `server.json` (remote)

```json
{
  "name": "ca.githired/jobs",
  "description": "Canada-eligible technology jobs from employer ATS boards. Read-only search, detail, profile match, and market stats. Advertised salaries only.",
  "version": "1.0.0",
  "remotes": [
    {
      "type": "streamable-http",
      "url": "https://api.githired.ca/mcp"
    }
  ],
  "websiteUrl": "https://githired.ca/agents"
}
```

## Domain authentication checklist

1. Choose domain namespace `ca.githired/*` via HTTP or DNS challenge for `githired.ca`.
2. Host `/.well-known/mcp-registry-auth` (HTTP method) or DNS TXT as required by
   [registry authentication docs](https://modelcontextprotocol.io/registry/authentication).
3. Run `mcp-publisher login` / `publish` only after explicit maintainer approval.

## GitHub namespace alternative

Use `io.github.mikegianfelice/githired` with GitHub device login if domain verification is deferred.

## Client install (already public)

- Cursor official deeplink documented on https://githired.ca/agents
- Claude / ChatGPT: copyable URL instructions (no third-party one-click)
