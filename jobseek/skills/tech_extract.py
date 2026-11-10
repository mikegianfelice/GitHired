"""Deterministic technology extraction from job text.

Used by the public shortlist export and API snapshot. Extracts skill *labels*
only — never returns description text. No LLM dependency.

Design rules:
- Match explicit technology mentions (case-insensitive).
- Do not treat a platform mention as proof of every related skill
  (e.g. Snowflake ≠ SQL, Databricks ≠ Spark/SQL).
- Skip negated / explicitly-excluded mentions when detectable.
- Prefer precision over recall for short English words (Go, Java vs JavaScript).
"""

from __future__ import annotations

import html
import re
from typing import Iterable

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# Canonical label → one or more search patterns.
# Order matters only for documentation; extraction is set-based then sorted stably.
_TECH_SPECS: list[tuple[str, tuple[str, ...]]] = [
    ("Python", (r"\bpython\b", r"\bpyspark\b")),
    ("TypeScript", (r"\btypescript\b",)),
    ("JavaScript", (r"\bjavascript\b",)),
    # Prefer golang / "Go engineer" / Go listed with peer languages — avoid "we go".
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
    # Word-boundary java does not match javascript.
    ("Java", (r"\bjava\b",)),
    ("Kotlin", (r"\bkotlin\b",)),
    ("C++", (r"\bc\+\+\b",)),
    ("C#", (r"\bc#\b", r"\bdotnet\b", r"\b\.net\b")),
    ("Ruby", (r"\bruby\b", r"\brails\b")),
    ("Scala", (r"\bscala\b",)),
    ("Swift", (r"\bswift\b",)),
    # SQL dialects normalize to SQL. Do NOT include postgres/mysql/snowflake here.
    (
        "SQL",
        (
            r"\bt-?sql\b",
            r"\bpl\/?sql\b",
            r"\bmicrosoft\s+sql\s*server\b",
            r"\bsql\s*server\b",
            r"\bsql\b",
        ),
    ),
    ("PostgreSQL", (r"\bpostgres(?:ql)?\b",)),
    ("MySQL", (r"\bmysql\b",)),
    ("PySpark", (r"\bpyspark\b",)),
    ("Spark", (r"\bapache\s+spark\b", r"\bpyspark\b", r"\bspark\b")),
    ("Kafka", (r"\bkafka\b", r"\bapache\s+kafka\b")),
    ("Airflow", (r"\bairflow\b", r"\bapache\s+airflow\b")),
    ("dbt", (r"\bdbt\b",)),
    ("Databricks", (r"\bdatabricks\b",)),
    ("Snowflake", (r"\bsnowflake\b",)),
    ("Docker", (r"\bdocker\b",)),
    ("Kubernetes", (r"\bkubernetes\b", r"\bk8s\b")),
    ("AWS", (r"\baws\b", r"\bamazon web services\b")),
    ("GCP", (r"\bgcp\b", r"\bgoogle cloud\b")),
    ("Azure", (r"\bazure\b",)),
    ("Terraform", (r"\bterraform\b",)),
    ("React", (r"\breact(?:\.?js)?\b",)),
    ("Node", (r"\bnode\.?js\b",)),
    ("PyTorch", (r"\bpytorch\b",)),
    ("TensorFlow", (r"\btensorflow\b",)),
    ("LLM", (r"\bllm\b", r"\blarge language models?\b")),
    # Avoid bare "security" (too common in generic eng posts).
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
    "tsql": "SQL",
    "t-sql": "SQL",
    "plsql": "SQL",
    "pl/sql": "SQL",
    "sql server": "SQL",
    "sqlserver": "SQL",
    "microsoft sql server": "SQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "node.js": "Node",
    "nodejs": "Node",
    "node": "Node",
    "golang": "Go",
    "k8s": "Kubernetes",
    "amazon web services": "AWS",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    "pyspark": "PySpark",
}

# One-hop related skills for overlap only (not exported as tags).
# Do not chain platform → dialect → language (SQL ↛ PySpark ↛ Python).
_RELATED: dict[str, frozenset[str]] = {
    "SQL": frozenset({"PostgreSQL", "MySQL"}),
    "PostgreSQL": frozenset({"SQL"}),
    "MySQL": frozenset({"SQL"}),
    "PySpark": frozenset({"Python", "Spark"}),
    "Python": frozenset({"PySpark"}),
    "Spark": frozenset({"PySpark"}),
    "Node": frozenset({"JavaScript"}),
    "JavaScript": frozenset({"Node", "TypeScript"}),
    "TypeScript": frozenset({"JavaScript"}),
}

# Avoid bare \bnot\b — phrases like "not just prototypes" / "not just tried
# them out" are common in job posts and are not skill exclusions.
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

# Incidental product-marketing noise that should not count as a requirement.
# E.g. "powered by Snowflake" in a partner blurb without skill language nearby
# is still a real stack mention for data roles — we keep it. Only clear
# "not a technology requirement" patterns are filtered via negation above.


def plain_text(*texts: str | None) -> str:
    """Join fragments and strip HTML to a single whitespace-normalized string."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return ""
    plain = _TAG.sub(" ", html.unescape(blob))
    return _WS.sub(" ", plain).strip()


def normalize_skill_label(skill: str | None) -> str:
    """Canonicalize a skill string for comparison."""
    raw = str(skill or "").strip()
    if not raw:
        return ""
    key = raw.casefold().replace("_", " ")
    key = re.sub(r"\s+", " ", key).strip()
    if key in _SKILL_ALIASES:
        return _SKILL_ALIASES[key]
    # Preserve known canonical casing from the dictionary.
    for label, _ in _TECH_SPECS:
        if label.casefold() == key:
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
    # Scope negation to the same sentence so earlier "No SQL…" does not
    # suppress later "Python is essential."
    sent_start, sent_end = _sentence_bounds(blob, start)
    sentence = blob[sent_start:sent_end]
    local = start - sent_start
    before = sentence[:local]
    after = sentence[local + (end - start) :]
    # Also allow a short lookback within the sentence for "no X" / "without X".
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
    """
    job_norm = {normalize_skill_label(s) for s in job_skills if normalize_skill_label(s)}
    # Expand job set with related skills for overlap only (not for export).
    expanded = set(job_norm)
    for js in list(job_norm):
        expanded |= _RELATED.get(js, frozenset())

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
