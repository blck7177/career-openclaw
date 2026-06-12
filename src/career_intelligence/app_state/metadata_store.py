"""
MetadataStore — SQLite-backed metadata for workspaces, users, sessions,
runs, tasks, and artifact indexes.

Design:
- SQLite with WAL mode for concurrent read/write between API and worker.
- Metadata only — large artifacts (reports, JDs, resumes) stay on the filesystem.
- All tables carry workspace_id so queries are always workspace-scoped.
- Global tables (jobs, job_reports) do not have workspace_id.

Usage:
    store = MetadataStore.from_data_root(get_data_root())
    store.init_schema()    # idempotent — safe to call on every startup
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "") -> str:
    short = uuid.uuid4().hex[:12]
    return f"{prefix}{short}" if prefix else short


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

-- =========================================================================
-- Global tables (no workspace_id — shared across all workspaces)
-- =========================================================================

CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    canonical_url   TEXT,
    jd_hash         TEXT,
    company         TEXT,
    title           TEXT,
    location        TEXT,
    source          TEXT,
    artifact_path   TEXT,   -- path to raw JD text file
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_jd_hash ON jobs(jd_hash);

CREATE TABLE IF NOT EXISTS job_reports (
    job_report_id   TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES jobs(job_id),
    jd_hash         TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    model           TEXT,
    status          TEXT NOT NULL DEFAULT 'active',  -- active | superseded
    superseded_by   TEXT,                            -- job_report_id
    report_path     TEXT,   -- path to report.md
    structured_path TEXT,   -- path to structured.json
    sources_path    TEXT,   -- path to sources.json
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_reports_job_id ON job_reports(job_id);
CREATE INDEX IF NOT EXISTS idx_job_reports_cache_key
    ON job_reports(job_id, jd_hash, prompt_version);

-- =========================================================================
-- Workspace / auth tables
-- =========================================================================

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id    TEXT PRIMARY KEY,
    name            TEXT,
    created_at      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'  -- active | suspended
);

CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(workspace_id),
    display_name    TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_workspace ON users(workspace_id);

CREATE TABLE IF NOT EXISTS invite_codes (
    id              TEXT PRIMARY KEY,
    code_hash       TEXT NOT NULL UNIQUE,  -- SHA-256 of the raw invite code
    workspace_id    TEXT NOT NULL REFERENCES workspaces(workspace_id),
    max_uses        INTEGER NOT NULL DEFAULT 1,
    used_count      INTEGER NOT NULL DEFAULT 0,
    expires_at      TEXT,
    status          TEXT NOT NULL DEFAULT 'active',  -- active | exhausted | revoked
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS browser_sessions (
    session_id          TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(user_id),
    workspace_id        TEXT NOT NULL,
    session_token_hash  TEXT NOT NULL UNIQUE,  -- SHA-256 of the raw session token
    expires_at          TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_browser_sessions_token
    ON browser_sessions(session_token_hash);
CREATE INDEX IF NOT EXISTS idx_browser_sessions_workspace
    ON browser_sessions(workspace_id);

-- =========================================================================
-- Job-workspace linkage (which workspace has seen/saved which jobs)
-- =========================================================================

CREATE TABLE IF NOT EXISTS job_workspace_links (
    id              TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(workspace_id),
    job_id          TEXT NOT NULL REFERENCES jobs(job_id),
    source_run_id   TEXT,
    seen_at         TEXT NOT NULL,   -- set when search run discovers this job
    saved_at        TEXT,            -- set when user explicitly saves
    archived_at     TEXT,            -- set when user archives
    UNIQUE(workspace_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_jwl_workspace ON job_workspace_links(workspace_id);
CREATE INDEX IF NOT EXISTS idx_jwl_job ON job_workspace_links(job_id);

-- =========================================================================
-- Runs and tasks
-- =========================================================================

CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(workspace_id),
    user_id             TEXT,
    run_type            TEXT NOT NULL,  -- search | process | reflect | full
    status              TEXT NOT NULL DEFAULT 'pending',
    agent_session_key   TEXT,   -- OpenClaw session key, if applicable
    artifact_root       TEXT,   -- path to run directory
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_workspace ON runs(workspace_id);

CREATE TABLE IF NOT EXISTS task_queue (
    task_id         TEXT PRIMARY KEY,
    workspace_id    TEXT NOT NULL,
    run_id          TEXT,
    task_type       TEXT NOT NULL,   -- job_report | fit_report | search_run | process_run
    status          TEXT NOT NULL DEFAULT 'pending',
    payload_json    TEXT,            -- JSON-encoded task input
    result_json     TEXT,            -- JSON-encoded task output on success
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_queue_status  ON task_queue(status);
CREATE INDEX IF NOT EXISTS idx_task_queue_workspace ON task_queue(workspace_id);

-- =========================================================================
-- Private analysis tables (workspace-scoped)
-- =========================================================================

CREATE TABLE IF NOT EXISTS candidate_profiles (
    candidate_profile_id    TEXT PRIMARY KEY,
    workspace_id            TEXT NOT NULL REFERENCES workspaces(workspace_id),
    profile_path            TEXT,   -- path to candidate_profile.json
    created_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_profiles_workspace
    ON candidate_profiles(workspace_id);

CREATE TABLE IF NOT EXISTS resume_versions (
    resume_version_id   TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES workspaces(workspace_id),
    file_path           TEXT,   -- path to original uploaded file
    parsed_path         TEXT,   -- path to extracted resume_profile.json
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resumes_workspace ON resume_versions(workspace_id);

CREATE TABLE IF NOT EXISTS fit_reports (
    fit_report_id           TEXT PRIMARY KEY,
    workspace_id            TEXT NOT NULL REFERENCES workspaces(workspace_id),
    job_id                  TEXT NOT NULL REFERENCES jobs(job_id),
    job_report_id           TEXT REFERENCES job_reports(job_report_id),
    candidate_profile_id    TEXT REFERENCES candidate_profiles(candidate_profile_id),
    resume_version_id       TEXT REFERENCES resume_versions(resume_version_id),
    report_path             TEXT,       -- path to fit_report narrative
    structured_path         TEXT,       -- path to fit_report structured JSON
    created_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fit_reports_workspace ON fit_reports(workspace_id);
CREATE INDEX IF NOT EXISTS idx_fit_reports_job ON fit_reports(job_id);
"""


# ---------------------------------------------------------------------------
# MetadataStore
# ---------------------------------------------------------------------------

class MetadataStore:
    """
    Thin wrapper around a SQLite connection.

    Thread safety: each request/worker should create its own MetadataStore
    instance (one connection per thread). Do not share instances across threads.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @classmethod
    def from_data_root(cls, data_root: Path) -> "MetadataStore":
        return cls(data_root / "app.sqlite")

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(
            self.db_path,
            timeout=10,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """
        Create all tables and indexes if they don't exist.
        Safe to call on every startup — fully idempotent.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_DDL)

    # -------------------------------------------------------------------------
    # Workspace helpers
    # -------------------------------------------------------------------------

    def get_or_create_workspace(
        self,
        workspace_id: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
            if row:
                return dict(row)
            now = _now_iso()
            conn.execute(
                "INSERT INTO workspaces (workspace_id, name, created_at) VALUES (?, ?, ?)",
                (workspace_id, name or workspace_id, now),
            )
            return {"workspace_id": workspace_id, "name": name or workspace_id, "created_at": now, "status": "active"}

    def get_or_create_user(
        self,
        user_id: str,
        workspace_id: str,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row:
                return dict(row)
            now = _now_iso()
            conn.execute(
                "INSERT INTO users (user_id, workspace_id, display_name, created_at) VALUES (?, ?, ?, ?)",
                (user_id, workspace_id, display_name or user_id, now),
            )
            return {"user_id": user_id, "workspace_id": workspace_id, "display_name": display_name or user_id, "created_at": now}

    # -------------------------------------------------------------------------
    # Job helpers
    # -------------------------------------------------------------------------

    def upsert_job_metadata(self, job_id: str, **fields: Any) -> None:
        """Insert or update a job row in the global jobs table."""
        now = _now_iso()
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT job_id FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if existing:
                set_clause = ", ".join(f"{k} = ?" for k in fields)
                values = list(fields.values()) + [now, job_id]
                conn.execute(
                    f"UPDATE jobs SET {set_clause}, updated_at = ? WHERE job_id = ?",
                    values,
                )
            else:
                cols = ["job_id", "created_at", "updated_at"] + list(fields.keys())
                placeholders = ", ".join("?" for _ in cols)
                values = [job_id, now, now] + list(fields.values())
                conn.execute(
                    f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders})",
                    values,
                )

    def link_job_to_workspace(
        self,
        workspace_id: str,
        job_id: str,
        run_id: str | None = None,
    ) -> None:
        """Record that a workspace's search run discovered this job (seen_at)."""
        now = _now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO job_workspace_links (id, workspace_id, job_id, source_run_id, seen_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, job_id) DO NOTHING
                """,
                (_new_id(), workspace_id, job_id, run_id, now),
            )

    # -------------------------------------------------------------------------
    # Job report helpers
    # -------------------------------------------------------------------------

    def get_active_job_report(
        self,
        job_id: str,
        jd_hash: str,
        prompt_version: str,
    ) -> dict[str, Any] | None:
        """Return an existing active report for the given cache key, or None."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM job_reports
                WHERE job_id = ? AND jd_hash = ? AND prompt_version = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (job_id, jd_hash, prompt_version),
            ).fetchone()
            return dict(row) if row else None

    def insert_job_report(
        self,
        job_id: str,
        jd_hash: str,
        prompt_version: str,
        model: str | None = None,
        report_path: str | None = None,
        structured_path: str | None = None,
        sources_path: str | None = None,
        job_report_id: str | None = None,
    ) -> str:
        """
        Insert a new active job report and supersede any older active report
        for the same (job_id, jd_hash, prompt_version).

        job_report_id: if provided, use this ID instead of generating a new one.
                       Useful when the caller pre-allocates the ID to determine
                       the artifact directory path before insertion.
        Returns the job_report_id (provided or generated).
        """
        if not job_report_id:
            job_report_id = "rpt_" + uuid.uuid4().hex[:8]
        now = _now_iso()
        with self._conn() as conn:
            # Supersede previous active reports for this job + prompt version
            # (jd_hash may differ if JD changed)
            old_rows = conn.execute(
                """
                SELECT job_report_id FROM job_reports
                WHERE job_id = ? AND prompt_version = ? AND status = 'active'
                """,
                (job_id, prompt_version),
            ).fetchall()
            for old in old_rows:
                conn.execute(
                    "UPDATE job_reports SET status = 'superseded', superseded_by = ? WHERE job_report_id = ?",
                    (job_report_id, old["job_report_id"]),
                )
            conn.execute(
                """
                INSERT INTO job_reports
                    (job_report_id, job_id, jd_hash, prompt_version, model, status,
                     report_path, structured_path, sources_path, created_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (job_report_id, job_id, jd_hash, prompt_version, model,
                 report_path, structured_path, sources_path, now),
            )
        return job_report_id

    # -------------------------------------------------------------------------
    # Run helpers
    # -------------------------------------------------------------------------

    def create_run(
        self,
        workspace_id: str,
        run_type: str,
        user_id: str | None = None,
        agent_session_key: str | None = None,
        artifact_root: str | None = None,
    ) -> str:
        """Create a new run record. Returns run_id."""
        run_id = "run_" + _now_iso().replace(":", "").replace("-", "").replace("T", "_").replace("+", "")[:15]
        now = _now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO runs
                    (run_id, workspace_id, user_id, run_type, status,
                     agent_session_key, artifact_root, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (run_id, workspace_id, user_id, run_type,
                 agent_session_key, artifact_root, now, now),
            )
        return run_id

    def update_run_status(self, run_id: str, status: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status, _now_iso(), run_id),
            )

    # -------------------------------------------------------------------------
    # Task queue helpers
    # -------------------------------------------------------------------------

    def create_task(
        self,
        workspace_id: str,
        task_type: str,
        payload: dict[str, Any],
        run_id: str | None = None,
    ) -> str:
        """Enqueue a new task. Returns task_id."""
        import json as _json
        task_id = "task_" + uuid.uuid4().hex[:10]
        now = _now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO task_queue
                    (task_id, workspace_id, run_id, task_type, status, payload_json, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (task_id, workspace_id, run_id, task_type, _json.dumps(payload), now),
            )
        return task_id

    def claim_next_pending_task(self) -> dict[str, Any] | None:
        """
        Atomically claim the oldest pending task by setting it to 'running'.
        Returns the task row or None if no pending tasks.
        Safe for single-worker usage with SQLite WAL mode.
        """
        import json as _json
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM task_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE task_queue SET status = 'running', started_at = ? WHERE task_id = ?",
                (_now_iso(), row["task_id"]),
            )
            now = _now_iso()
            task = dict(row)
            task["status"] = "running"
            task["started_at"] = now
            task["payload"] = _json.loads(task.get("payload_json") or "{}")
            return task

    def complete_task(
        self,
        task_id: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        import json as _json
        status = "failed" if error else "completed"
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE task_queue
                SET status = ?, finished_at = ?, result_json = ?, error_message = ?
                WHERE task_id = ?
                """,
                (
                    status,
                    _now_iso(),
                    _json.dumps(result) if result else None,
                    error,
                    task_id,
                ),
            )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        import json as _json
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM task_queue WHERE task_id = ?", (task_id,)
            ).fetchone()
            if not row:
                return None
            task = dict(row)
            task["payload"] = _json.loads(task.get("payload_json") or "{}")
            task["result"] = _json.loads(task.get("result_json") or "null")
            return task

    # -------------------------------------------------------------------------
    # Dev workspace bootstrap
    # -------------------------------------------------------------------------

    def bootstrap_dev_workspace(self) -> None:
        """
        Ensure the dev_default workspace and user exist in the metadata store.
        Called automatically by CLI tools on startup.
        """
        self.get_or_create_workspace("dev_default", name="Local Dev Workspace")
        self.get_or_create_user("dev_user", "dev_default", display_name="Dev User")
