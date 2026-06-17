"""
User-facing discovery runs API.

POST /api/discovery-runs
    Enqueue a search_run task using a candidate profile and optional natural-language
    instruction. Workspace-scoped (requires session auth) — available to regular users,
    unlike the operator-only /api/operator/agent-runs endpoint.

    The worker will run the Intent Translator before invoking the discovery agent,
    producing a structured DiscoveryIntent that allocates query budget across lanes
    and enforces hard constraints from the user instruction.

    Body:
        profile_id        str   candidate_profile_id (required)
        user_instruction  str   Free-text direction or empty for profile-based exploration
        requested_mode    str   "auto" | "directed_discovery" | "profile_based_exploration"
                                | "gap_fill_discovery"  (default "auto")
        max_queries       int   Hard query budget    (default 30)
        max_pages         int   Hard fetch-page budget (default 40)

    Response 202:
        { "task_id": str, "message": str, "discovery_mode": str }

GET /api/discovery-runs/{task_id}
    Poll status and result of a discovery run task.
    Returns the task dict (status, result, error_message).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.deps import CtxDep
from career_intelligence.services import task_service
from career_intelligence.services.profile_service import get_profile

router = APIRouter(prefix="/api/discovery-runs", tags=["discovery-runs"])

_VALID_MODES = frozenset(
    {"auto", "directed_discovery", "profile_based_exploration", "gap_fill_discovery"}
)


class DiscoveryRunRequest(BaseModel):
    profile_id: str = Field(..., description="candidate_profile_id from the profiles API")
    user_instruction: str = Field(
        "",
        description=(
            "Natural-language instruction. Leave empty to trigger profile-based exploration "
            "where lanes are inferred entirely from the candidate profile."
        ),
    )
    requested_mode: str = Field(
        "auto",
        description=(
            "auto | directed_discovery | profile_based_exploration | gap_fill_discovery. "
            "auto lets the Intent Translator decide based on instruction content."
        ),
    )
    max_queries: int = Field(30, ge=1, le=60, description="Hard query budget per run")
    max_pages: int = Field(40, ge=1, le=80, description="Hard fetch-page budget per run")


class DiscoveryRunResponse(BaseModel):
    task_id: str
    message: str = "discovery_run task enqueued"
    requested_mode: str


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DiscoveryRunResponse,
)
def enqueue_discovery_run(
    body: DiscoveryRunRequest,
    ctx: CtxDep,
) -> DiscoveryRunResponse:
    """
    Trigger a user-facing discovery run via the Intent Translator pipeline.

    Validates that the referenced profile exists in the user's workspace, then
    enqueues a search_run task with the new payload format. The agent-lane
    worker will claim it and run: Intent Translator → search agent → process
    pipeline → reflect.

    Poll the returned task_id via GET /api/discovery-runs/{task_id} or
    GET /api/tasks/{task_id}.
    """
    if body.requested_mode not in _VALID_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid requested_mode {body.requested_mode!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_MODES))}"
            ),
        )

    # Verify the profile exists (fail fast rather than enqueue a doomed task).
    profile = get_profile(ctx, body.profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate profile not found: {body.profile_id}",
        )

    task_id = task_service.create_task(
        ctx,
        task_type="search_run",
        payload={
            "profile_id": body.profile_id,
            "user_instruction": body.user_instruction,
            "requested_mode": body.requested_mode,
            "max_queries": body.max_queries,
            "max_pages": body.max_pages,
        },
    )
    return DiscoveryRunResponse(
        task_id=task_id,
        requested_mode=body.requested_mode,
    )


@router.get("/{task_id}")
def get_discovery_run(
    task_id: str,
    ctx: CtxDep,
) -> dict[str, Any]:
    """
    Poll the status and result of a discovery run task.

    Returns the full task dict (task_id, status, result, error_message, created_at).
    The task must belong to the caller's workspace.
    """
    task = task_service.get_task(task_id)
    if task is None or task.get("workspace_id") != ctx.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discovery run not found: {task_id}",
        )
    return task
