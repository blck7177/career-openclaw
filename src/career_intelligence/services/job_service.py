"""
JobService — workspace-scoped job record queries.

Jobs live in data/workspaces/<workspace_id>/db/jobs.jsonl (append-only JSONL).
The job_index.json maps job_id → line number for O(1) point lookups.

All functions take RequestContext as first argument.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.workspace_paths import get_workspace_paths
from career_intelligence.storage_jsonl import query_jobs


def list_jobs(
    ctx: RequestContext,
    *,
    workstream: str | None = None,
    company: str | None = None,
    since: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Return jobs visible in the workspace, with optional filters.

    workstream : substring match against primary_workstream / secondary_workstreams
    company    : substring match against company name (case-insensitive)
    since      : ISO date string "YYYY-MM-DD" — only jobs found on or after this date
    limit      : max records returned (default 100)
    """
    paths = get_workspace_paths(ctx.workspace_id)
    return query_jobs(
        paths.db_dir,
        workstream=workstream,
        company=company,
        since=since,
        limit=limit,
    )


def get_job(ctx: RequestContext, job_id: str) -> dict[str, Any] | None:
    """
    Return a single job record by job_id, or None if not found.

    Uses job_index.json for O(1) line lookup to avoid scanning the full JSONL.
    Falls back to a full scan if the index is stale or missing.
    """
    paths = get_workspace_paths(ctx.workspace_id)
    jobs_path = paths.jobs_db
    index_path = paths.job_index

    if not jobs_path.exists():
        return None

    # Fast path: use index if available
    if index_path.exists():
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
        entry = index.get("by_job_id", {}).get(job_id)
        if entry is not None:
            line_no = entry["line"]
            record = _read_line(jobs_path, line_no)
            if record and record.get("job_id") == job_id:
                return record

    # Slow path: full scan (index missing or stale)
    return _scan_for_job(jobs_path, job_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_line(path: Path, line_no: int) -> dict[str, Any] | None:
    """Read a specific zero-indexed line from a JSONL file."""
    try:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i == line_no:
                    line = line.strip()
                    if line:
                        return json.loads(line)
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _scan_for_job(path: Path, job_id: str) -> dict[str, Any] | None:
    """Scan jobs.jsonl and return the last record matching job_id."""
    found: dict[str, Any] | None = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if record.get("job_id") == job_id:
                        found = record
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return found
