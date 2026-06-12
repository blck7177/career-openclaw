"""
Run routes.

GET /api/runs                 — list runs in workspace
GET /api/runs/{run_id}        — run detail (config + summary JSON)
GET /api/runs/{run_id}/summary — run_summary.md markdown content
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status

from apps.api.deps import CtxDep
from career_intelligence.services import run_service

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("")
def list_runs(
    ctx: CtxDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """List runs in the workspace, newest first."""
    return run_service.list_runs(ctx, limit=limit)


@router.get("/{run_id}")
def get_run(ctx: CtxDep, run_id: str) -> dict[str, Any]:
    """Return full run metadata (config merged with summary JSON)."""
    run = run_service.get_run(ctx, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


@router.get("/{run_id}/summary")
def get_run_summary(ctx: CtxDep, run_id: str) -> Response:
    """
    Return run_summary.md as plain text/markdown.

    Returns 404 if the run does not exist or has no summary yet.
    """
    content = run_service.get_run_summary(ctx, run_id)
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run summary not available",
        )
    return Response(content=content, media_type="text/markdown; charset=utf-8")
