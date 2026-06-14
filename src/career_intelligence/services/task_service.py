"""
TaskService — async task queue management.

Tasks are workspace-scoped entries in the SQLite task_queue table.
The worker process polls this table and dispatches by task_type.

Supported task_type values (Sprint 3+):
  job_report   — generate a Job Intelligence Report for a job_id
  fit_report   — generate a Candidate Fit Report (Sprint 5)
  search_run   — trigger a search run (future)
  process_run  — trigger a process run (future)

All create/query functions interact with MetadataStore only.
Workspace-scoped operations take RequestContext; task lookup does not.
"""

from __future__ import annotations

from typing import Any

from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import get_data_root


def _store() -> MetadataStore:
    store = MetadataStore.from_data_root(get_data_root())
    store.init_schema()
    return store


def create_task(
    ctx: RequestContext,
    task_type: str,
    payload: dict[str, Any],
    *,
    run_id: str | None = None,
) -> str:
    """
    Enqueue a new task for the worker.

    Returns the task_id. The task starts in 'pending' status.
    """
    return _store().create_task(
        workspace_id=ctx.workspace_id,
        task_type=task_type,
        payload=payload,
        run_id=run_id,
    )


def get_task(task_id: str) -> dict[str, Any] | None:
    """
    Return the current state of a task by task_id, or None if not found.

    The returned dict includes:
      task_id, workspace_id, task_type, status, payload, result,
      created_at, started_at, finished_at, error_message
    """
    return _store().get_task(task_id)


def poll_pending_tasks(
    task_types: list[str] | None = None,
) -> dict[str, Any] | None:
    """
    Atomically claim the oldest pending task, setting its status to 'running'.

    task_types: optional allowlist — only tasks of these types are claimed.
                Pass None to claim any pending task (default, single-worker).
                Pass a list to restrict to specific types, enabling separate
                fast-lane and agent-lane worker processes.

    Returns the claimed task dict (with decoded payload), or None if the queue
    has no eligible pending tasks.  Intended for the worker process main loop —
    call in a tight loop with a sleep on None.
    """
    return _store().claim_next_pending_task(task_types=task_types)


def complete_task(
    task_id: str,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """
    Mark a task as completed (or failed if error is provided).
    """
    _store().complete_task(task_id, result=result, error=error)


def list_tasks(
    ctx: RequestContext,
    *,
    status: str | None = None,
    task_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    List tasks for a workspace, newest first.

    status    : filter by status ('pending', 'running', 'completed', 'failed')
    task_type : filter by task_type
    limit     : max records returned
    """
    import json as _json

    store = _store()
    where_clauses = ["workspace_id = ?"]
    params: list[Any] = [ctx.workspace_id]

    if status:
        where_clauses.append("status = ?")
        params.append(status)
    if task_type:
        where_clauses.append("task_type = ?")
        params.append(task_type)

    params.append(limit)
    where_sql = " AND ".join(where_clauses)

    with store._conn() as conn:
        rows = conn.execute(
            f"""
            SELECT task_id, workspace_id, run_id, task_type, status,
                   payload_json, result_json, created_at, started_at,
                   finished_at, error_message
            FROM task_queue
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    result = []
    for row in rows:
        t = dict(row)
        t["payload"] = _json.loads(t.pop("payload_json") or "{}")
        t["result"] = _json.loads(t.pop("result_json") or "null")
        result.append(t)
    return result
