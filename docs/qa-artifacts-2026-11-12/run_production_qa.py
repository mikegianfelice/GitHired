#!/usr/bin/env python3
"""Reproducible GitHired production QA harness (2026-11-12).

Usage:
  python3 docs/qa-artifacts-2026-11-12/run_production_qa.py
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.githired.ca"
SITE = "https://githired.ca"
OUT = Path(__file__).resolve().parent
UA = "GitHired-QA/2026-11-12 (+independent-assessment)"


PROFILES = [
    {
        "id": "P01",
        "name": "Junior Python Developer",
        "years": 1,
        "skills": ["Python"],
        "roles": ["Junior Python Developer", "Python Developer", "Software Engineer"],
        "locations": ["Toronto"],
        "arrangements": ["hybrid", "remote", "onsite"],
        "remote_preference": False,
        "minimum_salary": 65000,
        "seniority": "junior",
        "notes": "Toronto hybrid, junior, $65k+",
    },
    {
        "id": "P02",
        "name": "Senior Data Engineer",
        "years": 6,
        "skills": ["Python", "SQL", "Spark"],
        "roles": ["Senior Data Engineer", "Data Engineer"],
        "locations": ["Canada"],
        "arrangements": ["remote"],
        "remote_preference": True,
        "minimum_salary": 150000,
        "seniority": "senior",
        "notes": "Remote Canada, $150k+",
    },
    {
        "id": "P03",
        "name": "Frontend Developer",
        "years": 3,
        "skills": ["React", "TypeScript"],
        "roles": ["Frontend Developer", "Frontend Engineer", "Software Engineer"],
        "locations": ["Vancouver"],
        "arrangements": ["remote", "hybrid", "onsite"],
        "remote_preference": False,
        "minimum_salary": 90000,
        "seniority": "mid",
        "notes": "Vancouver, React/TS, $90k+",
    },
    {
        "id": "P04",
        "name": "Staff AI Engineer",
        "years": 9,
        "skills": ["LLM", "RAG", "AWS"],
        "roles": ["AI Engineer", "Staff AI Engineer", "Machine Learning Engineer"],
        "locations": ["Canada"],
        "arrangements": ["remote"],
        "remote_preference": True,
        "minimum_salary": 200000,
        "seniority": "staff",
        "notes": "Remote Canada, LLMs/RAG, $200k+",
    },
    {
        "id": "P05",
        "name": "DevOps Engineer",
        "years": 5,
        "skills": ["Kubernetes", "Terraform", "AWS"],
        "roles": ["DevOps Engineer", "SRE", "Platform Engineer"],
        "locations": ["Calgary"],
        "arrangements": ["remote", "hybrid", "onsite"],
        "remote_preference": False,
        "minimum_salary": 130000,
        "seniority": "senior",
        "notes": "Calgary, K8s/TF/AWS, $130k+",
    },
    {
        "id": "P06",
        "name": "Data Analyst",
        "years": 2,
        "skills": ["SQL", "Power BI"],
        "roles": ["Data Analyst", "Analytics Engineer"],
        "locations": ["Montreal"],
        "arrangements": ["remote", "hybrid", "onsite"],
        "remote_preference": False,
        "minimum_salary": 75000,
        "seniority": "mid",
        "notes": "Montreal, SQL/Power BI — niche vs eng-heavy inventory",
    },
    {
        "id": "P07",
        "name": "Cybersecurity Engineer",
        "years": 7,
        "skills": ["SIEM", "Security", "AWS"],
        "roles": ["Security Engineer", "Cybersecurity Engineer"],
        "locations": ["Ottawa"],
        "arrangements": ["remote", "hybrid", "onsite"],
        "remote_preference": False,
        "minimum_salary": 140000,
        "seniority": "senior",
        "notes": "Ottawa security — niche vs SE inventory",
    },
    {
        "id": "P08",
        "name": "Backend Engineer",
        "years": 4,
        "skills": ["Java", "Spring Boot"],
        "roles": ["Backend Engineer", "Software Engineer"],
        "locations": ["Toronto"],
        "arrangements": ["remote", "hybrid", "onsite"],
        "remote_preference": False,
        "minimum_salary": 110000,
        "seniority": "mid",
        "notes": "Toronto Java/Spring, $110k+",
    },
    {
        "id": "P09",
        "name": "Career Switcher",
        "years": 0,
        "skills": ["Python", "SQL"],
        "roles": ["Junior Software Engineer", "Software Engineer", "Data Engineer"],
        "locations": ["Canada"],
        "arrangements": ["remote"],
        "remote_preference": True,
        "minimum_salary": None,
        "seniority": "junior",
        "notes": "0 YOE remote Canada — expect sparse junior inventory",
    },
    {
        "id": "P10",
        "name": "Senior Solutions Architect",
        "years": 8,
        "skills": ["Databricks", "AWS", "Azure"],
        "roles": ["Solutions Architect", "Solution Architect", "Forward Deployed Engineer"],
        "locations": ["Canada"],
        "arrangements": ["remote", "hybrid"],
        "remote_preference": False,
        "minimum_salary": 170000,
        "seniority": "senior",
        "notes": "Customer-facing / Databricks / cloud, $170k+",
    },
]


def http(method: str, url: str, body: dict | None = None, timeout: float = 30.0) -> dict:
    data = None
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = {"_raw": raw.decode("utf-8", errors="replace")[:2000]}
            return {
                "ok": True,
                "status": resp.status,
                "elapsed_ms": elapsed_ms,
                "url": url,
                "body": payload,
                "bytes": len(raw),
            }
    except urllib.error.HTTPError as e:
        raw = e.read()
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {"_raw": raw.decode("utf-8", errors="replace")[:2000]}
        return {
            "ok": False,
            "status": e.code,
            "elapsed_ms": elapsed_ms,
            "url": url,
            "body": payload,
            "bytes": len(raw),
            "error": str(e),
        }
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "ok": False,
            "status": None,
            "elapsed_ms": elapsed_ms,
            "url": url,
            "body": None,
            "error": f"{type(e).__name__}: {e}",
        }


def match_body(p: dict) -> dict:
    body = {
        "skills": p["skills"],
        "years_experience": p["years"],
        "preferred_roles": p["roles"],
        "preferred_locations": p["locations"],
        "work_arrangements": p["arrangements"],
        "remote_preference": p["remote_preference"],
        "seniority": p["seniority"],
        "limit": 10,
        "salary_mode": "flexible",
    }
    if p["minimum_salary"] is not None:
        body["minimum_salary"] = p["minimum_salary"]
    return body


def assess_match(p: dict, m: dict) -> dict:
    issues = []
    goods = []
    score = m.get("match_score")
    title = (m.get("title") or "").lower()
    arr = m.get("work_arrangement")
    sal = m.get("salary_max_cad")
    skills = set(s.lower() for s in (m.get("matching_skills") or []))

    # Arrangement
    if p["arrangements"] and arr and arr not in p["arrangements"] and arr != "unspecified":
        # unspecified is soft — note but don't hard-fail
        if arr not in p["arrangements"]:
            issues.append(f"arrangement={arr} outside preferred {p['arrangements']}")
    elif arr in p["arrangements"]:
        goods.append(f"arrangement={arr}")
    elif arr == "unspecified":
        goods.append("arrangement=unspecified (soft)")

    # Salary flexible: max may meet floor
    floor = p["minimum_salary"]
    if floor and sal is not None:
        if sal + 1 < floor:
            issues.append(f"salary_max_cad={sal} below floor {floor}")
        else:
            goods.append(f"salary_max_cad={sal} meets floor {floor}")
    elif floor and sal is None:
        goods.append("salary undisclosed (flexible mode keeps job)")

    # Seniority heuristic
    sen = p["seniority"]
    if sen == "junior" and any(x in title for x in ("staff", "principal", "director", "vp ")):
        issues.append("junior candidate matched very senior title")
    if sen == "staff" and any(x in title for x in ("junior", "intern", "new grad", "co-op", "coop")):
        issues.append("staff candidate matched junior/intern title")
    if sen == "senior" and "intern" in title:
        issues.append("senior matched intern")

    # Skills
    wanted = {s.lower() for s in p["skills"]}
    hit = wanted & skills
    if hit:
        goods.append(f"skills_hit={sorted(hit)}")
    elif not skills:
        issues.append("no matching_skills reported")

    # Geography soft check
    loc = (m.get("location") or "").lower()
    prefs = [x.lower() for x in p["locations"]]
    if any(x in loc for x in prefs) or "canada" in loc or "remote" in loc:
        goods.append("geo_plausible")
    else:
        goods.append(f"geo_check_loc={m.get('location')}")

    verdict = "GOOD"
    if any("below floor" in i or "junior candidate matched very senior" in i for i in issues):
        verdict = "WEAK"
    if len(issues) >= 3:
        verdict = "POOR"
    return {"verdict": verdict, "goods": goods, "issues": issues, "score": score}


def check_apply_url(url: str, timeout: float = 12.0) -> dict:
    if not url or not url.startswith("http"):
        return {"status": "INVALID", "code": None, "final": None}
    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"status": "OK", "code": resp.status, "final": resp.geturl()}
    except urllib.error.HTTPError as e:
        # Some ATS reject HEAD — try GET light
        if e.code in (403, 405, 400):
            try:
                req2 = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
                with urllib.request.urlopen(req2, timeout=timeout) as resp:
                    return {"status": "OK_GET", "code": resp.status, "final": resp.geturl()}
            except Exception as e2:
                return {"status": "FAIL", "code": getattr(e2, "code", None), "error": str(e2)}
        return {"status": "HTTP_ERROR", "code": e.code, "error": str(e)}
    except Exception as e:
        return {"status": "FAIL", "code": None, "error": f"{type(e).__name__}: {e}"}


def main() -> int:
    report: dict = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api_base": API,
        "site_base": SITE,
        "connectivity": {},
        "edge_cases": {},
        "profiles": {},
        "data_quality": {},
        "consistency_notes": [],
    }

    # Connectivity
    for name, url in [
        ("health", f"{API}/api/v1/health"),
        ("stats", f"{API}/api/v1/stats"),
        ("companies", f"{API}/api/v1/companies"),
        ("api_root", f"{API}/api/v1"),
        ("openapi", f"{SITE}/openapi.json"),
        ("jobs_json", f"{SITE}/jobs.json"),
        ("site_index", f"{SITE}/"),
        ("mcp_get", f"{API}/mcp"),
    ]:
        report["connectivity"][name] = http("GET", url)

    health = report["connectivity"]["health"]["body"] or {}
    dataset_id = (health.get("dataset") or {}).get("dataset_id")
    dataset_count = (health.get("dataset") or {}).get("count")
    report["dataset_id"] = dataset_id
    report["dataset_count"] = dataset_count

    # Edge cases
    edges = {
        "jobs_empty_q": http("GET", f"{API}/api/v1/jobs?q=zzzznonexistentxyz&limit=5"),
        "jobs_salary_boundary": http("GET", f"{API}/api/v1/jobs?salary_min=900000&limit=5"),
        "jobs_invalid_work_mode": http("GET", f"{API}/api/v1/jobs?work_mode=telepathy&limit=5"),
        "jobs_pagination": http("GET", f"{API}/api/v1/jobs?limit=2&sort=salary"),
        "job_not_found": http("GET", f"{API}/api/v1/jobs/does-not-exist-xyz"),
        "match_invalid_json": http("POST", f"{API}/api/v1/match", body=None),  # will send no body oddly
        "match_empty": http("POST", f"{API}/api/v1/match", body={}),
        "jobs_remote_true": http("GET", f"{API}/api/v1/jobs?remote=true&limit=5"),
        "jobs_province_on": http("GET", f"{API}/api/v1/jobs?province=ON&limit=5"),
        "jobs_work_hybrid": http("GET", f"{API}/api/v1/jobs?work_mode=hybrid&limit=5"),
    }
    # Fix invalid JSON case with raw request
    req = urllib.request.Request(
        f"{API}/api/v1/match",
        data=b"not-json",
        headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            edges["match_invalid_json"] = {
                "ok": True,
                "status": resp.status,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                "body": json.loads(resp.read().decode()),
            }
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw.decode())
        except Exception:
            body = raw.decode(errors="replace")[:500]
        edges["match_invalid_json"] = {
            "ok": False,
            "status": e.code,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
            "body": body,
        }
    except Exception as e:
        edges["match_invalid_json"] = {"ok": False, "error": str(e)}

    # Pagination page 2
    page1 = edges["jobs_pagination"]["body"] or {}
    cursor = page1.get("next_cursor")
    if cursor:
        edges["jobs_pagination_page2"] = http(
            "GET", f"{API}/api/v1/jobs?limit=2&sort=salary&cursor={urllib.parse.quote(cursor)}"
        )
    report["edge_cases"] = edges

    # Profile matches via REST
    all_match_ids = []
    for p in PROFILES:
        body = match_body(p)
        r = http("POST", f"{API}/api/v1/match", body=body)
        matches = (r.get("body") or {}).get("matches") or []
        assessed = []
        for m in matches:
            a = assess_match(p, m)
            assessed.append({**{k: m.get(k) for k in (
                "id", "title", "company", "location", "work_arrangement",
                "match_score", "matching_skills", "salary_max_cad", "apply_url",
                "last_verified", "explanation",
            )}, "assessment": a})
            all_match_ids.append(m.get("id"))
        # Also keyword search analog
        q = p["roles"][0]
        search = http(
            "GET",
            f"{API}/api/v1/jobs?{urllib.parse.urlencode({'q': q, 'limit': 10, 'sort': 'relevance'})}",
        )
        report["profiles"][p["id"]] = {
            "profile": p,
            "match_request": body,
            "match_response_meta": {
                "status": r.get("status"),
                "elapsed_ms": r.get("elapsed_ms"),
                "dataset_id": (r.get("body") or {}).get("dataset_id"),
                "filter_semantics": (r.get("body") or {}).get("filter_semantics"),
                "note": (r.get("body") or {}).get("note"),
                "match_count": len(matches),
            },
            "matches": assessed,
            "search_analog": {
                "status": search.get("status"),
                "elapsed_ms": search.get("elapsed_ms"),
                "total": (search.get("body") or {}).get("total"),
                "ids": [j.get("id") for j in ((search.get("body") or {}).get("jobs") or [])],
            },
            "verdict_counts": Counter(a["assessment"]["verdict"] for a in assessed),
        }

    # Data quality sample: top salary jobs + remote + hybrid + by source
    jobs_all = http("GET", f"{API}/api/v1/jobs?limit=50&sort=salary")
    jobs = (jobs_all.get("body") or {}).get("jobs") or []
    by_source = Counter(j.get("source") for j in jobs)
    # Fetch more diverse via different queries
    samples = []
    for q, mode in [
        ("engineer", None),
        ("data", "remote"),
        ("platform", "hybrid"),
        ("security", None),
        ("frontend", None),
    ]:
        params = {"q": q, "limit": 10, "sort": "freshness"}
        if mode:
            params["work_mode"] = mode
        r = http("GET", f"{API}/api/v1/jobs?{urllib.parse.urlencode(params)}")
        for j in (r.get("body") or {}).get("jobs") or []:
            samples.append(j)

    # Deduplicate samples by id
    seen = set()
    uniq = []
    for j in samples:
        if j["id"] in seen:
            continue
        seen.add(j["id"])
        uniq.append(j)

    # Detail + apply URL checks for up to 25 jobs across sources
    by_src = defaultdict(list)
    for j in uniq:
        by_src[j.get("source") or "unknown"].append(j)
    pick = []
    for src, lst in by_src.items():
        pick.extend(lst[:4])
    pick = pick[:25]

    link_checks = []
    salary_flags = []
    detail_missing = []
    for j in pick:
        detail = http("GET", f"{API}/api/v1/jobs/{j['id']}")
        job = (detail.get("body") or {}).get("job") or {}
        excerpt = job.get("description_excerpt")
        if not excerpt:
            detail_missing.append(j["id"])
        if job.get("salary_kind") not in (None, "advertised_base", "undisclosed"):
            salary_flags.append({"id": j["id"], "salary_kind": job.get("salary_kind")})
        if job.get("salary_available") and job.get("salary_kind") != "advertised_base":
            salary_flags.append({"id": j["id"], "issue": "available_but_not_advertised_base", "kind": job.get("salary_kind")})
        link = check_apply_url(job.get("apply_url") or j.get("apply_url") or "")
        link_checks.append({
            "id": j["id"],
            "company": j.get("company"),
            "title": j.get("title"),
            "source": j.get("source"),
            "apply_url": job.get("apply_url") or j.get("apply_url"),
            "work_arrangement": j.get("work_arrangement"),
            "location": j.get("location"),
            "salary_available": job.get("salary_available"),
            "salary_kind": job.get("salary_kind"),
            "salary_max_cad": job.get("salary_max_cad"),
            "link_check": link,
            "has_excerpt": bool(excerpt),
        })

    # Duplicate check on site jobs.json
    site_jobs = (report["connectivity"]["jobs_json"].get("body") or {}).get("jobs") or []
    key_counts = Counter((j.get("company", "").casefold(), j.get("title", "").casefold()) for j in site_jobs)
    dups = [k for k, v in key_counts.items() if v > 1]

    # US-only remote smell in published inventory
    us_smell = []
    for j in site_jobs:
        loc = (j.get("location") or "")
        if j.get("work_arrangement") == "remote" and (
            "united states" in loc.lower() or loc.lower().endswith(", usa") or "remote, us" in loc.lower()
        ):
            us_smell.append({"id": j.get("id"), "location": loc, "company": j.get("company")})

    report["data_quality"] = {
        "site_job_count": len(site_jobs),
        "api_health_count": dataset_count,
        "count_delta_site_vs_health": abs(len(site_jobs) - (dataset_count or 0)),
        "sources_in_salary_sample": dict(by_source),
        "link_checks": link_checks,
        "link_summary": Counter(x["link_check"]["status"] for x in link_checks),
        "salary_flags": salary_flags,
        "missing_excerpts": detail_missing,
        "company_title_duplicates": [{"company": a, "title": b} for a, b in dups[:20]],
        "us_remote_smell": us_smell[:20],
        "arrangement_breakdown": dict(Counter(j.get("work_arrangement") for j in site_jobs)),
    }

    # Site vs API ID overlap for first page
    api_first = http("GET", f"{API}/api/v1/jobs?limit=20&sort=salary")
    api_ids = [j["id"] for j in ((api_first.get("body") or {}).get("jobs") or [])]
    site_sorted = sorted(
        site_jobs,
        key=lambda j: (0 if j.get("salary_available") else 1, -(j.get("salary_max_cad") or 0)),
    )
    site_ids = [j["id"] for j in site_sorted[:20]]
    report["consistency_notes"] = {
        "api_top20_salary_ids": api_ids,
        "site_top20_salary_ids": site_ids,
        "top20_id_overlap": len(set(api_ids) & set(site_ids)),
        "dataset_id_health": dataset_id,
        "dataset_id_site": (report["connectivity"]["jobs_json"].get("body") or {}).get("dataset_id")
        or (report["connectivity"]["jobs_json"].get("body") or {}).get("generated_at"),
        "site_generated_at": (report["connectivity"]["jobs_json"].get("body") or {}).get("generated_at"),
        "api_jobs_generated_at": (api_first.get("body") or {}).get("generated_at"),
    }

    out_path = OUT / "production_qa_results.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "path": str(out_path),
        "dataset_id": dataset_id,
        "dataset_count": dataset_count,
        "site_count": len(site_jobs),
        "profiles": {pid: v["match_response_meta"]["match_count"] for pid, v in report["profiles"].items()},
        "link_summary": dict(report["data_quality"]["link_summary"]),
        "health_ms": report["connectivity"]["health"].get("elapsed_ms"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
