"""
User-facing discovery runs API — v2.

POST /api/discovery-runs
    Enqueue a search_run task using a candidate profile plus structured search
    parameters. Workspace-scoped (requires session auth).

    The worker will:
      1. Compile structured search_params into a canonical instruction string.
      2. Run the Intent Translator to produce a DiscoveryIntent.
      3. Run the ObjectiveController (up to 2 attempts) to meet target_new_jobs.

    Body (all fields except profile_id are optional with sensible defaults):
        profile_id          str          candidate_profile_id (required)
        search_mode         str          auto | directed_discovery |
                                         profile_based_exploration | gap_fill_discovery
        search_params       SearchParams Structured filters (location, seniority, etc.)
        target_new_jobs     int          Objective: new jobs to insert (1–50, default 10)
        search_depth        str          fast | balanced | deep (maps to query/page budget)
        additional_instruction str       Free-text direction appended to compiled instruction

    Response 202:
        { "task_id": str, "run_id": str, "message": str, "requested_mode": str }

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

_VALID_SEARCH_DEPTHS = frozenset({"fast", "balanced", "deep"})

_VALID_SEARCH_SOURCES = frozenset(
    {"instruction_only", "profile_only", "instruction_plus_profile"}
)

# Budget per attempt for each search_depth level.
# Each attempt uses the same per-attempt budget; the ObjectiveController splits
# the total across attempts internally (attempt 1 gets ~60%).
_DEPTH_BUDGET: dict[str, dict[str, int]] = {
    "fast":     {"max_queries": 20,  "max_pages": 25},
    "balanced": {"max_queries": 40,  "max_pages": 60},
    "deep":     {"max_queries": 80,  "max_pages": 120},
}


class SearchParams(BaseModel):
    """Structured search filters exposed in the UI Search Builder."""

    location: list[str] = Field(
        default_factory=list,
        description="Target locations, e.g. ['NYC', 'Jersey City', 'US Remote'].",
    )
    remote_policy: str = Field(
        "flexible",
        description="on-site | hybrid | remote | flexible.",
    )
    seniority: list[str] = Field(
        default_factory=list,
        description="Target seniority levels, e.g. ['Analyst', 'Associate'].",
    )
    max_years_experience: int | None = Field(
        None,
        ge=0,
        le=20,
        description="Maximum years of relevant experience; null means unconstrained.",
    )
    workstreams: list[str] = Field(
        default_factory=list,
        description="Target workstream families, e.g. ['Market Risk', 'Valuation Control'].",
    )
    company_types: list[str] = Field(
        default_factory=list,
        description="Preferred company types, e.g. ['bank', 'asset_manager', 'hedge_fund'].",
    )
    exclusions: list[str] = Field(
        default_factory=list,
        description="Role types or keywords to exclude, e.g. ['model_validation', 'audit'].",
    )


class DiscoveryRunRequest(BaseModel):
    """
    Discovery run request — v2.

    Backward-compatible with v1 (user_instruction / requested_mode / max_queries /
    max_pages are still accepted).  New structured fields take precedence when
    present: search_mode overrides requested_mode, search_depth overrides
    max_queries/max_pages.
    """

    profile_id: str = Field(..., description="candidate_profile_id from the profiles API")

    # --- v2 structured fields ---
    search_mode: str = Field(
        "auto",
        description=(
            "auto | directed_discovery | profile_based_exploration | gap_fill_discovery. "
            "Overrides the legacy requested_mode field when both are provided."
        ),
    )
    search_params: SearchParams = Field(
        default_factory=SearchParams,
        description="Structured search filters compiled into a canonical instruction.",
    )
    target_new_jobs: int = Field(
        10,
        ge=1,
        le=50,
        description="Objective: number of new (not already in catalog) jobs to insert.",
    )
    search_depth: str = Field(
        "balanced",
        description=(
            "fast (20q/25p) | balanced (40q/60p) | deep (80q/120p). "
            "Maps to per-attempt query/page budget. Overrides max_queries/max_pages."
        ),
    )
    additional_instruction: str = Field(
        "",
        description=(
            "Free-text direction appended to the compiled instruction string. "
            "Useful for nuances not captured by structured params."
        ),
    )
    search_source: str = Field(
        "instruction_plus_profile",
        description=(
            "instruction_only | profile_only | instruction_plus_profile. "
            "Controls which inputs the Intent Translator may use for hard constraints. "
            "instruction_only: use only the submitted instruction/params, ignore profile. "
            "profile_only: use only the candidate profile, treat instruction as a style hint. "
            "instruction_plus_profile: instruction sets hard constraints, profile enriches lanes."
        ),
    )

    # --- v1 legacy fields (still accepted for backward compat) ---
    user_instruction: str = Field(
        "",
        description=(
            "[Legacy] Natural-language instruction. Prefer additional_instruction "
            "when using v2 structured fields."
        ),
    )
    requested_mode: str = Field(
        "auto",
        description="[Legacy] Use search_mode instead.",
    )
    max_queries: int | None = Field(
        None,
        ge=1,
        le=120,
        description="[Legacy] Hard query budget override. Use search_depth instead.",
    )
    max_pages: int | None = Field(
        None,
        ge=1,
        le=160,
        description="[Legacy] Hard page budget override. Use search_depth instead.",
    )


class DiscoveryRunResponse(BaseModel):
    task_id: str
    run_id: str
    message: str = "discovery_run task enqueued"
    requested_mode: str


def _compile_instruction(params: SearchParams, instruction: str) -> str:
    """
    Compile structured SearchParams + free-text instruction into a single
    canonical instruction string for the Intent Translator.

    Each non-empty field produces one clause; clauses are joined with ". ".
    The free-text instruction is appended last so the translator can reconcile
    structured constraints with any nuance in the text.
    """
    parts: list[str] = []

    if params.location:
        parts.append("Location: " + ", ".join(params.location))

    if params.remote_policy and params.remote_policy != "flexible":
        parts.append(f"Remote policy: {params.remote_policy}")

    if params.seniority:
        parts.append("Seniority: " + ", ".join(params.seniority))

    if params.max_years_experience is not None:
        parts.append(f"Max years experience: {params.max_years_experience}")

    if params.workstreams:
        parts.append("Workstreams: " + ", ".join(params.workstreams))

    if params.company_types:
        parts.append("Company types: " + ", ".join(params.company_types))

    if params.exclusions:
        parts.append("Exclude: " + ", ".join(params.exclusions))

    if instruction:
        parts.append(instruction)

    return ". ".join(parts)


def _resolve_budget(body: DiscoveryRunRequest) -> tuple[int, int]:
    """
    Resolve total query/page budget from the request.

    Priority: search_depth > legacy max_queries/max_pages > defaults.
    When search_depth is provided (non-default), it always wins.
    When max_queries/max_pages are explicitly set, they override the defaults.
    """
    depth_is_set = body.search_depth in _VALID_SEARCH_DEPTHS
    if depth_is_set:
        budget = _DEPTH_BUDGET.get(body.search_depth, _DEPTH_BUDGET["balanced"])
        return budget["max_queries"], budget["max_pages"]

    # Fall back to legacy explicit budget or defaults
    return (
        body.max_queries if body.max_queries is not None else 40,
        body.max_pages if body.max_pages is not None else 60,
    )


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
    Trigger a user-facing discovery run via the Intent Translator + ObjectiveController.

    Accepts both v2 structured params (search_mode, search_params, target_new_jobs,
    search_depth) and the legacy v1 fields (user_instruction, requested_mode,
    max_queries, max_pages) for backward compatibility.

    Poll the returned task_id via GET /api/discovery-runs/{task_id}.
    """
    # Resolve effective mode (v2 search_mode overrides v1 requested_mode)
    effective_mode = body.search_mode if body.search_mode != "auto" else body.requested_mode
    if effective_mode not in _VALID_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid mode {effective_mode!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_MODES))}"
            ),
        )

    if body.search_depth not in _VALID_SEARCH_DEPTHS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid search_depth {body.search_depth!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_SEARCH_DEPTHS))}"
            ),
        )

    if body.search_source not in _VALID_SEARCH_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid search_source {body.search_source!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_SEARCH_SOURCES))}"
            ),
        )

    # Verify profile exists (fail fast rather than enqueue a doomed task).
    profile = get_profile(ctx, body.profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate profile not found: {body.profile_id}",
        )

    # Enforce at-most-one active search_run per workspace.
    if task_service.count_active_tasks(ctx, "search_run") >= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A discovery run is already pending or running for this workspace.",
        )

    # Compile instruction: structured params + additional_instruction + legacy user_instruction
    compiled_instruction = _compile_instruction(
        body.search_params,
        body.additional_instruction or body.user_instruction,
    )

    # instruction_only requires at least one filter or free-text instruction.
    # An empty compiled_instruction would leave the translator with no signal,
    # producing undefined behaviour under the no-silent-defaults rule.
    if body.search_source == "instruction_only" and not compiled_instruction.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="instruction_only requires at least one filter or instruction",
        )

    # Resolve budget
    max_queries, max_pages = _resolve_budget(body)

    run_id = task_service.create_run(ctx, "discovery")
    task_id = task_service.create_task(
        ctx,
        task_type="search_run",
        payload={
            "profile_id": body.profile_id,
            # source_workspace_id ensures worker loads the profile from the
            # correct workspace (profiles are workspace-scoped).
            "source_workspace_id": ctx.workspace_id,
            "user_instruction": compiled_instruction,
            "requested_mode": effective_mode,
            "target_new_jobs": body.target_new_jobs,
            "max_queries": max_queries,
            "max_pages": max_pages,
            # Pass structured params so the worker can build hard_constraints
            # directly without re-parsing the compiled instruction string.
            "search_params": body.search_params.model_dump(),
            "search_depth": body.search_depth,
            "search_source": body.search_source,
        },
        run_id=run_id,
    )
    return DiscoveryRunResponse(
        task_id=task_id,
        run_id=run_id,
        requested_mode=effective_mode,
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
