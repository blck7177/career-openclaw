"""
Report routes — global Job Intelligence Reports.

GET /api/reports/jobs/{job_id}         — active report for a job
GET /api/reports/jobs/{job_id}/history — all versions (active + superseded)

These routes mirror /api/jobs/{job_id}/job-report but live under /api/reports/
for callers that work with reports directly (e.g. the worker, admin tools).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from apps.api.deps import CtxDep
from career_intelligence.services import report_service

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/jobs/{job_id}")
def get_job_report(ctx: CtxDep, job_id: str) -> dict[str, Any]:  # noqa: ARG001
    """Return the active Job Intelligence Report for a job."""
    report = report_service.get_job_report(job_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No report found")
    return report


@router.get("/jobs/{job_id}/history")
def list_job_reports(ctx: CtxDep, job_id: str) -> list[dict[str, Any]]:  # noqa: ARG001
    """Return all report versions for a job (active + superseded), newest first."""
    return report_service.list_job_reports(job_id)
