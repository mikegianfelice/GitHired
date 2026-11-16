# Résumé matching quality audit (2026-11-16)

Production failure report: fictional Senior Data Engineer PDF uploaded on githired.ca → Find My Matches ranked junior SRE / junior SWE above Senior Data Engineer.

## 1. Root causes (with code references)

| Failure | Cause | Location |
| --- | --- | --- |
| Negated skills confirmed | `extractSkills` regex-scanned the whole résumé; “Not claimed: Kubernetes, Java, React, Azure, GCP” and wrapped “Exclude: … Kubernetes” counted as skills | `site/match-engine.js` (`extractSkills`) |
| Junior + senior seniority | `extractSeniority` matched `entry-level` inside **Exclude:** → profile `seniority: ["junior","senior"]` → junior jobs scored `wanted.includes("junior")` → **“Seniority compatible”** | `extractSeniority` / `seniorityScore` / `scoreJob` reasons |
| Title became person name | Header line `Senior Data Engineer \| Toronto \| email…` exceeded 80 chars; fallback was `Alex Morgan` | `extractTitle` |
| Years missing | “6 years of **professional** experience” missed the years regex | `extractYears` |
| Salary never extracted | Preferences line `CAD $150,000` ignored; `minimum_salary_cad` stayed `0` | `extractProfileFromText` |
| On-site allowed | “Exclude: onsite-only” still added `onsite` | `extractArrangements` |
| Frontend track on profile | “frontend engineering” inside Exclude matched `software_engineering` | `extractDisciplines` |
| Ranking overweight keywords | Shared tech + soft discipline rescue let junior SWE/SRE beat role-aligned senior DE | `scoreJob` weights / title gate / no senior→junior demotion |

`site/resume.js` only extracts PDF/DOCX **text** (client-side). Profile parsing and scoring live in `site/match-engine.js`. REST/MCP (`api/src/match.ts`) consume a **normalized** profile (no résumé text); seniority messaging/weights were aligned there too.

## 2. Extracted profile before fixes

From the same PDF text fixture (`tests/jobseek/fixtures/mock_senior_data_engineer_resume.txt`):

```json
{
  "current_title": "Alex Morgan",
  "desired_titles": ["Alex Morgan"],
  "years_experience": null,
  "skills": ["Python","SQL","PySpark","Java","React","AWS","Azure","GCP","Databricks","Delta Lake","Spark","Kubernetes","Docker","Terraform","CI/CD","LLM","Power BI"],
  "disciplines": ["software_engineering","data_engineering","platform_engineering","analytics_engineering"],
  "seniority": ["junior","senior"],
  "work_arrangements": ["remote","hybrid","onsite"],
  "minimum_salary_cad": 0
}
```

Observed live-style top hits with that profile: PolicyMe Junior SWE (~68–73%), PointClickCare Jr SRE (~65–73%) with reasons including **Confirmed matching skills: Azure, Kubernetes** / **React** and **Seniority compatible**. Sun Life Senior Data Engineer ranked lower or was crowded out.

## 3. Corrected extracted profile

```json
{
  "current_title": "Senior Data Engineer",
  "desired_titles": ["Senior Data Engineer","Data Platform Engineer","Analytics Engineer"],
  "years_experience": 6,
  "skills": ["Python","SQL","PySpark","AWS","Databricks","Delta Lake","Spark","Docker","Terraform","CI/CD","Power BI"],
  "disciplines": ["data_engineering","platform_engineering","analytics_engineering"],
  "seniority": ["senior"],
  "preferred_locations": ["ON","Toronto","Canada"],
  "work_arrangements": ["remote","hybrid"],
  "minimum_salary_cad": 150000,
  "include_undisclosed_salary": true,
  "salary_filter_mode": "strict"
}
```

Denied skills (Kubernetes, Java, React, Azure, GCP, LLM) are absent. On-site and software_engineering no longer appear from Exclude text.

## 4. Before / after top recommendations

**Before (broken profile, site `jobs.json`):** junior PolicyMe / PointClickCare dominated; Sun Life not in top tier.

**After (fixed parse + score, same `jobs.json`, limit 10):**

| % | Company | Title | Seniority |
| --- | --- | --- | --- |
| 95 | Sun Life | Senior Data Engineer | senior |
| 93 | Lightspeed | Senior Analytics Engineer | senior |
| 91 | Mercury | Senior Analytics Engineer | senior |
| 88 | Cohere | Senior Staff Data Engineer | senior |
| … | Affirm / GitLab / Grafana / … | senior data-adjacent | senior |

PointClickCare Jr SRE and PolicyMe Junior SWE are **ineligible** (title/role-family gate and/or salary floor). They are not hard-coded exclusions.

## 5. Before / after scores & explanations

| Job | Before | After |
| --- | --- | --- |
| PointClickCare Jr SRE | ~65–73%, matched Azure/Kubernetes, “Seniority compatible” | Ineligible — role family / salary |
| PolicyMe Junior SWE | ~68–73%, matched React among others, “Seniority compatible” | Ineligible — role family / salary |
| Sun Life Senior Data Engineer | Mid-pack / lower | ~94–95%, title + Python/SQL/Spark/AWS, “Seniority compatible” (correct) |

Senior→junior listings that still pass gates get a soft demotion and an explicit note: *Job is junior/entry-level; your profile targets more senior roles* — never “Seniority compatible”.

## 6. Regression tests

```text
node --test tests/jobseek/test_match_resume_quality.js \
  tests/jobseek/test_match_engine.js \
  tests/jobseek/test_match_qa_personas.js
# 62 pass

cd api && npm test
# 23 pass
```

Coverage includes: negation / aspirational / multi-tech denial; mock DE fixture; six personas (senior DE, junior Python, career switcher, staff AI, frontend, solutions architect); junior-vs-senior ranking sanity.

## 7. Performance

Client `matchJobs` over ~524 site jobs: ~85 ms on a laptop Node run after fixes (same order of magnitude as before). No LLM / server résumé upload introduced.

## 8. Remaining limitations

- Heuristic negation can miss unusual phrasing (“Kubernetes is on my learning backlog”).
- PDF text order depends on pdf.js layout; pathological multi-column résumés may still confuse title detection.
- Website matching and API/MCP share intent; résumé **parsing** remains browser-only (by design).
- Undisclosed salary still included when `include_undisclosed_salary` is true (product default).
- Soft title gate (`title < 0.6 && disc < 0.9`) can still admit adjacent platform roles; that is intentional for data-platform mobility.

## 9. Leave unchanged

- ATS discovery / salary extraction from employer postings
- Client-side PDF/DOCX extraction architecture (`site/resume.js`)
- Public shortlist Canada-eligibility pipeline
- REST/MCP request schemas (backward compatible)
- Deterministic (non-LLM) matching philosophy
