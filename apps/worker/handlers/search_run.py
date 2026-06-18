"""Worker handler for search_run tasks.

Invoked by the agent-lane worker when a search_run task is claimed.
Drives a full OpenClaw discovery session (search → process → reflect)
against the shared catalog workspace.

Two payload formats are supported:

Legacy (operator) path — triggered by POST /api/operator/agent-runs:
    profile_name  str   Search profile name from configs/search_profiles.yaml
    search_brief  str   Free-text objective for the agent
    mode          str   "exploratory" | "refresh"  (optional, default exploratory)
    max_queries   int   Hard query budget            (optional, default 30)
    max_pages     int   Hard fetch-page budget       (optional, default 40)

New (user) path — triggered by POST /api/discovery-runs:
    profile_id          str   candidate_profile_id from profiles table
    source_workspace_id str   workspace that owns the profile (for multi-workspace safety)
    user_instruction    str   Raw user instruction (may be empty for profile-based exploration)
    requested_mode      str   "auto" | "directed_discovery" | "profile_based_exploration"
                              | "gap_fill_discovery"  (optional, default "auto")
    target_new_jobs     int   Objective: number of new jobs to insert   (optional, default 10)
    max_queries         int   Total query budget split across attempts  (optional, default 30)
    max_pages           int   Total fetch-page budget                   (optional, default 40)
    search_params       dict  Structured search parameters              (optional)

The new path runs the Intent Translator to produce a DiscoveryIntent, then
delegates to the ObjectiveController which runs up to 2 attempts and aggregates
results into a FinalSearchResult.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.workspace_paths import (
    get_catalog_workspace_id,
    get_repo_root,
    get_workspace_paths,
)
from career_intelligence.llm_client import make_client
from career_intelligence.services import task_service
from career_intelligence.services.agent_service import (
    AgentRunError,
    SearchValidationError,
    _build_catalog_context,
    _build_strategy_context,
)
from career_intelligence.services.intent_translator import (
    IntentTranslatorError,
    translate as translate_intent,
)
from career_intelligence.objective_controller import (
    ObjectiveController,
    SearchObjective,
)
from career_intelligence.search_session import session_dir

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# New path (profile_id + user_instruction) — ObjectiveController
# ---------------------------------------------------------------------------


def _handle_new_path(
    task_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Resolve profile, run Intent Translator, then run ObjectiveController
    (up to 2 attempts) to meet the target_new_jobs objective.

    Returns a FinalSearchResult dict.
    Raises on unrecoverable errors (caller writes task failure).
    """
    from career_intelligence.services.profile_service import get_profile

    profile_id: str = payload["profile_id"]
    user_instruction: str = payload.get("user_instruction", "")
    requested_mode: str = payload.get("requested_mode", "auto")
    search_source: str = payload.get("search_source", "instruction_plus_profile")
    target_new_jobs: int = int(payload.get("target_new_jobs", 10))
    total_queries: int = int(payload.get("max_queries", 30))
    total_pages: int = int(payload.get("max_pages", 40))

    catalog_id = get_catalog_workspace_id()
    workspace_root = get_workspace_paths(catalog_id).root
    repo_root = get_repo_root()

    # 1. Resolve candidate profile from its source workspace.
    source_workspace_id = payload.get("source_workspace_id", catalog_id)
    profile_ctx = RequestContext(
        workspace_id=source_workspace_id,
        user_id="worker",
        session_id=task_id,
    )
    profile = get_profile(profile_ctx, profile_id)
    if profile is None:
        raise ValueError(f"Candidate profile not found: {profile_id}")

    logger.info(
        "search_run task %s (new path): profile=%s instruction=%.80s mode=%s source=%s target=%d",
        task_id, profile_id, user_instruction, requested_mode, search_source, target_new_jobs,
    )

    # 2. Build catalog and strategy context.
    catalog_context = _build_catalog_context(catalog_id, workspace_root)
    strategy_context = _build_strategy_context(workspace_root)

    # 3. Run Intent Translator to produce a structured DiscoveryIntent.
    try:
        intent = translate_intent(
            profile=profile,
            user_instruction=user_instruction,
            catalog_context=catalog_context,
            strategy_context=strategy_context,
            workspace_root=workspace_root,
            repo_root=repo_root,
            requested_mode=requested_mode,
            search_source=search_source,
            session_root=None,
        )
    except IntentTranslatorError as exc:
        raise RuntimeError(f"Intent translation failed: {exc}") from exc

    logger.info(
        "search_run task %s: intent_kind=%s lanes=%d",
        task_id, intent.get("intent_kind", "?"), len(intent.get("search_lanes", [])),
    )

    # 4. Build search_brief from profile fields.
    profile_summary_parts: list[str] = []
    if profile.get("current_background"):
        profile_summary_parts.append(profile["current_background"])
    if profile.get("domain_experience"):
        profile_summary_parts.append(
            "Domains: " + ", ".join(profile["domain_experience"][:4])
        )
    if profile.get("target_workstreams"):
        profile_summary_parts.append(
            "Target workstreams: " + ", ".join(profile["target_workstreams"])
        )
    search_brief = user_instruction or " | ".join(profile_summary_parts) or "profile-based discovery"

    # 5. Build SearchObjective from intent + request params.
    #    Extract hard constraints from search_params if present (Phase 3 path)
    #    or fall back to whatever the intent translator produced.
    search_params = payload.get("search_params") or {}
    hard_constraints: dict[str, Any] = {}
    if search_params:
        if search_params.get("location"):
            hard_constraints["location"] = search_params["location"]
        if search_params.get("seniority"):
            hard_constraints["seniority"] = search_params["seniority"]
        if search_params.get("max_years_experience") is not None:
            hard_constraints["max_years_experience"] = search_params["max_years_experience"]
        if search_params.get("workstreams"):
            hard_constraints["workstreams"] = search_params["workstreams"]
        if search_params.get("exclusions"):
            hard_constraints["exclusions"] = search_params["exclusions"]

    soft_preferences: dict[str, Any] = {}
    if search_params.get("company_types"):
        soft_preferences["company_types"] = search_params["company_types"]
    if search_params.get("remote_policy"):
        soft_preferences["remote_policy"] = search_params["remote_policy"]

    objective = SearchObjective.from_intent_and_request(
        objective_id=task_id,
        target_new_jobs=target_new_jobs,
        total_queries=total_queries,
        total_pages=total_pages,
        max_attempts=2,
        discovery_intent=intent,
        search_mode=requested_mode,
        additional_instruction=user_instruction,
        hard_constraints=hard_constraints or None,
        soft_preferences=soft_preferences or None,
    )

    logger.info(
        "search_run task %s: objective created target=%d a1=%dq/%dp a2=%dq/%dp",
        task_id, objective.target_new_jobs,
        objective.attempt_1_queries, objective.attempt_1_pages,
        objective.attempt_2_queries, objective.attempt_2_pages,
    )

    # 6. Run ObjectiveController (multi-attempt).
    llm_client = make_client()
    controller = ObjectiveController(objective, llm_client)
    final_result = controller.run(
        profile_name=profile_id,
        search_brief=search_brief,
        discovery_intent=intent,
    )

    # 7. Best-effort: persist translator artifacts into the last session directory.
    last_session_id = final_result.last_session_id
    if last_session_id:
        try:
            s_root = session_dir(workspace_root, last_session_id)
            from career_intelligence.services.intent_translator import (
                build_input_envelope,
                persist_artifacts,
                _load_workstream_taxonomy,
            )
            taxonomy = _load_workstream_taxonomy(repo_root)
            envelope = build_input_envelope(
                profile=profile,
                user_instruction=user_instruction,
                catalog_context=catalog_context,
                strategy_context=strategy_context,
                workstream_taxonomy=taxonomy,
                requested_mode=requested_mode,
                search_source=search_source,
            )
            persist_artifacts(s_root, envelope, intent)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "search_run task %s: could not persist translator artifacts: %s",
                task_id, exc,
            )

    return final_result.to_dict()


# ---------------------------------------------------------------------------
# Legacy path (profile_name + search_brief)
# ---------------------------------------------------------------------------


def _handle_legacy_path(
    task_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Original operator-only flow — unchanged behaviour."""
    profile_name: str = payload.get("profile_name", "")
    search_brief: str = payload.get("search_brief", "")

    if not profile_name:
        raise ValueError("Missing required payload field: profile_name")
    if not search_brief:
        raise ValueError("Missing required payload field: search_brief")

    logger.info(
        "search_run task %s (legacy path): profile=%s brief=%.80s",
        task_id, profile_name, search_brief,
    )

    return run_discovery_session(
        profile_name=profile_name,
        search_brief=search_brief,
        mode=payload.get("mode", "exploratory"),
        max_queries=int(payload.get("max_queries", 30)),
        max_pages=int(payload.get("max_pages", 40)),
        discovery_intent=None,
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def handle_search_run(task: dict[str, Any]) -> None:
    """Claim and execute a search_run task end-to-end."""
    task_id = task["task_id"]
    run_id: str | None = task.get("run_id")
    payload = task.get("payload", {})

    if run_id:
        task_service.update_run_status(run_id, "running")
    try:
        # Route to the appropriate path based on payload shape.
        if "profile_id" in payload:
            result = _handle_new_path(task_id, payload)
        else:
            result = _handle_legacy_path(task_id, payload)

        if run_id:
            task_service.update_run_status(run_id, "completed")
        task_service.complete_task(task_id, result=result)
        logger.info(
            "search_run task %s complete: session=%s queries=%d inserted=%d updated=%d",
            task_id,
            result.get("session_id"),
            result.get("queries_run", 0),
            result.get("new_jobs_inserted", 0),
            result.get("existing_jobs_updated", 0),
        )

    except SearchValidationError as exc:
        # Agent produced zero queries — fabrication detected; fail the task so
        # the operator can see it clearly, but don't crash the worker.
        logger.error("search_run task %s validation failure: %s", task_id, exc)
        if run_id:
            task_service.update_run_status(run_id, "failed")
        task_service.complete_task(task_id, error=f"SearchValidationError: {exc}")

    except AgentRunError as exc:
        logger.error("search_run task %s agent error: %s", task_id, exc)
        if run_id:
            task_service.update_run_status(run_id, "failed")
        task_service.complete_task(task_id, error=f"AgentRunError: {exc}")
