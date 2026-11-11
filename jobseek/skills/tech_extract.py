"""Deterministic technology extraction from job text.

Used by the public shortlist export and API snapshot. Extracts skill *labels*
only — never returns description text. No LLM dependency.

Design rules:
- Match explicit technology mentions (case-insensitive).
- Do not treat a platform mention as proof of every related skill
  (e.g. Snowflake ≠ SQL, Databricks ≠ Spark/SQL, AWS ≠ Terraform).
- Skip negated / explicitly-excluded mentions when detectable.
- Prefer precision over recall for short English words (Go, MCP, TF).
- Strip obvious recruiter placeholders before matching (do not mutate stored text).
"""

from __future__ import annotations

import html
import re
from typing import Iterable

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# Affirm-style recruiter template noise — extraction only, never persisted.
_PLACEHOLDER = re.compile(
    r"\[(?:INSERT|PLACEHOLDER|TODO|TBD|RECRUITER)[^\]]*\]",
    re.I,
)

# Canonical label → one or more search patterns.
# Keep this list as the single source of truth for export tagging.
_TECH_SPECS: list[tuple[str, tuple[str, ...]]] = [
    # Languages
    ("Python", (r"\bpython\b",)),
    ("TypeScript", (r"\btypescript\b",)),
    ("JavaScript", (r"\bjavascript\b",)),
    (
        "Go",
        (
            r"\bgolang\b",
            r"\bgo\s*lang\b",
            r"\bgo(?:lang)?\s+(?:engineer|developer|programmer|backend)\b",
            r"(?:languages?|stack|experience|proficien\w*|skills?)[:\s].{0,80}\bgo\b",
            r"\bgo\b(?:\s*[,/]\s*|\s+and\s+)(?:python|java|rust|ruby|typescript|kotlin|scala|c\+\+|c#)",
            r"(?:python|java|rust|ruby|typescript|kotlin|scala|c\+\+|c#)(?:\s*[,/]\s*|\s+and\s+)\bgo\b",
        ),
    ),
    ("Rust", (r"\brust\b",)),
    ("Java", (r"\bjava\b",)),
    ("Kotlin", (r"\bkotlin\b",)),
    ("C++", (r"\bc\+\+\b",)),
    ("C#", (r"\bc#\b", r"\bdotnet\b", r"\b\.net\b")),
    ("Ruby", (r"\bruby\b", r"\brails\b")),
    ("Scala", (r"\bscala\b",)),
    ("Swift", (r"\bswift\b",)),
    # Data / SQL family — SQL Server is separate from bare SQL.
    ("SQL", (r"\bsql\b", r"\bpl\/?sql\b")),
    (
        "SQL Server",
        (
            r"\bmicrosoft\s+sql\s*server\b",
            r"\bsql\s*server\b",
            r"\bmssql\b",
            r"\bms[\s\-]?sql\b",
            r"\bt-?sql\b",
        ),
    ),
    ("PostgreSQL", (r"\bpostgres(?:ql)?\b",)),
    ("MySQL", (r"\bmysql\b",)),
    ("Oracle", (r"\boracle\s+(?:db|database|sql)\b", r"\boracle\b")),
    ("MongoDB", (r"\bmongo(?:db)?\b",)),
    ("Redis", (r"\bredis(?:\s+cache)?\b",)),
    ("Elasticsearch", (r"\belasticsearch\b",)),
    ("OpenSearch", (r"\bopensearch\b",)),
    ("ClickHouse", (r"\bclickhouse\b",)),
    ("BigQuery", (r"\bbigquery\b", r"\bbig\s*query\b")),
    # Data platforms / pipelines
    ("PySpark", (r"\bpyspark\b",)),
    ("Spark", (r"\bapache\s+spark\b", r"\bpyspark\b", r"\bspark\b")),
    ("Kafka", (r"\bkafka\b", r"\bapache\s+kafka\b")),
    ("Airflow", (r"\bairflow\b", r"\bapache\s+airflow\b")),
    ("dbt", (r"\bdbt\b",)),
    ("Databricks", (r"\bdatabricks\b",)),
    ("Snowflake", (r"\bsnowflake\b",)),
    ("Delta Lake", (r"\bdelta\s*lake\b",)),
    ("Unity Catalog", (r"\bunity\s+catalog\b",)),
    ("Hadoop", (r"\bhadoop\b",)),
    (
        "Control-M",
        (
            r"\bcontrol[\s\-]?m\b",
            r"\bcontrolm\b",
            r"\bbmc\s+control[\s\-]?m\b",
        ),
    ),
    ("SSIS", (r"\bssis\b", r"\bsql\s+server\s+integration\s+services\b")),
    ("Informatica", (r"\binformatica\b",)),
    ("Power BI", (r"\bpower\s*bi\b",)),
    ("Tableau", (r"\btableau\b",)),
    # Cloud / infra
    ("Docker", (r"\bdocker\b",)),
    ("Kubernetes", (r"\bkubernetes\b", r"\bk8s\b")),
    ("Helm", (r"\bhelm\b",)),
    ("Ansible", (r"\bansible\b",)),
    ("Terraform", (r"\bterraform\b",)),  # do not match bare TF
    ("AWS", (r"\baws\b", r"\bamazon web services\b")),
    ("GCP", (r"\bgcp\b", r"\bgoogle cloud(?:\s+platform)?\b")),
    ("Azure", (r"\bazure\b",)),
    ("AWS Lambda", (r"\baws\s+lambda\b", r"\blambda\s+functions?\b")),
    ("S3", (r"\bamazon\s+s3\b", r"\baws\s+s3\b", r"\bs3\s+buckets?\b")),
    ("EKS", (r"\bamazon\s+eks\b", r"\baws\s+eks\b", r"\beks\b")),
    ("ECS", (r"\bamazon\s+ecs\b", r"\baws\s+ecs\b")),
    ("Azure Data Factory", (r"\bazure\s+data\s+factory\b",)),
    ("Azure DevOps", (r"\bazure\s+devops\b",)),
    ("GitHub Actions", (r"\bgithub\s+actions\b", r"\bgh\s+actions\b")),
    ("Jenkins", (r"\bjenkins\b",)),
    ("CI/CD", (r"\bci\s*/\s*cd\b", r"\bci-cd\b", r"\bci\s+cd\b")),
    ("Linux", (r"\blinux\b",)),
    ("Bash", (r"\bbash\b",)),
    ("Prometheus", (r"\bprometheus\b",)),
    ("Grafana", (r"\bgrafana\b",)),
    # Frontend / APIs
    ("React", (r"\breact(?:\.?js)?\b",)),
    ("Next.js", (r"\bnext\.?js\b",)),
    ("Node", (r"\bnode\.?js\b",)),
    ("GraphQL", (r"\bgraphql\b",)),
    ("gRPC", (r"\bgrpc\b",)),
    # AI / ML
    ("PyTorch", (r"\bpytorch\b",)),
    ("TensorFlow", (r"\btensorflow\b",)),
    ("scikit-learn", (r"\bscikit[\-\s]?learn\b", r"\bsklearn\b")),
    ("MLflow", (r"\bmlflow\b",)),
    ("Machine Learning", (r"\bmachine\s+learning\b",)),
    ("Deep Learning", (r"\bdeep\s+learning\b",)),
    ("LLM", (r"\bllm\b", r"\blarge language models?\b")),
    ("LangChain", (r"\blangchain\b",)),
    ("LangGraph", (r"\blanggraph\b",)),
    ("RAG", (r"\bretrieval[\-\s]augmented(?:\s+generation)?\b", r"\brag\b")),
    ("pgvector", (r"\bpgvector\b",)),
    ("Hugging Face", (r"\bhugging\s*face\b",)),
    (
        "MCP",
        (
            r"\bmodel\s+context\s+protocol\b",
            # Bare MCP only near AI/agent tooling cues — not generic "protocol".
            r"(?:ai\s+agents?|llm|claude|cursor|anthropic|openai|tool(?:ing)?\s+call).{0,48}\bmcp\b",
            r"\bmcp\b.{0,48}(?:ai\s+agents?|llm|tool(?:ing)?|claude|cursor|anthropic|openai)",
            r"\bmcp\s+servers?\b",  # common AI-agent phrasing
        ),
    ),
    # Security (avoid bare "security")
    (
        "Security",
        (
            r"\bappsec\b",
            r"\bdevsecops\b",
            r"\bsecurity engineer(?:ing)?\b",
            r"\bapplication security\b",
            r"\binformation security\b",
            r"\bcybersecurity\b",
        ),
    ),
]

_TECH_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (label, re.compile("|".join(f"(?:{p})" for p in pats), re.I))
    for label, pats in _TECH_SPECS
]

# Alias folding for match / display (profile ↔ job).
_SKILL_ALIASES: dict[str, str] = {
    "plsql": "SQL",
    "pl/sql": "SQL",
    "tsql": "SQL Server",
    "t-sql": "SQL Server",
    "t sql": "SQL Server",
    "sql server": "SQL Server",
    "sqlserver": "SQL Server",
    "mssql": "SQL Server",
    "ms sql": "SQL Server",
    "microsoft sql server": "SQL Server",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mongo": "MongoDB",
    "mongodb": "MongoDB",
    "redis cache": "Redis",
    "node.js": "Node",
    "nodejs": "Node",
    "node": "Node",
    "golang": "Go",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "amazon web services": "AWS",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    "gcp": "GCP",
    "pyspark": "PySpark",
    "apache spark": "Spark",
    "apache kafka": "Kafka",
    "apache airflow": "Airflow",
    "control m": "Control-M",
    "controlm": "Control-M",
    "control-m": "Control-M",
    "powerbi": "Power BI",
    "power bi": "Power BI",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "github actions": "GitHub Actions",
    "gh actions": "GitHub Actions",
    "ci cd": "CI/CD",
    "ci-cd": "CI/CD",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "machine learning": "Machine Learning",
    "deep learning": "Deep Learning",
    "model context protocol": "MCP",
    "hugging face": "Hugging Face",
    "delta lake": "Delta Lake",
    "unity catalog": "Unity Catalog",
    "big query": "BigQuery",
    "bigquery": "BigQuery",
}

# Exact-match related hits (profile skill → job skill). Conservative:
# compound skills may imply parents; broad skills do NOT imply specifics.
_RELATED: dict[str, frozenset[str]] = {
    # Profile PostgreSQL may satisfy a job that only listed SQL.
    "PostgreSQL": frozenset({"SQL"}),
    "MySQL": frozenset({"SQL"}),
    "SQL Server": frozenset({"SQL"}),
    # PySpark implies Python + Spark for the person.
    "PySpark": frozenset({"Python", "Spark"}),
    "Node": frozenset({"JavaScript"}),
    "JavaScript": frozenset({"Node"}),
}

# Expand exported job tags only (compound / alias), not the full related graph.
# Do NOT expand PostgreSQL→SQL here — that would make profile SQL an exact hit.
_JOB_EXPAND: dict[str, frozenset[str]] = {
    "PySpark": frozenset({"Python", "Spark"}),
    "SQL Server": frozenset({"SQL"}),
    "Node": frozenset({"Node"}),
}

_NEGATION_BEFORE = re.compile(
    r"(?:"
    r"\bno\b|"
    r"\bwithout\b|"
    r"\bnor\b|"
    r"\bneither\b|"
    r"does\s+not\s+require|"
    r"do\s+not\s+require|"
    r"don'?t\s+require|"
    r"not\s+(?:be\s+)?required|"
    r"not\s+needed|"
    r"excluding|"
    r"except(?:\s+for)?"
    r")[\w\s,/\-+.&]{0,48}$",
    re.I,
)

_NEGATION_AFTER = re.compile(
    r"^\s*(?:experience\s+|knowledge\s+|skills?\s+)?"
    r"(?:is\s+|are\s+|was\s+|were\s+)?"
    r"(?:not|never)\s+(?:required|needed|necessary|expected|a\s+must)",
    re.I,
)


def plain_text(*texts: str | None) -> str:
    """Join fragments and strip HTML to a single whitespace-normalized string."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return ""
    plain = _TAG.sub(" ", html.unescape(blob))
    plain = _PLACEHOLDER.sub(" ", plain)
    return _WS.sub(" ", plain).strip()


def normalize_skill_label(skill: str | None) -> str:
    """Canonicalize a skill string for comparison."""
    raw = str(skill or "").strip()
    if not raw:
        return ""
    folded = raw.casefold().replace("_", " ")
    spaced = re.sub(r"[\-/]+", " ", folded)
    spaced = re.sub(r"\s+", " ", spaced).strip()
    compact = re.sub(r"[\s\-/]+", "", folded)
    for candidate in (folded, spaced, compact, folded.replace("-", "")):
        if candidate in _SKILL_ALIASES:
            return _SKILL_ALIASES[candidate]
    # Preserve known canonical casing from the dictionary.
    for label, _ in _TECH_SPECS:
        lab = label.casefold()
        if lab == folded or lab == spaced or re.sub(r"[\s\-/]+", "", lab) == compact:
            return label
    return raw


def _sentence_bounds(blob: str, pos: int) -> tuple[int, int]:
    """Return [start, end) of the sentence containing ``pos``."""
    start = pos
    while start > 0 and blob[start - 1] not in ".!?\n":
        start -= 1
    end = pos
    while end < len(blob) and blob[end] not in ".!?\n":
        end += 1
    return start, end


def _is_negated(blob: str, start: int, end: int) -> bool:
    sent_start, sent_end = _sentence_bounds(blob, start)
    sentence = blob[sent_start:sent_end]
    local = start - sent_start
    before = sentence[:local]
    after = sentence[local + (end - start) :]
    if len(before) > 48:
        before = before[-48:]
    if _NEGATION_BEFORE.search(before):
        return True
    if _NEGATION_AFTER.match(after):
        return True
    return False


def extract_technologies(*texts: str | None) -> list[str]:
    """Return ordered unique technology labels evidenced in the given texts.

    Pass title, location, and full description. Empty / missing description is
    fine — extraction simply has less evidence (no fabricated tags).
    """
    blob = plain_text(*texts)
    if not blob:
        return []

    found: list[str] = []
    seen: set[str] = set()
    for label, pattern in _TECH_PATTERNS:
        matched = False
        for m in pattern.finditer(blob):
            if _is_negated(blob, m.start(), m.end()):
                continue
            matched = True
            break
        if matched and label not in seen:
            seen.add(label)
            found.append(label)

    # PySpark implies Python + Spark for export (explicit compound skill).
    if "PySpark" in seen:
        for extra in ("Python", "Spark"):
            if extra not in seen:
                seen.add(extra)
                found.append(extra)

    return found


def skills_overlap(
    profile_skills: Iterable[str],
    job_skills: Iterable[str],
) -> tuple[list[str], list[str]]:
    """Compare profile skills to job skills.

    Returns (matched, unconfirmed). Unconfirmed means the listing did not
    evidence the skill — not a confirmed gap.

    Exact matches only (plus conservative one-hop related). Profile SQL does
    not count as an exact PostgreSQL match.
    """
    job_norm = {normalize_skill_label(s) for s in job_skills if normalize_skill_label(s)}
    expanded = set(job_norm)
    for js in list(job_norm):
        expanded |= _JOB_EXPAND.get(js, frozenset())

    matched: list[str] = []
    unconfirmed: list[str] = []
    seen_m: set[str] = set()
    for raw in profile_skills:
        skill = normalize_skill_label(raw)
        if not skill:
            continue
        related = _RELATED.get(skill, frozenset())
        hit = skill in expanded or bool(related & expanded)
        if hit:
            if skill not in seen_m:
                seen_m.add(skill)
                matched.append(skill)
        else:
            unconfirmed.append(skill)
    return matched, unconfirmed


def known_skill_labels() -> list[str]:
    """Canonical labels recognized by the extractor (for tests/docs)."""
    return [label for label, _ in _TECH_SPECS]
