"""
Fit report routes — Sprint 4-lite.

POST /api/jobs/{job_id}/fit            — enqueue async Fit Report generation
GET  /api/fit-reports/{fit_report_id}  — fetch completed Fit Report artifact
GET  /api/jobs/{job_id}/fit-reports    — list Fit Reports for a job
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from apps.api.deps import CtxDep
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import get_data_root
from career_intelligence.services import task_service

router = APIRouter(tags=["fit-reports"])


# ---------------------------------------------------------------------------
# POST /api/jobs/{job_id}/fit  — enqueue async generation
# ---------------------------------------------------------------------------


class FitRequest(BaseModel):
    profile_id: str
    force: bool = False


class FitEnqueueResponse(BaseModel):
    task_id: str
    message: str = "Fit report task enqueued"


@router.post(
    "/api/jobs/{job_id}/fit",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=FitEnqueueResponse,
)
def enqueue_fit_report(
    job_id: str,
    body: FitRequest,
    ctx: CtxDep,
) -> FitEnqueueResponse:
    """
    Enqueue an async Candidate Fit Report generation task.

    The worker executes the task.  Poll GET /api/tasks/{task_id} to check
    progress.  When status is 'completed', the report is available at
    GET /api/fit-reports/{fit_report_id} (fit_report_id is in task result).
    """
    task_id = task_service.create_task(
        ctx,
        task_type="fit_report",
        payload={"job_id": job_id, "profile_id": body.profile_id, "force": body.force},
    )
    return FitEnqueueResponse(task_id=task_id)


# ---------------------------------------------------------------------------
# GET /api/fit-reports/{fit_report_id}  — fetch artifact
# ---------------------------------------------------------------------------


@router.get("/api/fit-reports/{fit_report_id}")
def get_fit_report(
    fit_report_id: str,
    ctx: CtxDep,  # noqa: ARG001 — validates auth
) -> dict[str, Any]:
    """
    Return a completed Candidate Fit Report.

    Response shape:
        {
          "structured": { ...full fit report JSON... },
          "narrative_md": "..."
        }

    Does NOT include task metadata — use GET /api/tasks/{task_id} for that.
    """
    data_root = get_data_root()
    store = MetadataStore.from_data_root(data_root)
    store.init_schema()

    row = store.get_fit_report(fit_report_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fit report not found: {fit_report_id}",
        )

    structured = _read_json(row.get("structured_path"))
    narrative_md = _read_text(row.get("report_path"))

    return {
        "structured": structured,
        "narrative_md": narrative_md,
    }


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/fit-reports  — list for a job
# ---------------------------------------------------------------------------


@router.get("/api/jobs/{job_id}/fit-reports")
def list_fit_reports(
    job_id: str,
    ctx: CtxDep,
) -> list[dict[str, Any]]:
    """
    List all Candidate Fit Reports for a job in this workspace, newest first.

    Returns summary rows only — use GET /api/fit-reports/{id} for full content.
    """
    data_root = get_data_root()
    store = MetadataStore.from_data_root(data_root)
    store.init_schema()

    rows = store.list_fit_reports(workspace_id=ctx.workspace_id, job_id=job_id)

    # Load overall_match_score from structured JSON for each row
    result = []
    for row in rows:
        entry: dict[str, Any] = {
            "fit_report_id": row["fit_report_id"],
            "candidate_profile_id": row.get("candidate_profile_id"),
            "job_report_id": row.get("job_report_id"),
            "created_at": row["created_at"],
            "overall_match_score": None,
        }
        structured = _read_json(row.get("structured_path"))
        if isinstance(structured, dict):
            entry["overall_match_score"] = structured.get("overall_match_score")
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path_str: str | None) -> Any:
    if not path_str:
        return None
    try:
        p = Path(path_str)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _read_text(path_str: str | None) -> str | None:
    if not path_str:
        return None
    try:
        p = Path(path_str)
        if p.exists():
            return p.read_text(encoding="utf-8")
    except OSError:
        pass
    return None
