# Search Queries for Job Scraper

<!-- Canada-remote AI / data / forward-deployed engineering focus -->

## Installed portal CLIs (primary for `/scrape`)

`/scrape` discovers every portal skill under `.agents/skills/*/SKILL.md` and runs its CLI first.
For production Canada-remote discovery prefer the `jobseek` CLI (Greenhouse / Lever / Ashby registry +
compliant LinkedIn sources). Keep portal CLIs for interactive sessions.

Danish demo portals ship with `enabled: false`. Leave LinkedIn guest scrape off for scheduled runs
(`sources.linkedin_guest: false` in `config/search.yaml`).

The `site:` query templates below are the **WebSearch fallback**.

**Language scope:** English (and any other languages listed in CLAUDE.md). Apply
`04-job-evaluation.md`'s Language Gate.

## Search Sites

Primary:
- **linkedin.com/jobs** — Canada remote / Remote (prefer search-index + alerts over guest scrape)
- **Company ATS boards** — Greenhouse, Lever, Ashby via `config/companies.yaml` + `jobseek discover`
- **freehire.me** — optional aggregator (`sources.freehire`)

Secondary:
- Direct Google `site:` searches for target company career pages

## Query Categories

### Priority 1: AI Engineering

```
site:linkedin.com/jobs "AI Engineer" (Canada OR "Remote Canada" OR "remote in Canada")
site:linkedin.com/jobs "Senior AI Engineer" (Canada OR Remote)
site:linkedin.com/jobs "Applied AI Engineer" (Canada OR Remote)
site:linkedin.com/jobs "Machine Learning Engineer" (Canada OR "Remote Canada")
"AI Engineer" remote Canada
```

### Priority 2: Forward Deployed / Solutions

```
site:linkedin.com/jobs "Forward Deployed Engineer" (Canada OR Remote)
site:linkedin.com/jobs "AI Solutions Architect" (Canada OR Remote)
site:linkedin.com/jobs "Solutions Architect" AI OR LLM (Canada OR Remote)
"Forward Deployed Engineer" remote Canada
```

### Priority 3: Data Engineering

```
site:linkedin.com/jobs "Senior Data Engineer" (Canada OR "Remote Canada")
site:linkedin.com/jobs "Staff Data Engineer" (Canada OR Remote)
site:linkedin.com/jobs "Data Engineer" (Remote) Canada
"Staff Data Engineer" remote Canada
```

### Priority 4: Broader AI platform

```
site:linkedin.com/jobs "LLM Engineer" OR "Generative AI" (Canada OR Remote)
site:linkedin.com/jobs "AI Platform Engineer" (Canada OR Remote)
"MLOps" OR "AI Platform" remote Canada
```

## Location Filter

Hard filters for `jobseek` live in `config/search.yaml`. For `/scrape` agent review:

- Prefer: Canada remote, Remote Canada, hybrid Canada
- US employers hiring remotely are eligible **only** with explicit Canada / worldwide evidence in the posting
- Reject US-only remote unless Canadian eligibility is explicitly established
- Never invent Canadian hiring eligibility

Acceptable:
- Canada (remote / hybrid)
- Remote — Canada
- Worldwide / work from anywhere (when evidenced)
- US remote **with** "Canada", "Canadian applicants", or equivalent evidence

Reject / flag:
- US-only remote, "must be located in the United States"
- Roles requiring relocation outside Canada without a remote option

## Language Filter

Your working languages and levels are in CLAUDE.md's Languages table. When filtering scraped results, apply `04-job-evaluation.md`'s Language Gate.

## Date Filter

Only include jobs posted within the last 14–30 days (see `config/search.yaml` `recency_days`), or with an application deadline that has not yet passed. If a posting date cannot be determined, include it but flag as "date unknown".

## Adapting Queries

If the user specifies a focus area, select queries from the matching category and also generate 2-3 custom queries for that focus.
