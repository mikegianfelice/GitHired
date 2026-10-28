# Community company registry

Validated public ATS boards contributed via pull request.

## Rules

- Only publicly accessible board endpoints (Greenhouse, Lever, Ashby, Workable, RSS, etc.).
- Never invent `board_token` values — extract them from real careers / ATS URLs.
- Include short validation notes (endpoint + date).
- Do **not** upload personal profiles, application history, API keys, or local SQLite dumps.

## Format

See `schema.v1.json` and `companies.v1.yaml`. Import locally with:

```bash
githired companies import registry/community/companies.v1.yaml
```

Export locally discovered (validated) rows for a PR draft:

```bash
githired companies export --validated --out /tmp/companies.v1.yaml
```

Automatic discovery never publishes without explicit export + PR.
