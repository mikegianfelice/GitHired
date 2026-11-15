# Owner steps: upload & submit GitHired to the ChatGPT Plugin Directory

**Do not claim the plugin is listed until OpenAI review completes.**  
Prepared package: `githired-chatgpt-plugin-1.0.2.zip` in this directory.

Official docs:
- https://developers.openai.com/plugins/deploy/submission
- https://developers.openai.com/plugins/build/plugins
- https://developers.openai.com/plugins/deploy/submission-errors

## Before you upload

1. Confirm you can open:
   - https://githired.ca/privacy
   - https://githired.ca/terms
   - https://github.com/mikegianfelice/GitHired/issues
   - https://api.githired.ca/mcp (already connected as your personal plugin)
2. In [OpenAI Platform](https://platform.openai.com/), complete **individual or business verification** for the name you will publish under.
3. Ensure your org role includes **`api.apps.write`** (owners have it by default).
4. Record a short **demo walkthrough** (positive + negative cases). Host it at an HTTPS URL you control. You will paste this as `demo_recording_url` in Review details (or rebuild the ZIP with `extensions.com.openai.review.demo_recording_url` set).

## Upload the ZIP

1. Open the Plugins page in the OpenAI dashboard → **Upload new or existing plugin** (or open your existing personal GitHired plugin draft if the portal allows attaching a package to it).
2. Choose your **verified developer identity**.
3. Upload `githired-chatgpt-plugin-1.0.2.zip`.
4. Wait for **Metadata & Skills** automated checks. Fix any package findings by editing `plugins/openai-githired/` and rebuilding the ZIP (see rebuild note below).

## Connect / scan MCP (if not already linked on this draft)

Because the MCP is already working as a personal plugin, reconnect or confirm:

1. Open **MCPs** → select the GitHired server (URL `https://api.githired.ca/mcp`, authentication: none).
2. Complete any **domain verification** challenge the portal shows for `githired.ca` / `api.githired.ca`.
3. **Scan Tools**. Confirm tools: `search_jobs`, `get_job`, `match_profile`, `get_market_stats` with read-only annotations.
4. Resolve any tool findings, then Rescan.

## Complete review materials

1. Open **Review information → Review details**.
2. Confirm the five positive and three negative cases imported from the ZIP (also listed in `VALIDATION.md` / `plugin.json`).
3. Enter the **demo recording URL**.
4. Leave credentials empty (no auth). Do not put secrets in the ZIP.
5. Save details.

## Submit for review

1. Select the draft → **Submit for review**.
2. Complete **policy attestations** yourself (do not have an agent “accept” them for you).
3. Track status under **Review status**. Publish only after approval, when you choose.

## Rebuild the ZIP (if needed)

From the repo root:

```bash
python3 - <<'PY'
# or re-run the packaging script used to create this release
print('Rebuild from plugins/openai-githired into releases/chatgpt-plugin-githired-1.0.2/')
PY
```

Source of truth for package files: `plugins/openai-githired/`.

## Out of scope / not done by automation

- Public directory submission
- Purchasing services
- Inventing a support email or legal entity claims
- Modifying job discovery / matching / MCP behavior for this package
