"""
Job routes.

GET /api/jobs                      — list jobs in workspace
GET /api/jobs/{job_id}             — job detail
GET /api/jobs/{job_id}/job-report  — active Job Intelligence Report for this job
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from apps.api.deps import CtxDep
from career_intelligence.services import job_service, report_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    ctx: CtxDep,
    workstream: str | None = Query(default=None, description="Substring filter on workstream"),
    company: str | None = Query(default=None, description="Substring filter on company name"),
    since: str | None = Query(default=None, description="ISO date YYYY-MM-DD lower bound"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    """List job records visible in the workspace."""
    return job_service.list_jobs(
        ctx,
        workstream=workstream,
        company=company,
        since=since,
        limit=limit,
    )


@router.get("/{job_id}")
def get_job(ctx: CtxDep, job_id: str) -> dict[str, Any]:
    """Return a single job record."""
    job = job_service.get_job(ctx, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("/{job_id}/job-report")
def get_job_report(ctx: CtxDep, job_id: str) -> dict[str, Any]:  # noqa: ARG001
    """
    Return the active Job Intelligence Report for this job.

    ctx is required for auth but the report itself is global (not workspace-scoped).
    Returns 404 if no report has been generated yet.
    """
    report = report_service.get_job_report(job_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No job report found. Trigger analysis via POST /api/jobs/{job_id}/analyze (Sprint 3).",
        )
    return report
