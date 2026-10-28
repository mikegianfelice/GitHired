"""SQLite schema for jobseek / githired."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS raw_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    request_key TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    status_code INTEGER,
    body TEXT,
    UNIQUE(source, request_key, fetched_at)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_key TEXT NOT NULL UNIQUE,
    ats_provider TEXT,
    ats_job_id TEXT,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location_raw TEXT,
    url TEXT NOT NULL,
    apply_url TEXT,
    description TEXT,
    description_hash TEXT,
    salary_raw TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    source TEXT NOT NULL,
    posted_date TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    removed_at TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    company_norm TEXT,
    title_norm TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_ats ON jobs(ats_provider, ats_job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(url);
CREATE INDEX IF NOT EXISTS idx_jobs_company_title ON jobs(company_norm, title_norm);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_removed ON jobs(removed_at);

CREATE TABLE IF NOT EXISTS job_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    overall REAL NOT NULL,
    scores_json TEXT NOT NULL,
    hard_filter_json TEXT,
    strengths_json TEXT,
    gaps_json TEXT,
    salary_alignment TEXT,
    rejection_reasons_json TEXT,
    evidence_json TEXT,
    model TEXT,
    score_kind TEXT NOT NULL DEFAULT 'deterministic',
    description_hash TEXT,
    scored_at TEXT NOT NULL,
    UNIQUE(job_id, description_hash, score_kind)
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    notes TEXT,
    company_norm TEXT,
    role_norm TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(company_norm, role_norm)
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL UNIQUE,
    careers_url TEXT,
    ats TEXT,
    board_token TEXT,
    validation_status TEXT NOT NULL DEFAULT 'unvalidated',
    last_success_at TEXT,
    last_error TEXT,
    industry TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    source TEXT NOT NULL DEFAULT 'yaml'
);

CREATE INDEX IF NOT EXISTS idx_companies_ats ON companies(ats, board_token);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    job_ids_json TEXT NOT NULL,
    emailed INTEGER NOT NULL DEFAULT 0
);
"""

# Migrations for DBs created before score_kind / companies existed.
MIGRATIONS = [
    "ALTER TABLE job_scores ADD COLUMN score_kind TEXT NOT NULL DEFAULT 'deterministic'",
]
