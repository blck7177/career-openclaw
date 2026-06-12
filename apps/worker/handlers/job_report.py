"""
Handler for task_type = 'job_report'.

Called by the worker main loop when a job_report task is claimed.
Delegates entirely to analysis_service.create_job_report().

Exceptions are intentionally NOT caught here — the worker's dispatch()
function wraps each handler call and writes any exception to the task's
error_message field.
"""

from __future__ import annotations

from typing import Any

from career_intelligence.app_state.context import RequestContext
from career_intelligence.services import analysis_service
from career_intelligence.services.task_service import complete_task


def handle_job_report(task: dict[str, Any]) -> None:
    """
    Execute a job_report task.

    Expected payload:
        { "job_id": str, "force": bool (optional, default False) }
    """
    payload = task.get("payload") or {}
    job_id: str = payload["job_id"]
    force: bool = bool(payload.get("force", False))
    workspace_id: str = task["workspace_id"]

    ctx = RequestContext(workspace_id=workspace_id, user_id="worker")
    result = analysis_service.create_job_report(ctx, job_id, force=force)
    complete_task(task["task_id"], result=result)
