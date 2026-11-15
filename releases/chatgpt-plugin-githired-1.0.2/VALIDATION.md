# ChatGPT plugin package validation — GitHired 1.0.2

- **ZIP:** `/Users/gianf/GitHired/releases/chatgpt-plugin-githired-1.0.2/githired-chatgpt-plugin-1.0.2.zip` (27391 bytes)
- **Agent Plugins schema:** PASS
- **OpenAI submission field checks:** PASS (27/27)
  - [PASS] displayName ≤30 — 'GitHired'
  - [PASS] shortDescription ≤30 — 24 chars
  - [PASS] longDescription ≤4000 — 564 chars
  - [PASS] developerName ≤80
  - [PASS] category set
  - [PASS] websiteURL https
  - [PASS] supportURL https
  - [PASS] privacyPolicyURL https
  - [PASS] termsOfServiceURL https
  - [PASS] logo present
  - [PASS] composerIcon present
  - [PASS] defaultPrompt ≤3
  - [PASS] defaultPrompt lengths ≤128
  - [PASS] exactly 1 mcp server
  - [PASS] mcp streamable-http
  - [PASS] mcp public url
  - [PASS] 5 positive cases — 5
  - [PASS] 3 negative cases — 3
  - [PASS] positive fields
  - [PASS] negative fields
  - [PASS] onboarding skill exists
  - [PASS] no demo_recording_url in package (owner must supply)
  - [PASS] privacy live — {'status': 200, 'final_url': 'https://githired.ca/privacy/', 'bytes': 3982}
  - [PASS] terms live — {'status': 200, 'final_url': 'https://githired.ca/terms/', 'bytes': 3509}
  - [PASS] support live — {'status': 200, 'final_url': 'https://github.com/mikegianfelice/GitHired/issues', 'bytes': 191665}
  - [PASS] mcp tools/list
  - [PASS] mcp annotations present

## Live URL probes

```json
{
  "privacy": {
    "status": 200,
    "final_url": "https://githired.ca/privacy/",
    "bytes": 3982
  },
  "terms": {
    "status": 200,
    "final_url": "https://githired.ca/terms/",
    "bytes": 3509
  },
  "website": {
    "status": 200,
    "final_url": "https://githired.ca",
    "bytes": 20020
  },
  "support": {
    "status": 200,
    "final_url": "https://github.com/mikegianfelice/GitHired/issues",
    "bytes": 191665
  },
  "mcp": {
    "status": 200,
    "tools": [
      "search_jobs",
      "get_job",
      "match_profile",
      "get_market_stats"
    ],
    "annotations": true
  }
}
```

## Missing before public submit

- review.demo_recording_url — required before Submit for review (host a short walkthrough video and paste the HTTPS URL in the dashboard or a revised ZIP)
- Dedicated support email / business contact — not provided; package uses GitHub Issues as supportURL (existing public channel). Add a business email later only if you want one.
- OpenAI individual/business identity verification + policy attestations (dashboard only; cannot be packaged)

## Not submitted
This package was prepared only. No OpenAI upload or review submission was performed.

