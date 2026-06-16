"""
Agent Service — drives OpenClaw for job discovery sessions.

Worker-side orchestration of job discovery. The worker owns the session
lifecycle; the bounded agents only run their own bounded action. Workflow:

  1. start_session()       — Python direct call (creates run directory + run_config.yaml)
  2. agent_gateway.invoke  — drive career-search-agent (search turns only) via the
                             generic gateway; gateway parses real tool_calls
  3. Provenance validation — abort if 0 web_search calls AND queries_run == 0
  4. end_session()         — worker finalizes the session (agent no longer ends it)
  5. run_processing_pipeline() — deterministic, called directly in Python
  6. Reflect turn          — drive the bounded career-reflect-agent (it only writes
                             strategy_patch.json + reflection_report.md); the worker
                             validates the patch and applies it to strategy_state.json
                             (Service owns persistence; agent never writes final state)

Environment overrides (all optional):
  AGENT_TURN_TIMEOUT_S      Per-turn subprocess timeout in seconds  (default 180)
  AGENT_RUN_MAX_TURNS       Max search agent turns per session      (default 40)
  AGENT_REFLECT_MAX_TURNS   Max reflect agent turns                 (default 3)
  AGENT_RUN_WALL_CLOCK_S    Total wall-clock limit in seconds       (default 3600)
  OPENCLAW_AGENT_ID         Search agent id to invoke               (default career-search-agent)
  OPENCLAW_REFLECT_AGENT_ID Reflect agent id to invoke              (default career-reflect-agent)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from career_intelligence.app_state.workspace_paths import (
    get_catalog_workspace_id,
    get_repo_root,
    get_workspace_paths,
)
from career_intelligence.services import agent_gateway
from career_intelligence.runner import run_processing_pipeline
from career_intelligence.search_session import (
    end_session,
    get_session_status,
    session_dir,
    start_session,
)
from career_intelligence.strategy_state import (
    StrategyPatchError,
    apply_strategy_patch,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AGENT_TURN_TIMEOUT_S = int(os.environ.get("AGENT_TURN_TIMEOUT_S", "180"))
AGENT_RUN_MAX_TURNS = int(os.environ.get("AGENT_RUN_MAX_TURNS", "40"))
AGENT_REFLECT_MAX_TURNS = int(os.environ.get("AGENT_REFLECT_MAX_TURNS", "3"))
AGENT_RUN_WALL_CLOCK_S = int(os.environ.get("AGENT_RUN_WALL_CLOCK_S", "3600"))
# All three production lanes are bounded agents driven through agent_gateway:
# discovery → career-search-agent, reflect → career-reflect-agent. The legacy
# monolith career-intel is no longer used in production (kept registered for
# manual/debug runs only).
_OPENCLAW_AGENT_ID = os.environ.get("OPENCLAW_AGENT_ID", "career-search-agent")
_REFLECT_AGENT_ID = os.environ.get("OPENCLAW_REFLECT_AGENT_ID", "career-reflect-agent")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SearchValidationError(Exception):
    """Raised when agent output fails provenance validation (zero real queries)."""


class AgentRunError(Exception):
    """Raised for unrecoverable agent run failures (bad binary, wall-clock, etc.)."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _reflect_input_spec(
    session_id: str, run_summary_path: Path, coverage_path: Path,
    strategy_patch_path: Path, reflection_report_path: Path,
) -> dict[str, Any]:
    """Structured task spec the bounded reflect agent reads (instead of a long prompt)."""
    return {
        "session_id": session_id,
        "run_summary_path": str(run_summary_path),
        "coverage_report_path": str(coverage_path),
        "expected_output_paths": {
            "strategy_patch": str(strategy_patch_path),
            "reflection_report": str(reflection_report_path),
        },
    }


def _search_input_spec(
    session_id: str, workspace_id: str, profile_name: str, search_brief: str,
    max_queries: int, max_pages: int, coverage_path: Path,
) -> dict[str, Any]:
    """Structured task spec the bounded search agent reads (instead of a long prompt)."""
    return {
        "session_id": session_id,
        # The workspace the worker created the session in. The agent must pass
        # this to every wrapper (--workspace-id) so its writes land in the same
        # workspace, not the CLI default — see resolve_workspace_root().
        "workspace_id": workspace_id,
        "profile_name": profile_name,
        "search_brief": search_brief,
        "max_queries": max_queries,
        "max_pages": max_pages,
        "expected_output_paths": {
            "coverage_draft": str(coverage_path),
        },
    }


def _search_prompt(session_id: str, workspace_id: str, input_spec_path: Path) -> str:
    """Task envelope only. Workflow/tool order/admission gates/stopping rules live
    in the career-search-turn-operator skill + references (single source of truth);
    the prompt never restates them."""
    return (
        "You are executing a bounded career search turn.\n\n"
        "Read and follow the career-search-turn-operator skill and its references. "
        "They are the source of truth for workflow, tool order, candidate admission "
        "gates, and stopping rules. If anything in this prompt appears to conflict "
        "with the skill, follow the skill.\n\n"
        f"Read your task spec from: {input_spec_path}\n"
        f"  session_id   : {session_id}\n"
        f"  workspace_id : {workspace_id}\n\n"
        "Write the expected output to the path given in the task spec, then STOP."
    )


def _reflect_prompt(session_id: str, input_spec_path: Path) -> str:
    """Task envelope only. Workflow/diagnosis focus/patch contract/stopping rules
    live in the career-reflect-operator skill + references (single source of truth);
    the prompt never restates them."""
    return (
        "You are executing a bounded post-run reflection turn.\n\n"
        "Read and follow the career-reflect-operator skill and its references. "
        "They are the source of truth for workflow, diagnosis focus, the strategy "
        "patch contract, and stopping rules. If anything in this prompt appears to "
        "conflict with the skill, follow the skill.\n\n"
        f"Read your task spec from: {input_spec_path}\n"
        f"  session_id : {session_id}\n\n"
        "Write the expected outputs to the paths given in the task spec, then STOP."
    )


def _run_reflect(
    *,
    session_id: str,
    workspace_root: Path,
    session_root: Path,
    repo_root: Path,
) -> dict[str, Any]:
    """
    Drive the bounded career-reflect-agent, then deterministically apply its
    strategy patch. The agent only writes strategy_patch.json + reflection_report.md;
    this function (the worker) is the sole writer of strategy_state.json.

    Best-effort: the caller treats any exception as non-fatal. Returns a small
    summary {reflected, patch_applied[, runs_completed]}.
    """
    run_summary_path = session_root / "run_summary.md"
    coverage_path = session_root / "coverage_report.md"
    strategy_patch_path = session_root / "strategy_patch.json"
    reflection_report_path = session_root / "reflection_report.md"
    input_spec_path = session_root / "reflect_input.json"
    run_log_path = session_root / "reflect_run_log.json"

    invocation = agent_gateway.AgentInvocation(
        agent_id=_REFLECT_AGENT_ID,
        prompt=_reflect_prompt(session_id, input_spec_path),
        repo_root=repo_root,
        expected_outputs=[strategy_patch_path, reflection_report_path],
        input_spec=_reflect_input_spec(
            session_id, run_summary_path, coverage_path,
            strategy_patch_path, reflection_report_path,
        ),
        input_spec_path=input_spec_path,
        run_log_path=run_log_path,
        turn_timeout_s=AGENT_TURN_TIMEOUT_S,
        max_turns=AGENT_REFLECT_MAX_TURNS,
        wall_clock_s=AGENT_RUN_WALL_CLOCK_S,
    )

    run_result = agent_gateway.invoke(invocation)

    if not strategy_patch_path.exists():
        logger.warning(
            "Reflect for %s produced no strategy_patch.json (status=%s) — "
            "strategy state unchanged", session_id, run_result.status,
        )
        return {"reflected": True, "patch_applied": False}

    try:
        patch = json.loads(strategy_patch_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Reflect patch for %s unreadable: %s", session_id, exc)
        return {"reflected": True, "patch_applied": False}

    try:
        updated = apply_strategy_patch(workspace_root, session_id, patch)
    except StrategyPatchError as exc:
        logger.warning("Reflect patch for %s rejected: %s", session_id, exc)
        return {"reflected": True, "patch_applied": False}

    logger.info(
        "Reflect applied for %s: runs_completed=%d",
        session_id, updated.get("runs_completed", 0),
    )
    return {
        "reflected": True,
        "patch_applied": True,
        "runs_completed": updated.get("runs_completed", 0),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_discovery_session(
    *,
    profile_name: str,
    search_brief: str,
    mode: str = "exploratory",
    max_queries: int = 30,
    max_pages: int = 40,
) -> dict[str, Any]:
    """
    Drive a full OpenClaw discovery run (search → validate → process → reflect).

    Returns:
        {session_id, run_id, turns_used, search_complete,
         queries_run, candidates_captured,
         jobs_fetched, jobs_structured, jobs_saved, jobs_failed}

    Raises:
        SearchValidationError  — agent produced 0 queries (fabrication detected)
        AgentRunError          — unrecoverable failure (openclaw not found, wall-clock)
    """
    catalog_id = get_catalog_workspace_id()
    workspace_root = get_workspace_paths(catalog_id).root
    repo_root = get_repo_root()
    # The agent must write to the SAME workspace the worker creates the session
    # in; it receives this id in the input_spec and passes it to every wrapper.

    # 1. Start session (Python direct — no subprocess needed)
    sess = start_session(
        workspace_root=workspace_root,
        profile_name=profile_name,
        mode=mode,
        max_queries=max_queries,
        max_fetched_pages=max_pages,
    )
    session_id: str = sess["session_id"]
    logger.info("Search session started: %s (profile=%s)", session_id, profile_name)

    # 2. Drive the bounded search agent via the generic gateway
    session_root = session_dir(workspace_root, session_id)
    coverage_draft = session_root / "coverage_draft.md"
    input_spec_path = session_root / "agent_input.json"
    run_log_path = session_root / "agent_run_log.json"

    invocation = agent_gateway.AgentInvocation(
        agent_id=_OPENCLAW_AGENT_ID,
        prompt=_search_prompt(session_id, catalog_id, input_spec_path),
        repo_root=repo_root,
        expected_outputs=[coverage_draft],
        input_spec=_search_input_spec(
            session_id, catalog_id, profile_name, search_brief,
            max_queries, max_pages, coverage_draft,
        ),
        input_spec_path=input_spec_path,
        run_log_path=run_log_path,
        turn_timeout_s=AGENT_TURN_TIMEOUT_S,
        max_turns=AGENT_RUN_MAX_TURNS,
        wall_clock_s=AGENT_RUN_WALL_CLOCK_S,
    )

    try:
        run_result = agent_gateway.invoke(invocation)
    except agent_gateway.AgentGatewayError as exc:
        raise AgentRunError(str(exc)) from exc

    web_search_calls = sum(
        1 for tc in run_result.tool_calls if tc.get("tool") == "web_search"
    )
    search_complete = run_result.status == "complete"
    logger.info(
        "Search agent finished: status=%s turns=%d web_search_calls=%d",
        run_result.status, run_result.turns_used, web_search_calls,
    )

    # 3. Provenance validation — hard gate before pipeline.
    # Ground truth: real web_search tool calls from the run log. Fallback: the
    # search ledger's queries_run. Both zero == fabrication → abort (discovery
    # has no value without candidates; unlike research, we do NOT degrade).
    final_status = get_session_status(workspace_root, session_id)
    queries_run = final_status.get("queries_run", 0)
    candidates_captured = final_status.get("candidates_captured", 0)

    if web_search_calls == 0 and queries_run == 0:
        raise SearchValidationError(
            f"Agent produced 0 web_search calls and 0 logged queries for session "
            f"{session_id}. Pipeline aborted — fabricated candidates would corrupt "
            f"the catalog. Fix: ensure agent executes real web_search before "
            f"career_log_candidates."
        )

    if candidates_captured == 0:
        logger.warning(
            "Session %s: queries_run=%d but 0 candidates captured — "
            "pipeline will process an empty pool",
            session_id, queries_run,
        )

    # 4. Worker finalizes the session (the bounded agent no longer ends it)
    if not coverage_draft.exists():
        logger.warning(
            "Session %s: agent did not write coverage_report; writing a stub so the "
            "session can be finalized", session_id,
        )
        coverage_draft.write_text(
            f"# Coverage Report (auto-stub)\n\n"
            f"session_id: {session_id}\n"
            f"queries_run: {queries_run}\n"
            f"candidates_captured: {candidates_captured}\n"
            f"note: agent finished with status={run_result.status} without writing a "
            f"coverage report.\n",
            encoding="utf-8",
        )
    end_result = end_session(workspace_root, session_id, str(coverage_draft))
    if end_result.get("error"):
        logger.warning("end_session for %s returned: %s", session_id, end_result["error"])

    # 5. Deterministic processing pipeline (Python direct — no subprocess)
    candidates_file = session_root / "candidate_pool.jsonl"
    logger.info("Starting processing pipeline for session %s (%d candidates)", session_id, candidates_captured)

    pipeline_result = run_processing_pipeline(
        workspace_root=workspace_root,
        session_id=session_id,
        candidates_file=candidates_file,
        config_root=repo_root,
    )
    logger.info(
        "Pipeline complete: fetched=%d saved=%d failed=%d",
        pipeline_result.get("jobs_fetched", 0),
        pipeline_result.get("jobs_saved", 0),
        pipeline_result.get("jobs_failed", 0),
    )

    # 6. Reflect turn — bounded career-reflect-agent writes a strategy patch;
    # the worker validates + applies it (best-effort, never fatal to the run).
    try:
        _run_reflect(
            session_id=session_id,
            workspace_root=workspace_root,
            session_root=session_root,
            repo_root=repo_root,
        )
        logger.info("Reflect complete for session %s", session_id)
    except Exception as exc:  # noqa: BLE001 — reflect is best-effort, never fatal
        logger.warning("Reflect failed (non-fatal): %s", exc)

    return {
        "session_id": session_id,
        "run_id": session_id,
        "turns_used": run_result.turns_used,
        "search_complete": search_complete,
        "queries_run": queries_run,
        "candidates_captured": candidates_captured,
        "jobs_fetched": pipeline_result.get("jobs_fetched", 0),
        "jobs_structured": pipeline_result.get("jobs_structured", 0),
        "jobs_saved": pipeline_result.get("jobs_saved", 0),
        "jobs_failed": pipeline_result.get("jobs_failed", 0),
        "duration_seconds": pipeline_result.get("duration_seconds", 0),
    }
