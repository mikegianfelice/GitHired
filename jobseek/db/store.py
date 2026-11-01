"""SQLite persistence for discovery, scores, applications, companies, and runs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from jobseek.db.schema import (
    COMPANY_COLUMN_MIGRATIONS,
    JOB_COLUMN_MIGRATIONS,
    SCORE_COLUMN_MIGRATIONS,
    SCHEMA_SQL,
)
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
        # check_same_thread=False allows bounded concurrent discover workers to
        # share this handle under self._write_lock (writes only).
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=60.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.executescript(SCHEMA_SQL)
        self._migrate()
        self._conn.commit()
        import threading

        self._write_lock = threading.RLock()

    def _migrate(self) -> None:
        cols = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(job_scores)").fetchall()
        }
        if "score_kind" not in cols:
            self._conn.execute(
                "ALTER TABLE job_scores ADD COLUMN score_kind TEXT NOT NULL DEFAULT 'deterministic'"
            )
        for col_name, sql in SCORE_COLUMN_MIGRATIONS:
            if col_name not in cols:
                self._conn.execute(sql)
        job_cols = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        for col_name, sql in JOB_COLUMN_MIGRATIONS:
            if col_name not in job_cols:
                self._conn.execute(sql)
        company_cols = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(companies)").fetchall()
        }
        for col_name, sql in COMPANY_COLUMN_MIGRATIONS:
            if col_name not in company_cols:
                self._conn.execute(sql)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_source_company ON jobs(source, company)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_last_seen ON jobs(last_seen)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_scores_fingerprint ON job_scores(config_fingerprint)"
        )

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
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
            # Same source+key in the same UTC second (batch failures / retries) must not crash.
            self._conn.execute(
                """
                INSERT OR REPLACE INTO raw_responses
                    (source, request_key, fetched_at, status_code, body)
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
        """Insert or update a job. Returns (job_id, is_new).

        Never replaces a complete description with an incomplete listing stub.

        Lookup and write happen inside the same write-locked transaction so
        concurrent discover workers cannot both insert the same canonical_key.
        IntegrityError on UNIQUE is treated as a lost race and converted to UPDATE.
        """
        identity = JobIdentity.from_fields(
            company=job.company,
            title=job.title,
            url=job.url,
            ats_provider=job.ats_provider,
            ats_job_id=job.ats_job_id,
        )
        now = seen_at or _utcnow()
        incoming_complete = bool(job.description_complete and job.description)
        incoming_desc = job.description if job.description not in (None, "") else None
        # Ranking requires a non-null description; title is a last-resort stub only.
        stub_desc = incoming_desc or job.title

        with self.transaction():
            # Lookup + write under the same write lock so concurrent discover
            # workers cannot both decide "missing" and race on INSERT.
            existing_id = self.find_existing_job_id(identity)
            if existing_id is None:
                desc = stub_desc
                desc_hash = _hash_text(desc)
                fetched_at = (
                    job.description_fetched_at or now if incoming_complete else None
                )
                # INSERT OR IGNORE: if another worker won the race on
                # canonical_key, rowcount==0 and we fall through to UPDATE.
                cur = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO jobs (
                        canonical_key, ats_provider, ats_job_id, company, title,
                        location_raw, url, apply_url, description, description_hash,
                        salary_raw, salary_min, salary_max, salary_currency,
                        source, posted_date, first_seen, last_seen, removed_at, status,
                        company_norm, title_norm, description_complete, description_fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'new', ?, ?, ?, ?)
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
                        desc,
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
                        1 if incoming_complete else 0,
                        fetched_at,
                    ),
                )
                if cur.rowcount == 1:
                    return int(cur.lastrowid), True
                existing_id = self.find_existing_job_id(identity)
                if existing_id is None:
                    row = self._conn.execute(
                        "SELECT id FROM jobs WHERE canonical_key = ? LIMIT 1",
                        (identity.canonical_key,),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError(
                            f"upsert_job: INSERT OR IGNORE conflict for "
                            f"{identity.canonical_key!r} but row not found"
                        )
                    existing_id = int(row["id"])

            return self._update_existing_job(
                existing_id,
                job=job,
                identity=identity,
                now=now,
                incoming_complete=incoming_complete,
                incoming_desc=incoming_desc,
                stub_desc=stub_desc,
            ), False

    def _update_existing_job(
        self,
        existing_id: int,
        *,
        job: RawJob,
        identity: JobIdentity,
        now: str,
        incoming_complete: bool,
        incoming_desc: str | None,
        stub_desc: str,
    ) -> int:
        """Apply update rules for an existing job row. Caller holds the write lock."""
        existing = self._conn.execute(
            "SELECT description, description_hash, description_complete, "
            "description_fetched_at, location_raw FROM jobs WHERE id = ?",
            (existing_id,),
        ).fetchone()
        old_complete = bool(existing["description_complete"]) if existing else False
        old_desc = (existing["description"] if existing else None) or ""
        old_hash = existing["description_hash"] if existing else None
        old_fetched = existing["description_fetched_at"] if existing else None

        if old_complete and not incoming_complete:
            # Preserve complete cached description; listing stub must not win.
            desc = old_desc
            desc_hash = old_hash
            complete_flag = 1
            fetched_at = old_fetched
        elif incoming_complete:
            desc = incoming_desc or stub_desc
            desc_hash = _hash_text(desc)
            complete_flag = 1
            fetched_at = job.description_fetched_at or now
        elif incoming_desc and (not old_desc or len(incoming_desc) > len(old_desc)):
            desc = incoming_desc
            desc_hash = _hash_text(desc)
            complete_flag = 0
            fetched_at = old_fetched
        else:
            desc = old_desc or stub_desc
            desc_hash = old_hash or _hash_text(desc)
            complete_flag = 1 if old_complete else 0
            fetched_at = old_fetched

        # Prefer richer location when listing was a multi-location stub.
        location = job.location_raw
        if (
            location
            and existing
            and existing["location_raw"]
            and len(str(location)) < len(str(existing["location_raw"]))
            and old_complete
        ):
            location = existing["location_raw"]

        self._conn.execute(
            """
            UPDATE jobs SET
                last_seen = ?,
                removed_at = NULL,
                location_raw = COALESCE(?, location_raw),
                apply_url = COALESCE(?, apply_url),
                description = ?,
                description_hash = ?,
                description_complete = ?,
                description_fetched_at = ?,
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
                location,
                job.apply_url,
                desc,
                desc_hash,
                complete_flag,
                fetched_at,
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
        return existing_id

    def mark_missing_removed(
        self,
        *,
        source_prefix: str | None,
        seen_ids: set[int],
        companies: set[str] | None = None,
        now: str | None = None,
    ) -> int:
        """Mark jobs not seen in this run as removed. Returns count updated.

        Callers must only pass companies whose listing fetch completed fully.
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

    def workday_description_cache(
        self,
        *,
        company: str,
        ats_job_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Return cached Workday descriptions keyed by ats_job_id and URL path id.

        Multi-key index lets hydration match list rows that only expose the path
        slug when bulletFields omit the requisition id.
        """

        def _index_rows(rows: list[Any]) -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for row in rows:
                entry = dict(row)
                job_id = entry.get("ats_job_id")
                if job_id:
                    out[str(job_id)] = entry
                url = str(entry.get("url") or entry.get("apply_url") or "")
                if url:
                    path_id = url.rstrip("/").split("/")[-1].split("?")[0]
                    if path_id and path_id not in out:
                        out[path_id] = entry
            return out

        clauses = [
            "ats_provider = 'workday'",
            "company = ?",
            "removed_at IS NULL",
            "ats_job_id IS NOT NULL",
        ]
        params: list[Any] = [company]
        select_cols = (
            "ats_job_id, description, description_complete, "
            "description_fetched_at, location_raw, description_hash, url, apply_url"
        )
        if ats_job_ids:
            out: dict[str, dict[str, Any]] = {}
            for i in range(0, len(ats_job_ids), 400):
                chunk = ats_job_ids[i : i + 400]
                ph = ",".join("?" for _ in chunk)
                sql = f"""
                    SELECT {select_cols}
                    FROM jobs
                    WHERE ats_provider = 'workday' AND company = ?
                      AND removed_at IS NULL AND ats_job_id IN ({ph})
                """
                rows = self._conn.execute(sql, [company, *chunk]).fetchall()
                out.update(_index_rows(rows))
            return out
        sql = f"""
            SELECT {select_cols}
            FROM jobs
            WHERE {' AND '.join(clauses)}
        """
        rows = self._conn.execute(sql, params).fetchall()
        return _index_rows(rows)

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(
        self,
        *,
        min_score: float | None = None,
        status: str | None = None,
        limit: int = 50,
        score_kind: str = "deterministic",
        eligibility: str | None = "ELIGIBLE",
    ) -> list[dict[str, Any]]:
        """List jobs with scores.

        ``eligibility`` defaults to ``ELIGIBLE`` so the main shortlist is never
        silently padded with UNCERTAIN/INELIGIBLE roles. Pass ``UNCERTAIN``,
        ``INELIGIBLE``, ``ALL``, or ``None`` to inspect other buckets.
        """
        params: list[Any] = []
        clauses = ["j.removed_at IS NULL"]
        if status:
            clauses.append("j.status = ?")
            params.append(status)
        join = ""
        select_score = (
            "NULL AS overall, NULL AS score_kind, NULL AS model, "
            "NULL AS hard_filter_json"
        )
        want_scores = min_score is not None or score_kind or eligibility
        if want_scores:
            join = """
                LEFT JOIN job_scores s
                  ON s.job_id = j.id
                 AND s.description_hash = j.description_hash
                 AND s.score_kind = ?
            """
            params.insert(0, score_kind or "deterministic")
            select_score = (
                "s.overall AS overall, s.score_kind AS score_kind, s.model AS model, "
                "s.hard_filter_json AS hard_filter_json"
            )
            if min_score is not None:
                clauses.append("s.overall >= ?")
                params.append(min_score)
        # Over-fetch when filtering eligibility so LIMIT still fills.
        elig_filter = (eligibility or "").strip().upper()
        fetch_limit = limit
        if elig_filter and elig_filter not in ("ALL", "*"):
            fetch_limit = max(limit * 20, 100)
        params.append(fetch_limit)
        sql = f"""
            SELECT j.*, {select_score}
            FROM jobs j
            {join}
            WHERE {' AND '.join(clauses)}
            ORDER BY COALESCE(overall, 0) DESC, j.last_seen DESC
            LIMIT ?
        """
        rows = [dict(r) for r in self._conn.execute(sql, params).fetchall()]
        if not elig_filter or elig_filter in ("ALL", "*"):
            return rows[:limit]
        out: list[dict[str, Any]] = []
        for row in rows:
            elig = self._eligibility_from_score_row(row)
            if elig == elig_filter:
                out.append(row)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _eligibility_from_score_row(row: dict[str, Any]) -> str:
        import json

        hf = row.get("hard_filter_json")
        if isinstance(hf, str) and hf:
            try:
                return str((json.loads(hf) or {}).get("eligibility") or "UNCERTAIN").upper()
            except json.JSONDecodeError:
                return "UNCERTAIN"
        if isinstance(hf, dict):
            return str(hf.get("eligibility") or "UNCERTAIN").upper()
        return "UNCERTAIN"

    def count_scored_by_eligibility(
        self,
        *,
        score_kind: str = "deterministic",
        min_score: float | None = None,
    ) -> dict[str, int]:
        """Count scored jobs by hard-filter eligibility (ELIGIBLE/UNCERTAIN/INELIGIBLE)."""
        import json

        params: list[Any] = [score_kind]
        score_clause = ""
        if min_score is not None:
            score_clause = "AND s.overall >= ?"
            params.append(min_score)
        rows = self._conn.execute(
            f"""
            SELECT s.hard_filter_json, s.overall
            FROM job_scores s
            JOIN jobs j ON j.id = s.job_id
            WHERE j.removed_at IS NULL
              AND s.score_kind = ?
              AND s.description_hash = j.description_hash
              {score_clause}
            """,
            params,
        ).fetchall()
        counts = {"ELIGIBLE": 0, "UNCERTAIN": 0, "INELIGIBLE": 0}
        for row in rows:
            elig = "UNCERTAIN"
            hf = row["hard_filter_json"] if hasattr(row, "keys") else row[0]
            if isinstance(hf, str) and hf:
                try:
                    elig = str((json.loads(hf) or {}).get("eligibility") or "UNCERTAIN").upper()
                except json.JSONDecodeError:
                    elig = "UNCERTAIN"
            if elig not in counts:
                counts[elig] = 0
            counts[elig] += 1
        return counts

    def _jobs_needing_score_sql(
        self,
        *,
        re_rank: bool,
        score_kind: str,
        current_model: str | None,
        config_fingerprint: str | None,
        count_only: bool = False,
    ) -> tuple[str, list[Any]]:
        """Build SQL for jobs that lack a valid score for the current config."""
        select = "COUNT(*)" if count_only else "j.*"
        if re_rank:
            return (
                f"""
                SELECT {select} FROM jobs j
                WHERE j.removed_at IS NULL AND j.status != 'removed'
                """,
                [],
            )
        if current_model:
            models = (
                list(current_model)
                if isinstance(current_model, (list, tuple, set))
                else [current_model]
            )
            placeholders = ",".join("?" for _ in models)
            sql = f"""
                SELECT {select} FROM jobs j
                WHERE j.removed_at IS NULL
                  AND j.status != 'removed'
                  AND j.description IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM job_scores s
                    WHERE s.job_id = j.id
                      AND s.description_hash = j.description_hash
                      AND s.model IN ({placeholders})
                      AND (
                        ? IS NULL
                        OR (s.config_fingerprint IS NOT NULL AND s.config_fingerprint = ?)
                      )
                  )
            """
            fp = config_fingerprint
            return sql, [*models, fp, fp]
        sql = f"""
            SELECT {select} FROM jobs j
            LEFT JOIN job_scores s
              ON s.job_id = j.id
             AND s.description_hash = j.description_hash
             AND s.score_kind = ?
             AND (? IS NULL OR s.config_fingerprint = ?)
            WHERE j.removed_at IS NULL
              AND j.status != 'removed'
              AND j.description IS NOT NULL
              AND s.id IS NULL
        """
        fp = config_fingerprint
        return sql, [score_kind, fp, fp]

    def count_jobs_needing_score(
        self,
        *,
        re_rank: bool = False,
        score_kind: str = "deterministic",
        current_model: str | None = None,
        config_fingerprint: str | None = None,
    ) -> int:
        sql, params = self._jobs_needing_score_sql(
            re_rank=re_rank,
            score_kind=score_kind,
            current_model=current_model,
            config_fingerprint=config_fingerprint,
            count_only=True,
        )
        row = self._conn.execute(sql, params).fetchone()
        return int(row[0] if row else 0)

    def jobs_needing_score(
        self,
        *,
        limit: int = 50,
        re_rank: bool = False,
        score_kind: str = "deterministic",
        pool_size: int | None = None,
        current_model: str | None = None,
        title_priority: Any = None,
        config_fingerprint: str | None = None,
    ) -> list[dict[str, Any]]:
        from jobseek.rank.selection import select_jobs_fairly

        # Keep the candidate pool modest — large pools with title_priority make
        # incremental ranking feel hung on big databases.
        pool = pool_size or max(limit * 8, 400)
        base_sql, params = self._jobs_needing_score_sql(
            re_rank=re_rank,
            score_kind=score_kind,
            current_model=current_model,
            config_fingerprint=config_fingerprint,
            count_only=False,
        )
        order = (
            "ORDER BY j.last_seen DESC"
            if re_rank
            else "ORDER BY j.first_seen DESC"
        )
        sql = f"{base_sql} {order} LIMIT ?"
        rows = self._conn.execute(sql, (*params, pool)).fetchall()
        candidates = [dict(r) for r in rows]
        return select_jobs_fairly(
            candidates, limit=limit, title_priority=title_priority
        )

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
        score_kind: str = "deterministic",
        config_fingerprint: str | None = None,
    ) -> None:
        with self.transaction():
            # Prefer upsert by (job_id, description_hash, score_kind); fall back
            # for older DBs that only unique on (job_id, description_hash).
            existing = self._conn.execute(
                """
                SELECT id FROM job_scores
                WHERE job_id = ? AND description_hash = ? AND score_kind = ?
                """,
                (job_id, description_hash, score_kind),
            ).fetchone()
            payload = (
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
                score_kind,
                description_hash,
                config_fingerprint,
                _utcnow(),
            )
            if existing:
                self._conn.execute(
                    """
                    UPDATE job_scores SET
                        overall = ?, scores_json = ?, hard_filter_json = ?,
                        strengths_json = ?, gaps_json = ?, salary_alignment = ?,
                        rejection_reasons_json = ?, evidence_json = ?, model = ?,
                        config_fingerprint = ?, scored_at = ?
                    WHERE id = ?
                    """,
                    (
                        overall,
                        json.dumps(scores),
                        json.dumps(hard_filter) if hard_filter else None,
                        json.dumps(strengths),
                        json.dumps(gaps),
                        salary_alignment,
                        json.dumps(rejection_reasons),
                        json.dumps(evidence),
                        model,
                        config_fingerprint,
                        _utcnow(),
                        int(existing["id"]),
                    ),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO job_scores (
                        job_id, overall, scores_json, hard_filter_json, strengths_json,
                        gaps_json, salary_alignment, rejection_reasons_json, evidence_json,
                        model, score_kind, description_hash, config_fingerprint, scored_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
            # Hard-filter failures historically used score_kind=hard_filter while
            # confirmed shortlists read score_kind=deterministic — delete the
            # sibling hard_filter row when writing deterministic so stale PASS
            # rows cannot shadow a newer FAIL (and vice versa).
            if score_kind == "deterministic":
                self._conn.execute(
                    """
                    DELETE FROM job_scores
                    WHERE job_id = ? AND description_hash = ? AND score_kind = 'hard_filter'
                    """,
                    (job_id, description_hash),
                )
            elif score_kind == "hard_filter":
                self._conn.execute(
                    """
                    DELETE FROM job_scores
                    WHERE job_id = ? AND description_hash = ? AND score_kind = 'deterministic'
                    """,
                    (job_id, description_hash),
                )
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
        self,
        *,
        limit: int = 10,
        min_score: float = 60.0,
        since: str | None = None,
        score_kind: str = "deterministic",
        eligibility: str | None = "ELIGIBLE",
    ) -> list[dict[str, Any]]:
        # Over-fetch so filtering tracked applications + eligibility can still fill top_n
        fetch_limit = max(limit * 25, 100)
        params: list[Any] = [score_kind, min_score]
        since_clause = ""
        if since:
            since_clause = "AND j.first_seen >= ?"
            params.append(since)
        params.append(fetch_limit)
        rows = self._conn.execute(
            f"""
            SELECT j.*, s.overall, s.strengths_json, s.gaps_json, s.hard_filter_json,
                   s.salary_alignment, s.rejection_reasons_json, s.evidence_json,
                   s.scored_at, s.score_kind, s.model
            FROM jobs j
            JOIN job_scores s
              ON s.job_id = j.id
             AND s.description_hash = j.description_hash
             AND s.score_kind = ?
            WHERE j.removed_at IS NULL
              AND j.status = 'ranked'
              AND s.overall >= ?
              {since_clause}
            ORDER BY s.overall DESC, j.first_seen DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        elig_filter = (eligibility or "ELIGIBLE").strip().upper()
        results = []
        for row in rows:
            item = dict(row)
            if self.should_skip_recommendation(item["company"], item["title"]):
                continue
            if elig_filter not in ("ALL", "*"):
                if self._eligibility_from_score_row(item) != elig_filter:
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

    # --- Company registry -------------------------------------------------

    def upsert_company(
        self,
        *,
        name: str,
        careers_url: str | None = None,
        ats: str | None = None,
        board_token: str | None = None,
        validation_status: str = "unvalidated",
        last_success_at: str | None = None,
        last_error: str | None = None,
        industry: str | None = None,
        enabled: bool = True,
        notes: str | None = None,
        source: str = "yaml",
        domain: str | None = None,
        discovery_source: str | None = None,
        last_validated_at: str | None = None,
        last_job_fetch_at: str | None = None,
        failure_count: int | None = None,
        validation_evidence_json: str | None = None,
        excluded: bool | None = None,
        preserve_enabled: bool = False,
    ) -> int:
        name_norm = normalize_text(name)
        with self.transaction():
            existing = self._conn.execute(
                "SELECT * FROM companies WHERE name_norm = ?", (name_norm,)
            ).fetchone()
            if existing:
                next_enabled = int(existing["enabled"]) if preserve_enabled else (1 if enabled else 0)
                if excluded is not None:
                    next_excluded = 1 if excluded else 0
                else:
                    next_excluded = int(existing["excluded"] or 0) if "excluded" in existing.keys() else 0
                next_failures = (
                    int(failure_count)
                    if failure_count is not None
                    else int(existing["failure_count"] or 0)
                    if "failure_count" in existing.keys()
                    else 0
                )
                self._conn.execute(
                    """
                    UPDATE companies SET
                        careers_url = COALESCE(?, careers_url),
                        ats = COALESCE(?, ats),
                        board_token = COALESCE(?, board_token),
                        validation_status = ?,
                        last_success_at = COALESCE(?, last_success_at),
                        last_error = ?,
                        industry = COALESCE(?, industry),
                        enabled = ?,
                        notes = COALESCE(?, notes),
                        source = COALESCE(?, source),
                        domain = COALESCE(?, domain),
                        discovery_source = COALESCE(?, discovery_source),
                        last_validated_at = COALESCE(?, last_validated_at),
                        last_job_fetch_at = COALESCE(?, last_job_fetch_at),
                        failure_count = ?,
                        validation_evidence_json = COALESCE(?, validation_evidence_json),
                        excluded = ?
                    WHERE id = ?
                    """,
                    (
                        careers_url,
                        ats,
                        board_token,
                        validation_status,
                        last_success_at,
                        last_error,
                        industry,
                        next_enabled,
                        notes,
                        source,
                        domain,
                        discovery_source,
                        last_validated_at,
                        last_job_fetch_at,
                        next_failures,
                        validation_evidence_json,
                        next_excluded,
                        int(existing["id"]),
                    ),
                )
                return int(existing["id"])
            cur = self._conn.execute(
                """
                INSERT INTO companies (
                    name, name_norm, careers_url, ats, board_token, validation_status,
                    last_success_at, last_error, industry, enabled, notes, source,
                    domain, discovery_source, last_validated_at, last_job_fetch_at,
                    failure_count, validation_evidence_json, excluded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    name_norm,
                    careers_url,
                    ats,
                    board_token,
                    validation_status,
                    last_success_at,
                    last_error,
                    industry,
                    1 if enabled else 0,
                    notes,
                    source,
                    domain,
                    discovery_source,
                    last_validated_at,
                    last_job_fetch_at,
                    int(failure_count or 0),
                    validation_evidence_json,
                    1 if excluded else 0,
                ),
            )
            return int(cur.lastrowid)

    def seed_companies_from_yaml(self, companies: list[dict[str, Any]]) -> int:
        count = 0
        for company in companies:
            name = company.get("name")
            if not name:
                continue
            name_norm = normalize_text(str(name))
            existing = self._conn.execute(
                "SELECT validation_status, failure_count FROM companies WHERE name_norm = ?",
                (name_norm,),
            ).fetchone()
            # Preserve prior validation from successful discovers
            status = "unvalidated"
            if existing and existing["validation_status"] in (
                "ok",
                "invalid",
                "empty",
                "unsupported",
                "transient",
                "excluded",
            ):
                status = str(existing["validation_status"])
            from jobseek.companies.domain_util import canonical_domain

            domain = company.get("domain") or canonical_domain(
                str(company.get("careers_url") or "")
            )
            self.upsert_company(
                name=str(name),
                careers_url=company.get("careers_url"),
                ats=(company.get("ats") or "unknown"),
                board_token=company.get("board_token") or company.get("site_slug"),
                validation_status=status,
                industry=company.get("industry"),
                enabled=bool(company.get("enabled", True)),
                notes=company.get("notes"),
                source=str(company.get("source") or "yaml"),
                domain=domain or None,
                discovery_source=company.get("discovery_source") or "builtin",
                # Keep user/DB enablement across rediscovery seeds
                preserve_enabled=existing is not None,
            )
            count += 1
        return count

    def mark_company_fetch(
        self,
        name: str,
        *,
        ok: bool,
        ats: str | None = None,
        board_token: str | None = None,
        error: str | None = None,
        empty: bool = False,
    ) -> None:
        if ok:
            status = "empty" if empty else "ok"
            now = _utcnow()
            self.upsert_company(
                name=name,
                ats=ats,
                board_token=board_token,
                validation_status=status,
                last_success_at=now,
                last_job_fetch_at=now,
                last_error=None,
                failure_count=0,
                source="discover",
                preserve_enabled=True,
            )
            return
        existing = self._conn.execute(
            "SELECT failure_count FROM companies WHERE name_norm = ?",
            (normalize_text(name),),
        ).fetchone()
        failures = int(existing["failure_count"] or 0) + 1 if existing else 1
        self.upsert_company(
            name=name,
            ats=ats,
            board_token=board_token,
            validation_status="invalid",
            last_error=error or "fetch failed",
            failure_count=failures,
            source="discover",
            preserve_enabled=True,
        )

    def list_companies(
        self,
        *,
        ats: str | None = None,
        status: str | None = None,
        enabled: bool | None = None,
        excluded: bool | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if ats:
            clauses.append("ats = ?")
            params.append(ats)
        if status:
            clauses.append("validation_status = ?")
            params.append(status)
        if enabled is not None:
            clauses.append("enabled = ?")
            params.append(1 if enabled else 0)
        if excluded is not None:
            clauses.append("excluded = ?")
            params.append(1 if excluded else 0)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM companies {where} ORDER BY name COLLATE NOCASE",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def company_stats(self) -> dict[str, Any]:
        by_ats = {
            row["ats"] or "unknown": row["n"]
            for row in self._conn.execute(
                "SELECT ats, COUNT(*) AS n FROM companies GROUP BY ats"
            ).fetchall()
        }
        by_status = {
            row["validation_status"] or "unvalidated": row["n"]
            for row in self._conn.execute(
                "SELECT validation_status, COUNT(*) AS n FROM companies GROUP BY validation_status"
            ).fetchall()
        }
        enabled = self._conn.execute(
            "SELECT COUNT(*) AS n FROM companies WHERE enabled = 1 AND IFNULL(excluded, 0) = 0"
        ).fetchone()["n"]
        failures = [
            dict(r)
            for r in self._conn.execute(
                """
                SELECT name, ats, failure_count, last_error, validation_status
                FROM companies
                WHERE IFNULL(failure_count, 0) > 0
                ORDER BY failure_count DESC, name COLLATE NOCASE
                LIMIT 20
                """
            ).fetchall()
        ]
        return {
            "total": sum(by_status.values()),
            "enabled": enabled,
            "by_ats": by_ats,
            "by_status": by_status,
            "top_failures": failures,
        }

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
            description = entry.get("description") or title
            job = RawJob(
                company=company,
                title=title,
                url=url,
                source=f"import:{entry.get('portal') or entry.get('source') or 'seen_jobs'}",
                location_raw=entry.get("location"),
                posted_date=entry.get("posted_date"),
                description=description,
            )
            job_id, _ = self.upsert_job(job, seen_at=entry.get("first_seen") or _utcnow())
            # Carry over prior rank fields when present
            rank_score = entry.get("rank_score")
            if rank_score is not None:
                try:
                    overall = float(rank_score)
                except (TypeError, ValueError):
                    overall = None
                if overall is not None:
                    gaps = entry.get("gaps") or []
                    if isinstance(gaps, str):
                        gaps = [gaps]
                    self.save_score(
                        job_id,
                        overall=overall,
                        scores={"imported": overall},
                        hard_filter={
                            "verdict": entry.get("location_verdict") or "FLAG",
                            "reasons": ["imported from seen_jobs.json"],
                        },
                        strengths=[],
                        gaps=list(gaps)[:10],
                        salary_alignment="",
                        rejection_reasons=[],
                        evidence=[],
                        model="imported",
                        description_hash=_hash_text(description),
                        score_kind="deterministic",
                    )
                    status = entry.get("status")
                    if status:
                        with self.transaction():
                            self._conn.execute(
                                "UPDATE jobs SET status = ? WHERE id = ?",
                                (str(status), job_id),
                            )
            count += 1
        return count
