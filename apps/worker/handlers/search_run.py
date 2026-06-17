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
    profile_id       str   candidate_profile_id from profiles table
    user_instruction str   Raw user instruction (may be empty for profile-based exploration)
    requested_mode   str   "auto" | "directed_discovery" | "profile_based_exploration"
                           | "gap_fill_discovery"  (optional, default "auto")
    max_queries      int   Hard query budget            (optional, default 30)
    max_pages        int   Hard fetch-page budget       (optional, default 40)

The new path runs the Intent Translator before invoking the discovery agent,
producing a structured DiscoveryIntent written into the session artifacts
(translator_input.json + discovery_intent.json) for auditability.
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
from career_intelligence.services import task_service
from career_intelligence.services.agent_service import (
    AgentRunError,
    SearchValidationError,
    _build_catalog_context,
    _build_strategy_context,
    run_discovery_session,
)
from career_intelligence.services.intent_translator import (
    IntentTranslatorError,
    translate as translate_intent,
)
from career_intelligence.search_session import session_dir

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# New path (profile_id + user_instruction)
# ---------------------------------------------------------------------------


def _handle_new_path(
    task_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Resolve profile, run Intent Translator, then call run_discovery_session
    with the resulting DiscoveryIntent.

    Returns the result dict from run_discovery_session.
    Raises on unrecoverable errors (caller writes task failure).
    """
    from career_intelligence.services.profile_service import get_profile

    profile_id: str = payload["profile_id"]
    user_instruction: str = payload.get("user_instruction", "")
    requested_mode: str = payload.get("requested_mode", "auto")
    max_queries: int = int(payload.get("max_queries", 30))
    max_pages: int = int(payload.get("max_pages", 40))

    catalog_id = get_catalog_workspace_id()
    workspace_root = get_workspace_paths(catalog_id).root
    repo_root = get_repo_root()

    # 1. Resolve candidate profile from the workspace it was created in.
    #    Profiles are workspace-scoped; we look up using the catalog workspace
    #    context since discovery runs write to the catalog workspace.
    ctx = RequestContext(
        workspace_id=catalog_id,
        user_id="worker",
        session_id=task_id,
    )
    profile = get_profile(ctx, profile_id)
    if profile is None:
        raise ValueError(f"Candidate profile not found: {profile_id}")

    logger.info(
        "search_run task %s (new path): profile=%s instruction=%.80s mode=%s",
        task_id, profile_id, user_instruction, requested_mode,
    )

    # 2. Build catalog and strategy context (same as agent_service does internally).
    catalog_context = _build_catalog_context(catalog_id, workspace_root)
    strategy_context = _build_strategy_context(workspace_root)

    # 3. Run Intent Translator to produce a structured DiscoveryIntent.
    #    We pass session_root=None here because we don't have a session_id yet;
    #    the translator artifacts will be persisted by run_discovery_session's
    #    session directory. We call translate() without session_root so it
    #    returns the intent, and then persist from the handler after session creation.
    #    NOTE: session_root persistence is best-effort (warn, never fail).
    try:
        intent = translate_intent(
            profile=profile,
            user_instruction=user_instruction,
            catalog_context=catalog_context,
            strategy_context=strategy_context,
            workspace_root=workspace_root,
            repo_root=repo_root,
            requested_mode=requested_mode,
            session_root=None,  # will persist after session is created below
        )
    except IntentTranslatorError as exc:
        raise RuntimeError(f"Intent translation failed: {exc}") from exc

    logger.info(
        "search_run task %s: intent_kind=%s lanes=%d",
        task_id, intent.get("intent_kind", "?"), len(intent.get("search_lanes", [])),
    )

    # 4. Use profile summary from profile fields as the search_brief for the agent
    #    (provides human-readable fallback if agent reads the old search_request fields).
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

    # 5. Run the full discovery session with the structured intent.
    result = run_discovery_session(
        profile_name=profile_id,
        search_brief=search_brief,
        mode="exploratory",
        max_queries=max_queries,
        max_pages=max_pages,
        discovery_intent=intent,
    )

    # 6. Best-effort: persist translator artifacts into the session directory
    #    now that we have the session_id from the result.
    session_id = result.get("session_id")
    if session_id:
        try:
            s_root = session_dir(workspace_root, session_id)
            from career_intelligence.services.intent_translator import (
                build_input_envelope,
                persist_artifacts,
            )
            from career_intelligence.services.intent_translator import _load_workstream_taxonomy
            taxonomy = _load_workstream_taxonomy(repo_root)
            envelope = build_input_envelope(
                profile=profile,
                user_instruction=user_instruction,
                catalog_context=catalog_context,
                strategy_context=strategy_context,
                workstream_taxonomy=taxonomy,
                requested_mode=requested_mode,
            )
            persist_artifacts(s_root, envelope, intent)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "search_run task %s: could not persist translator artifacts: %s",
                task_id, exc,
            )

    return result


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
            "search_run task %s complete: session=%s queries=%d saved=%d",
            task_id,
            result.get("session_id"),
            result.get("queries_run", 0),
            result.get("jobs_saved", 0),
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
