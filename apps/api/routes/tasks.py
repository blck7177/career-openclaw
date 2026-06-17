"""
Task routes — Sprint 3.

POST /api/jobs/{job_id}/analyze    Enqueue a job_report task, return 202 + task_id.
GET  /api/tasks/{task_id}          Poll task status and result.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from apps.api.deps import CtxDep
from career_intelligence.services import task_service

router = APIRouter(tags=["tasks"])


# ---------------------------------------------------------------------------
# POST /api/jobs/{job_id}/analyze
# ---------------------------------------------------------------------------


class AnalyzeResponse(BaseModel):
    task_id: str
    message: str = "Analysis task enqueued"


@router.post(
    "/api/jobs/{job_id}/analyze",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AnalyzeResponse,
)
def enqueue_job_analysis(
    job_id: str,
    ctx: CtxDep,
    force: bool = False,
    with_research: bool = False,
) -> AnalyzeResponse:
    """
    Enqueue an async Job Intelligence Report generation task.

    The task is executed by the worker process.  Poll GET /api/tasks/{task_id}
    to check progress.  When status is 'completed', the report is available at
    GET /api/jobs/{job_id}/job-report.

    Query params:
        force (bool, default False): re-generate even if a cached report exists.
        with_research (bool, default False): run career-research first to
            produce a validated web-research bundle and generate a
            research-augmented report (degrades to JD-only if research fails).
    """
    if not force:
        existing = task_service.find_active_task(
            ctx, "job_report", {"job_id": job_id}
        )
        if existing:
            return AnalyzeResponse(task_id=existing["task_id"])

    task_id = task_service.create_task(
        ctx,
        task_type="job_report",
        payload={"job_id": job_id, "force": force, "with_research": with_research},
    )
    return AnalyzeResponse(task_id=task_id)


# ---------------------------------------------------------------------------
# GET /api/tasks/{task_id}
# ---------------------------------------------------------------------------


@router.get("/api/tasks/{task_id}")
def get_task(task_id: str, ctx: CtxDep) -> dict[str, Any]:
    """
    Return the current status and result of a task.

    Possible status values: pending | running | completed | failed

    On 'completed', result contains:
        { "job_report_id": str, "status": "created" | "cache_hit",
          "report_path": str, "structured_path": str }

    On 'failed', error_message contains the reason.

    Workspace-scoped: a task is only visible to its owning workspace.  Requests
    for a task belonging to another workspace get 404 (not 403) so existence is
    not leaked.
    """
    task = task_service.get_task(task_id)
    if task is None or task.get("workspace_id") != ctx.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )
    return task
