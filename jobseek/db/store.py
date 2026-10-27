"""SQLite persistence for discovery, scores, applications, and runs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from jobseek.db.schema import SCHEMA_SQL
from jobseek.identity import JobIdentity, normalize_text
from jobseek.models import RawJob


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_text(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def store_raw(
        self,
        *,
        source: str,
        request_key: str,
        status_code: int | None,
        body: str | Any,
    ) -> None:
        if not isinstance(body, str):
            body = json.dumps(body, ensure_ascii=False)
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO raw_responses (source, request_key, fetched_at, status_code, body)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source, request_key, _utcnow(), status_code, body),
            )

    def find_existing_job_id(self, identity: JobIdentity) -> int | None:
        cur = self._conn.cursor()
        if identity.ats_provider and identity.ats_job_id:
            row = cur.execute(
                """
                SELECT id FROM jobs
                WHERE ats_provider = ? AND ats_job_id = ?
                LIMIT 1
                """,
                (identity.ats_provider, identity.ats_job_id),
            ).fetchone()
            if row:
                return int(row["id"])
        if identity.url:
            row = cur.execute(
                "SELECT id FROM jobs WHERE url = ? LIMIT 1", (identity.url,)
            ).fetchone()
            if row:
                return int(row["id"])
        row = cur.execute(
            """
            SELECT id FROM jobs
            WHERE company_norm = ? AND title_norm = ?
            LIMIT 1
            """,
            (identity.company_norm, identity.title_norm),
        ).fetchone()
        if row:
            return int(row["id"])
        row = cur.execute(
            "SELECT id FROM jobs WHERE canonical_key = ? LIMIT 1",
            (identity.canonical_key,),
        ).fetchone()
        return int(row["id"]) if row else None

    def upsert_job(self, job: RawJob, *, seen_at: str | None = None) -> tuple[int, bool]:
        """Insert or update a job. Returns (job_id, is_new)."""
        identity = JobIdentity.from_fields(
            company=job.company,
            title=job.title,
            url=job.url,
            ats_provider=job.ats_provider,
            ats_job_id=job.ats_job_id,
        )
        now = seen_at or _utcnow()
        desc_hash = _hash_text(job.description)
        existing_id = self.find_existing_job_id(identity)
        with self.transaction():
            if existing_id is None:
                cur = self._conn.execute(
                    """
                    INSERT INTO jobs (
                        canonical_key, ats_provider, ats_job_id, company, title,
                        location_raw, url, apply_url, description, description_hash,
                        salary_raw, salary_min, salary_max, salary_currency,
                        source, posted_date, first_seen, last_seen, removed_at, status,
                        company_norm, title_norm
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'new', ?, ?)
                    """,
                    (
                        identity.canonical_key,
                        identity.ats_provider,
                        identity.ats_job_id,
                        job.company,
                        job.title,
                        job.location_raw,
                        identity.url,
                        job.apply_url,
                        job.description,
                        desc_hash,
                        job.salary_raw,
                        job.salary_min,
                        job.salary_max,
                        job.salary_currency,
                        job.source,
                        job.posted_date,
                        now,
                        now,
                        identity.company_norm,
                        identity.title_norm,
                    ),
                )
                return int(cur.lastrowid), True

            self._conn.execute(
                """
                UPDATE jobs SET
                    last_seen = ?,
                    removed_at = NULL,
                    location_raw = COALESCE(?, location_raw),
                    apply_url = COALESCE(?, apply_url),
                    description = COALESCE(?, description),
                    description_hash = COALESCE(?, description_hash),
                    salary_raw = COALESCE(?, salary_raw),
                    salary_min = COALESCE(?, salary_min),
                    salary_max = COALESCE(?, salary_max),
                    salary_currency = COALESCE(?, salary_currency),
                    posted_date = COALESCE(?, posted_date),
                    ats_provider = COALESCE(?, ats_provider),
                    ats_job_id = COALESCE(?, ats_job_id),
                    status = CASE WHEN status = 'removed' THEN 'new' ELSE status END
                WHERE id = ?
                """,
                (
                    now,
                    job.location_raw,
                    job.apply_url,
                    job.description,
                    desc_hash if job.description else None,
                    job.salary_raw,
                    job.salary_min,
                    job.salary_max,
                    job.salary_currency,
                    job.posted_date,
                    identity.ats_provider,
                    identity.ats_job_id,
                    existing_id,
                ),
            )
            return existing_id, False

    def mark_missing_removed(
        self,
        *,
        source_prefix: str | None,
        seen_ids: set[int],
        companies: set[str] | None = None,
        now: str | None = None,
    ) -> int:
        """Mark jobs not seen in this run as removed. Returns count updated.

        Only considers rows for `companies` when provided, so a failed board
        fetch cannot retire another company's listings.
        """
        stamp = now or _utcnow()
        if not seen_ids:
            return 0
        placeholders = ",".join("?" for _ in seen_ids)
        params: list[Any] = [stamp, *seen_ids]
        sql = f"""
            UPDATE jobs
            SET removed_at = ?, status = 'removed'
            WHERE removed_at IS NULL
              AND id NOT IN ({placeholders})
        """
        if source_prefix:
            sql += " AND source LIKE ?"
            params.append(f"{source_prefix}%")
        if companies:
            c_ph = ",".join("?" for _ in companies)
            sql += f" AND company IN ({c_ph})"
            params.extend(sorted(companies))
        with self.transaction():
            cur = self._conn.execute(sql, params)
            return cur.rowcount

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def jobs_needing_score(self, *, limit: int = 50, re_rank: bool = False) -> list[dict[str, Any]]:
        if re_rank:
            sql = """
                SELECT j.* FROM jobs j
                WHERE j.removed_at IS NULL AND j.status != 'removed'
                ORDER BY j.last_seen DESC
                LIMIT ?
            """
            rows = self._conn.execute(sql, (limit,)).fetchall()
        else:
            sql = """
                SELECT j.* FROM jobs j
                LEFT JOIN job_scores s
                  ON s.job_id = j.id AND s.description_hash = j.description_hash
                WHERE j.removed_at IS NULL
                  AND j.status != 'removed'
                  AND j.description IS NOT NULL
                  AND s.id IS NULL
                ORDER BY j.first_seen DESC
                LIMIT ?
            """
            rows = self._conn.execute(sql, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def save_score(
        self,
        job_id: int,
        *,
        overall: float,
        scores: dict[str, float],
        hard_filter: dict[str, Any] | None,
        strengths: list[str],
        gaps: list[str],
        salary_alignment: str,
        rejection_reasons: list[str],
        evidence: list[str],
        model: str,
        description_hash: str,
    ) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO job_scores (
                    job_id, overall, scores_json, hard_filter_json, strengths_json,
                    gaps_json, salary_alignment, rejection_reasons_json, evidence_json,
                    model, description_hash, scored_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, description_hash) DO UPDATE SET
                    overall = excluded.overall,
                    scores_json = excluded.scores_json,
                    hard_filter_json = excluded.hard_filter_json,
                    strengths_json = excluded.strengths_json,
                    gaps_json = excluded.gaps_json,
                    salary_alignment = excluded.salary_alignment,
                    rejection_reasons_json = excluded.rejection_reasons_json,
                    evidence_json = excluded.evidence_json,
                    model = excluded.model,
                    scored_at = excluded.scored_at
                """,
                (
                    job_id,
                    overall,
                    json.dumps(scores),
                    json.dumps(hard_filter) if hard_filter else None,
                    json.dumps(strengths),
                    json.dumps(gaps),
                    salary_alignment,
                    json.dumps(rejection_reasons),
                    json.dumps(evidence),
                    model,
                    description_hash,
                    _utcnow(),
                ),
            )
            self._conn.execute(
                "UPDATE jobs SET status = ? WHERE id = ?",
                ("ranked" if overall >= 0 else "scored", job_id),
            )
            # status always ranked after a score attempt
            self._conn.execute(
                "UPDATE jobs SET status = 'ranked' WHERE id = ?", (job_id,)
            )

    def sync_application(self, company: str, role: str, status: str, notes: str = "") -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO applications (company, role, status, notes, company_norm, role_norm, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(company_norm, role_norm) DO UPDATE SET
                    status = excluded.status,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (
                    company,
                    role,
                    status,
                    notes,
                    normalize_text(company),
                    normalize_text(role),
                    _utcnow(),
                ),
            )

    def import_tracker_csv(self, path: Path) -> int:
        import csv

        if not path.is_file():
            return 0
        count = 0
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                company = (row.get("company") or "").strip()
                role = (row.get("role") or "").strip()
                status = (row.get("status") or "").strip() or "applied"
                if not company or not role:
                    continue
                self.sync_application(company, role, status, row.get("notes") or "")
                count += 1
        return count

    def is_tracked(self, company: str, title: str) -> bool:
        row = self._conn.execute(
            """
            SELECT 1 FROM applications
            WHERE company_norm = ? AND role_norm = ?
            LIMIT 1
            """,
            (normalize_text(company), normalize_text(title)),
        ).fetchone()
        return row is not None

    def tracked_blocked_statuses(self) -> set[str]:
        return {
            "drafted",
            "applied",
            "interview",
            "offer",
            "hired",
            "rejected",
            "no_response",
            "offer_declined",
            "withdrawn",
        }

    def should_skip_recommendation(self, company: str, title: str) -> bool:
        row = self._conn.execute(
            """
            SELECT status FROM applications
            WHERE company_norm = ? AND role_norm = ?
            LIMIT 1
            """,
            (normalize_text(company), normalize_text(title)),
        ).fetchone()
        if not row:
            return False
        return (row["status"] or "").lower() in self.tracked_blocked_statuses()

    def start_run(self, kind: str) -> int:
        with self.transaction():
            cur = self._conn.execute(
                "INSERT INTO runs (kind, started_at, ok, summary_json) VALUES (?, ?, NULL, NULL)",
                (kind, _utcnow()),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, *, ok: bool, summary: dict[str, Any]) -> None:
        with self.transaction():
            self._conn.execute(
                """
                UPDATE runs SET finished_at = ?, ok = ?, summary_json = ?
                WHERE id = ?
                """,
                (_utcnow(), 1 if ok else 0, json.dumps(summary, ensure_ascii=False), run_id),
            )

    def add_run_event(
        self, run_id: int, level: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO run_events (run_id, level, message, details_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    level,
                    message,
                    json.dumps(details or {}, ensure_ascii=False),
                    _utcnow(),
                ),
            )

    def top_new_scored(
        self, *, limit: int = 10, min_score: float = 60.0, since: str | None = None
    ) -> list[dict[str, Any]]:
        params: list[Any] = [min_score]
        since_clause = ""
        if since:
            since_clause = "AND j.first_seen >= ?"
            params.append(since)
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT j.*, s.overall, s.strengths_json, s.gaps_json, s.hard_filter_json,
                   s.salary_alignment, s.rejection_reasons_json, s.evidence_json, s.scored_at
            FROM jobs j
            JOIN job_scores s ON s.job_id = j.id AND s.description_hash = j.description_hash
            WHERE j.removed_at IS NULL
              AND j.status = 'ranked'
              AND s.overall >= ?
              {since_clause}
            ORDER BY s.overall DESC, j.first_seen DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            if self.should_skip_recommendation(item["company"], item["title"]):
                continue
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def save_digest(self, job_ids: list[int], *, emailed: bool = False) -> int:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO digests (created_at, job_ids_json, emailed)
                VALUES (?, ?, ?)
                """,
                (_utcnow(), json.dumps(job_ids), 1 if emailed else 0),
            )
            return int(cur.lastrowid)

    def last_digest_at(self) -> str | None:
        row = self._conn.execute(
            "SELECT created_at FROM digests ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["created_at"] if row else None

    def import_seen_jobs_json(self, path: Path) -> int:
        if not path.is_file():
            return 0
        doc = json.loads(path.read_text(encoding="utf-8"))
        seen = doc.get("seen", doc) if isinstance(doc, dict) else {}
        if not isinstance(seen, dict):
            return 0
        count = 0
        for _key, entry in seen.items():
            if not isinstance(entry, dict):
                continue
            company = entry.get("company") or ""
            title = entry.get("title") or ""
            url = entry.get("url") or ""
            if not company or not title or not url:
                continue
            job = RawJob(
                company=company,
                title=title,
                url=url,
                source=f"import:{entry.get('portal') or entry.get('source') or 'seen_jobs'}",
                location_raw=entry.get("location"),
                posted_date=entry.get("posted_date"),
                description=entry.get("description"),
            )
            self.upsert_job(job, seen_at=entry.get("first_seen") or _utcnow())
            count += 1
        return count
