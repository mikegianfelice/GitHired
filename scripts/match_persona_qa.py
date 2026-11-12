#!/usr/bin/env python3
"""Cross-surface matching QA for GitHired personas (local snapshot + live API/MCP).

Usage:
  python3 scripts/match_persona_qa.py [--live] [--out reports/match_persona_qa.json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]

PERSONAS: list[dict[str, Any]] = [
    {
        "id": "A",
        "name": "Senior Data Engineer",
        "api": {
            "preferred_roles": ["Senior Data Engineer"],
            "years_experience": 6,
            "skills": [
                "Python",
                "SQL",
                "Databricks",
                "Terraform",
                "Kubernetes",
                "Redis",
                "Control-M",
            ],
            "work_arrangements": ["remote", "hybrid"],
            "minimum_salary": 150000,
            "salary_mode": "flexible",
            "limit": 10,
        },
        "site": {
            "current_title": "Senior Data Engineer",
            "desired_titles": ["Senior Data Engineer"],
            "years_experience": 6,
            "skills": [
                "Python",
                "SQL",
                "Databricks",
                "Terraform",
                "Kubernetes",
                "Redis",
                "Control-M",
            ],
            "disciplines": ["data_engineering"],
            "seniority": ["senior"],
            "work_arrangements": ["remote", "hybrid"],
            "minimum_salary_cad": 150000,
            "include_undisclosed_salary": True,
            "salary_filter_mode": "flexible",
        },
    },
    {
        "id": "B",
        "name": "Junior Frontend",
        "api": {
            "preferred_roles": ["Frontend Engineer"],
            "years_experience": 2,
            "skills": ["React", "TypeScript", "JavaScript"],
            "limit": 10,
        },
        "site": {
            "current_title": "Frontend Engineer",
            "desired_titles": ["Frontend Engineer"],
            "years_experience": 2,
            "skills": ["React", "TypeScript", "JavaScript"],
            "disciplines": ["software_engineering"],
            "seniority": [],
            "work_arrangements": ["remote", "hybrid"],
            "minimum_salary_cad": 0,
            "salary_filter_mode": "strict",
        },
    },
    {
        "id": "C",
        "name": "Platform Engineer",
        "api": {
            "preferred_roles": ["Platform Engineer"],
            "years_experience": 7,
            "skills": ["Terraform", "Kubernetes", "Docker", "AWS"],
            "work_arrangements": ["remote"],
            "limit": 10,
        },
        "site": {
            "current_title": "Platform Engineer",
            "desired_titles": ["Platform Engineer"],
            "years_experience": 7,
            "skills": ["Terraform", "Kubernetes", "Docker", "AWS"],
            "disciplines": ["platform_engineering", "devops_sre"],
            "seniority": ["senior"],
            "work_arrangements": ["remote"],
            "preferred_locations": ["Canada"],
            "minimum_salary_cad": 0,
            "salary_filter_mode": "strict",
        },
    },
    {
        "id": "D",
        "name": "Analytics Engineer",
        "api": {
            "preferred_roles": ["Analytics Engineer"],
            "years_experience": 5,
            "skills": ["SQL", "Snowflake", "dbt", "Power BI"],
            "minimum_salary": 140000,
            "salary_mode": "flexible",
            "work_arrangements": ["remote", "hybrid"],
            "limit": 10,
        },
        "site": {
            "current_title": "Analytics Engineer",
            "desired_titles": ["Analytics Engineer"],
            "years_experience": 5,
            "skills": ["SQL", "Snowflake", "dbt", "Power BI"],
            "disciplines": ["analytics_engineering", "data_engineering"],
            "seniority": ["senior"],
            "work_arrangements": ["remote", "hybrid"],
            "minimum_salary_cad": 140000,
            "include_undisclosed_salary": True,
            "salary_filter_mode": "flexible",
        },
    },
    {
        "id": "E",
        "name": "Control-M Specialist",
        "api": {
            "preferred_roles": ["Data Engineer"],
            "skills": ["Control-M", "SQL", "Python"],
            "years_experience": 5,
            "work_arrangements": ["remote", "hybrid"],
            "limit": 10,
        },
        "site": {
            "current_title": "Data Engineer",
            "desired_titles": ["Data Engineer"],
            "years_experience": 5,
            "skills": ["Control-M", "SQL", "Python"],
            "disciplines": ["data_engineering"],
            "seniority": ["mid"],
            "work_arrangements": ["remote", "hybrid"],
            "minimum_salary_cad": 0,
            "salary_filter_mode": "strict",
        },
    },
    {
        "id": "F",
        "name": "Strict Remote",
        "api": {
            "preferred_roles": ["Software Engineer"],
            "skills": ["Python", "Docker"],
            "years_experience": 4,
            "work_arrangements": ["remote"],
            "limit": 10,
        },
        "site": {
            "current_title": "Software Engineer",
            "desired_titles": ["Software Engineer"],
            "years_experience": 4,
            "skills": ["Python", "Docker"],
            "disciplines": ["software_engineering"],
            "seniority": ["mid"],
            "work_arrangements": ["remote"],
            "preferred_locations": ["Canada"],
            "minimum_salary_cad": 0,
            "salary_filter_mode": "strict",
        },
    },
    {
        "id": "G",
        "name": "Senior AI Engineer",
        "api": {
            "preferred_roles": ["AI Engineer", "ML Engineer"],
            "years_experience": 5,
            "skills": ["Python", "RAG", "LangChain", "LLM", "OpenAI"],
            "work_arrangements": ["remote", "hybrid"],
            "preferred_locations": ["Toronto"],
            "limit": 10,
        },
        "site": {
            "current_title": "AI Engineer",
            "desired_titles": ["AI Engineer", "ML Engineer"],
            "years_experience": 5,
            "skills": ["Python", "RAG", "LangChain", "LLM"],
            "disciplines": ["ai_engineering", "ml_engineering"],
            "seniority": ["senior"],
            "work_arrangements": ["remote", "hybrid"],
            "preferred_locations": ["Toronto", "ON"],
            "minimum_salary_cad": 0,
            "salary_filter_mode": "strict",
        },
    },
    {
        "id": "H",
        "name": "DevOps Engineer",
        "api": {
            "preferred_roles": ["DevOps Engineer", "SRE"],
            "years_experience": 6,
            "skills": [
                "Terraform",
                "Kubernetes",
                "Helm",
                "GitHub Actions",
                "Prometheus",
                "Grafana",
            ],
            "work_arrangements": ["remote", "hybrid"],
            "limit": 10,
        },
        "site": {
            "current_title": "DevOps Engineer",
            "desired_titles": ["DevOps Engineer", "Site Reliability Engineer"],
            "years_experience": 6,
            "skills": [
                "Terraform",
                "Kubernetes",
                "Helm",
                "GitHub Actions",
                "Prometheus",
                "Grafana",
            ],
            "disciplines": ["devops_sre", "platform_engineering"],
            "seniority": ["senior"],
            "work_arrangements": ["remote", "hybrid"],
            "minimum_salary_cad": 0,
            "salary_filter_mode": "strict",
        },
    },
    {
        "id": "I",
        "name": "Backend Engineer",
        "api": {
            "preferred_roles": ["Backend Engineer"],
            "years_experience": 4,
            "skills": ["Java", "Spring Boot", "PostgreSQL", "Redis", "Kafka"],
            "work_arrangements": ["remote", "hybrid"],
            "limit": 10,
        },
        "site": {
            "current_title": "Backend Engineer",
            "desired_titles": ["Backend Engineer"],
            "years_experience": 4,
            "skills": ["Java", "Spring Boot", "PostgreSQL", "Redis", "Kafka"],
            "disciplines": ["software_engineering"],
            "seniority": ["mid"],
            "work_arrangements": ["remote", "hybrid"],
            "minimum_salary_cad": 0,
            "salary_filter_mode": "strict",
        },
    },
    {
        "id": "J",
        "name": "New Graduate",
        "api": {
            "preferred_roles": ["Software Engineer"],
            "years_experience": 0,
            "skills": ["Python", "JavaScript", "SQL"],
            "seniority": "junior",
            "work_arrangements": ["remote", "hybrid"],
            "limit": 10,
        },
        "site": {
            "current_title": "Software Engineer",
            "desired_titles": ["Software Engineer", "Junior Software Engineer"],
            "years_experience": 0,
            "skills": ["Python", "JavaScript", "SQL"],
            "disciplines": ["software_engineering"],
            "seniority": ["junior"],
            "work_arrangements": ["remote", "hybrid"],
            "minimum_salary_cad": 0,
            "salary_filter_mode": "strict",
        },
    },
]


def _http_json(url: str, *, method: str = "GET", body: dict | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    req = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "User-Agent": "GitHired-persona-qa/1.0", "Accept": "application/json, text/event-stream"},
    )
    with urlopen(req, timeout=30) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8", errors="replace")
        if "data:" in raw and raw.strip().startswith("event:"):
            # SSE: take last JSON payload
            for line in reversed(raw.splitlines()):
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
        return json.loads(raw)


def site_match(profile: dict[str, Any], snapshot_path: Path) -> list[dict[str, Any]]:
    # Use Node match-engine against local snapshot
    script = f"""
const M=require({json.dumps(str(ROOT / "site" / "match-engine.js"))});
const snap=require({json.dumps(str(snapshot_path))});
const profile={json.dumps(profile)};
const full={{...M.emptyProfile(), ...profile}};
const r=M.matchJobs(full, snap.jobs, {{limit:10, fx: snap.usd_to_cad || 1.35}});
console.log(JSON.stringify(r.map(x=>({{
  id:x.job.id, title:x.job.title, company:x.job.company, percent:x.match.percent,
  work_arrangement:x.job.work_arrangement, matched:x.match.matched_skills,
  unconfirmed:x.match.unconfirmed_skills, reasons:x.match.reasons.slice(0,3)
}}))));
"""
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def compact(matches: list[dict[str, Any]], *, score_key: str) -> list[dict[str, Any]]:
    out = []
    for m in matches[:5]:
        out.append(
            {
                "id": m.get("id"),
                "title": m.get("title"),
                "company": m.get("company"),
                "score": m.get(score_key),
                "work_arrangement": m.get("work_arrangement"),
                "matching_skills": m.get("matching_skills") or m.get("matched"),
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--snapshot", type=Path, default=ROOT / "api" / "data" / "jobs.snapshot.json")
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "match_persona_qa.json")
    args = ap.parse_args()

    # Bundle API match for local parity
    bundle = Path(tempfile.gettempdir()) / "githired-match-qa.mjs"
    subprocess.run(
        [
            "npx",
            "--yes",
            "esbuild",
            str(ROOT / "api" / "src" / "match.ts"),
            "--bundle",
            "--platform=neutral",
            "--format=esm",
            f"--outfile={bundle}",
        ],
        cwd=str(ROOT / "api"),
        check=True,
        capture_output=True,
    )

    report: dict[str, Any] = {"personas": [], "live": bool(args.live)}
    snap = json.loads(args.snapshot.read_text())

    for persona in PERSONAS:
        entry: dict[str, Any] = {"id": persona["id"], "name": persona["name"]}
        # Local API matchProfile
        node = f"""
import {{ readFileSync }} from 'fs';
import {{ matchProfile }} from {json.dumps(bundle.as_uri())};
const snap=JSON.parse(readFileSync({json.dumps(str(args.snapshot))},'utf8'));
const r=matchProfile(snap, {json.dumps(persona["api"])});
console.log(JSON.stringify({{count:r.matches.length, semantics:r.filter_semantics, top:r.matches.slice(0,5)}}));
"""
        proc = subprocess.run(
            ["node", "--input-type=module", "-e", node],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            entry["local_api_error"] = proc.stderr
        else:
            local_api = json.loads(proc.stdout)
            entry["local_api"] = {
                "count": local_api["count"],
                "semantics": local_api.get("semantics"),
                "top5": compact(local_api["top"], score_key="match_score"),
            }

        site = site_match(persona["site"], args.snapshot)
        entry["website"] = {
            "count": len(site),
            "top5": [
                {
                    "id": s.get("id"),
                    "title": s.get("title"),
                    "company": s.get("company"),
                    "score": s.get("percent"),
                    "work_arrangement": s.get("work_arrangement"),
                    "matching_skills": s.get("matched"),
                }
                for s in site[:5]
            ],
            "arrangements": sorted({s.get("work_arrangement") for s in site}),
        }

        # Observations
        notes = []
        if persona["id"] == "F":
            bad = [s for s in site if s.get("work_arrangement") in ("hybrid", "onsite")]
            notes.append("strict_remote_ok" if not bad else f"strict_remote_fail:{len(bad)}")
        if persona["id"] == "E":
            invented = [
                s
                for s in site
                if "Control-M" in (s.get("matched") or [])
                and "Control-M" not in str(s.get("reasons"))
            ]
            # matched Control-M only if evidenced
            notes.append(
                "control_m_matched="
                + str(sum(1 for s in site if "Control-M" in (s.get("matched") or [])))
            )
        if persona["id"] in ("B", "J"):
            staffish = [
                s
                for s in site
                if any(x in (s.get("title") or "").lower() for x in ("staff", "principal"))
            ]
            if staffish and site:
                notes.append(
                    f"staff_or_principal_present scores={[s.get('percent') for s in staffish[:3]]} vs top={site[0].get('percent')}"
                )
        entry["notes"] = notes

        if args.live:
            try:
                api = _http_json(
                    "https://api.githired.ca/api/v1/match",
                    method="POST",
                    body=persona["api"],
                )
                entry["live_api"] = {
                    "count": len(api.get("matches") or []),
                    "dataset_id": api.get("dataset_id"),
                    "top5": compact(api.get("matches") or [], score_key="match_score"),
                }
                mcp = _http_json(
                    "https://api.githired.ca/mcp",
                    method="POST",
                    body={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "match_profile", "arguments": persona["api"]},
                    },
                )
                text = ((mcp.get("result") or {}).get("content") or [{}])[0].get("text") or "{}"
                payload = json.loads(text)
                entry["live_mcp"] = {
                    "count": len(payload.get("matches") or []),
                    "dataset_id": payload.get("dataset_id"),
                    "top5": compact(payload.get("matches") or [], score_key="match_score"),
                }
            except Exception as exc:  # noqa: BLE001
                entry["live_error"] = str(exc)

        report["personas"].append(entry)

    report["snapshot"] = {
        "path": str(args.snapshot),
        "dataset_id": snap.get("dataset_id"),
        "job_count": len(snap.get("jobs") or []),
        "generated_at": snap.get("generated_at"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"personas": len(report["personas"]), "out": str(args.out)}, indent=2))
    for p in report["personas"]:
        wa = p.get("website", {})
        la = p.get("local_api", {})
        print(
            f"Persona {p['id']} {p['name']}: site={wa.get('count')} api={la.get('count')} notes={p.get('notes')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
