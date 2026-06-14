"""
Operator-only agent-runs API.

POST /api/operator/agent-runs
    Enqueue a search_run task against the shared catalog workspace.
    Operator-only: triggers an OpenClaw agent run + LLM processing — not for
    regular users.  Guard is enforced via the OPERATOR_TOKEN env var; when
    DEV_MODE=1 the X-Dev-Context: dev header also bypasses the guard.

    Body:
        profile_name  str   Name of a search profile in configs/search_profiles.yaml
        search_brief  str   Free-text objective passed to the agent
        mode          str   "exploratory" | "refresh"  (default exploratory)
        max_queries   int   Hard query budget           (default 30)
        max_pages     int   Hard fetch-page budget      (default 40)

    Response 202:
        { "task_id": str, "message": str }

GET /api/operator/agent-runs/{task_id}
    Convenience alias for GET /api/tasks/{task_id} scoped to the catalog
    workspace.  Returns status + result once the search_run completes.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.workspace_paths import get_catalog_workspace_id
from career_intelligence.services import task_service

router = APIRouter(prefix="/api/operator", tags=["operator"])

_DEV_MODE = os.getenv("DEV_MODE", "0") == "1" and os.getenv("ENV", "development") != "production"
_OPERATOR_TOKEN = os.getenv("OPERATOR_TOKEN", "")


def _require_operator(x_operator_token: str | None) -> None:
    """
    Enforce operator-only access.

    In DEV_MODE the check is skipped (allows curl testing without a token).
    In production, the X-Operator-Token header must match OPERATOR_TOKEN.
    A missing or empty OPERATOR_TOKEN env var disables the endpoint entirely
    unless DEV_MODE is active.
    """
    if _DEV_MODE:
        return
    if not _OPERATOR_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator endpoint not configured (OPERATOR_TOKEN not set)",
        )
    if x_operator_token != _OPERATOR_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-Operator-Token header",
        )


def _catalog_ctx() -> RequestContext:
    return RequestContext(
        workspace_id=get_catalog_workspace_id(),
        user_id="operator",
        session_id="operator-session",
    )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class AgentRunRequest(BaseModel):
    profile_name: str = Field(..., description="Search profile from configs/search_profiles.yaml")
    search_brief: str = Field(..., description="Free-text objective for the agent")
    mode: str = Field("exploratory", description="exploratory | refresh")
    max_queries: int = Field(30, ge=1, le=60, description="Hard query budget")
    max_pages: int = Field(40, ge=1, le=80, description="Hard fetch-page budget")


class AgentRunResponse(BaseModel):
    task_id: str
    message: str = "search_run task enqueued"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/agent-runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AgentRunResponse,
)
def enqueue_agent_run(
    body: AgentRunRequest,
    x_operator_token: str | None = Header(default=None),
) -> AgentRunResponse:
    """
    Trigger a full OpenClaw discovery run against the shared catalog.

    Enqueues a search_run task.  The agent-lane worker will claim and execute
    it (search → validate → process → reflect).  Poll the returned task_id via
    GET /api/tasks/{task_id} or GET /api/operator/agent-runs/{task_id}.
    """
    _require_operator(x_operator_token)

    task_id = task_service.create_task(
        _catalog_ctx(),
        task_type="search_run",
        payload={
            "profile_name": body.profile_name,
            "search_brief": body.search_brief,
            "mode": body.mode,
            "max_queries": body.max_queries,
            "max_pages": body.max_pages,
        },
    )
    return AgentRunResponse(task_id=task_id)


@router.get("/agent-runs/{task_id}")
def get_agent_run(
    task_id: str,
    x_operator_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    Poll the status and result of a search_run task.

    Returns the full task dict (status, result, error_message).
    Task is looked up in the catalog workspace — not user-scoped.
    """
    _require_operator(x_operator_token)

    task = task_service.get_task(task_id)
    if task is None or task.get("workspace_id") != get_catalog_workspace_id():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent run not found: {task_id}",
        )
    return task
