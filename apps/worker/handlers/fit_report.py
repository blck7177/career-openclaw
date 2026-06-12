"""
Handler for task_type = 'fit_report'.

Called by the worker main loop when a fit_report task is claimed.
Delegates entirely to match_service.create_fit_report().

Convention: handler internally calls complete_task() on success.
Exceptions are NOT caught here — worker dispatch() wraps each handler
and writes any exception to the task's error_message field.
This is identical to handle_job_report().
"""

from __future__ import annotations

from typing import Any

from career_intelligence.app_state.context import RequestContext
from career_intelligence.services import match_service
from career_intelligence.services.task_service import complete_task


def handle_fit_report(task: dict[str, Any]) -> None:
    """
    Execute a fit_report task.

    Expected payload:
        { "job_id": str, "profile_id": str, "force": bool (optional, default False) }
    """
    payload = task.get("payload") or {}
    job_id: str = payload["job_id"]
    profile_id: str = payload["profile_id"]
    force: bool = bool(payload.get("force", False))
    workspace_id: str = task["workspace_id"]

    ctx = RequestContext(workspace_id=workspace_id, user_id="worker")
    result = match_service.create_fit_report(ctx, job_id, profile_id, force=force)
    complete_task(task["task_id"], result=result)
