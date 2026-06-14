"""
Handler for task_type = 'job_report'.

Called by the worker main loop when a job_report task is claimed.
Delegates entirely to analysis_service.create_job_report().

Exceptions are intentionally NOT caught here — the worker's dispatch()
function wraps each handler call and writes any exception to the task's
error_message field.
"""

from __future__ import annotations

import logging
from typing import Any

from career_intelligence.app_state.context import RequestContext
from career_intelligence.services import analysis_service, research_service
from career_intelligence.services.task_service import complete_task

logger = logging.getLogger(__name__)


def handle_job_report(task: dict[str, Any]) -> None:
    """
    Execute a job_report task.

    Expected payload:
        {
          "job_id": str,
          "force": bool (optional, default False),
          "with_research": bool (optional, default False)
        }

    When with_research is true, the worker first produces and validates a
    web-research bundle (career-research) and passes it to the report.
    A failed bundle degrades gracefully to a JD-only report.
    """
    payload = task.get("payload") or {}
    job_id: str = payload["job_id"]
    force: bool = bool(payload.get("force", False))
    with_research: bool = bool(payload.get("with_research", False))
    workspace_id: str = task["workspace_id"]

    ctx = RequestContext(workspace_id=workspace_id, user_id="worker")

    research_bundle = None
    if with_research:
        research_bundle = research_service.ensure_research_bundle(ctx, job_id, force=force)
        logger.info(
            "job_report %s research bundle: status=%s verified=%d/%d",
            job_id,
            research_bundle.get("validation_status"),
            research_bundle.get("verified_source_count", 0),
            research_bundle.get("source_count", 0),
        )

    result = analysis_service.create_job_report(
        ctx, job_id, force=force, research_bundle=research_bundle
    )
    complete_task(task["task_id"], result=result)
