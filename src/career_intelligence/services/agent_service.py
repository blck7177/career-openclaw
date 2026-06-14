"""
Agent Service — drives OpenClaw for job discovery sessions.

Translates the monitor_search.sh driving loop into a Python adapter that can
be called from the worker. Workflow:

  1. start_session()       — Python direct call (creates run directory + run_config.yaml)
  2. Agent driving loop    — subprocess `openclaw agent --message ...` with per-turn timeout
  3. Provenance validation — abort if queries_run == 0 (fabrication guard)
  4. run_processing_pipeline() — deterministic, called directly in Python
  5. Reflect turn          — final agent subprocess call for strategy update

Environment overrides (all optional):
  AGENT_TURN_TIMEOUT_S    Per-turn subprocess timeout in seconds   (default 180)
  AGENT_RUN_MAX_TURNS     Max agent turns per session              (default 40)
  AGENT_RUN_WALL_CLOCK_S  Total wall-clock limit in seconds        (default 3600)
  OPENCLAW_AGENT_ID       OpenClaw agent id to invoke              (default career-intel)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from career_intelligence.app_state.workspace_paths import (
    get_catalog_workspace_id,
    get_repo_root,
    get_workspace_paths,
)
from career_intelligence.runner import run_processing_pipeline
from career_intelligence.search_session import get_session_status, start_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AGENT_TURN_TIMEOUT_S = int(os.environ.get("AGENT_TURN_TIMEOUT_S", "180"))
AGENT_RUN_MAX_TURNS = int(os.environ.get("AGENT_RUN_MAX_TURNS", "40"))
AGENT_RUN_WALL_CLOCK_S = int(os.environ.get("AGENT_RUN_WALL_CLOCK_S", "3600"))
_OPENCLAW_AGENT_ID = os.environ.get("OPENCLAW_AGENT_ID", "career-intel")


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


def _openclaw_turn(message: str, repo_root: Path) -> dict[str, Any]:
    """
    Send one message to the OpenClaw agent, return parsed JSON output.

    Raises subprocess.TimeoutExpired if the agent exceeds AGENT_TURN_TIMEOUT_S.
    On non-zero exit or unparseable JSON, returns a dict with raw_output/exit_code.
    """
    cmd = [
        "openclaw", "agent",
        "--agent", _OPENCLAW_AGENT_ID,
        "--local",
        "--message", message,
        "--json",
    ]
    logger.info("OpenClaw turn → %.80s…", message)
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=AGENT_TURN_TIMEOUT_S,
    )
    stdout = (proc.stdout or "").strip()
    if proc.returncode != 0:
        logger.warning(
            "openclaw exit %d  stderr: %.200s", proc.returncode, proc.stderr or ""
        )
    # Output may have a non-JSON leading line from streamed output; find first '{'.
    json_start = stdout.find("{")
    if json_start != -1:
        try:
            return json.loads(stdout[json_start:])
        except json.JSONDecodeError:
            pass
    return {"raw_output": stdout[:500], "exit_code": proc.returncode}


def _run_status(workspace_root: Path, session_id: str) -> str:
    """Read the run_config.yaml status field, e.g. 'search_in_progress' | 'search_complete'."""
    rc_path = workspace_root / "runs" / session_id / "run_config.yaml"
    if not rc_path.exists():
        return "unknown"
    with open(rc_path) as f:
        rc = yaml.safe_load(f) or {}
    return rc.get("status", "unknown")


def _budget_remaining(workspace_root: Path, session_id: str) -> int:
    status = get_session_status(workspace_root, session_id)
    return status.get("budget_used", {}).get("queries_remaining", 0)


def _search_prompt_initial(
    session_id: str, profile_name: str, search_brief: str,
    max_queries: int, max_pages: int,
) -> str:
    return (
        f"Read the career-search-operator skill, then execute Steps 2 and 3 only.\n\n"
        f"IMPORTANT — Step 1 (session start) is ALREADY DONE. "
        f"Do NOT call career_search_session start. The session is already created:\n"
        f"  session_id : {session_id}\n"
        f"  profile    : {profile_name}\n"
        f"  budget     : {max_queries} queries, {max_pages} fetched pages\n\n"
        f"Your objective: {search_brief}\n\n"
        f"Start immediately at Step 2 (Search Loop):\n"
        f"  web_search → web_fetch → career_log_candidates\n"
        f"  Use --session-id {session_id} for all wrapper calls.\n\n"
        f"REQUIRED: Execute real web_search calls before career_log_candidates. "
        f"The system REJECTS candidates when queries_run=0.\n\n"
        f"When done (≥20 candidates or budget exhausted), complete Step 3:\n"
        f"  write coverage_report.md, then call:\n"
        f"  career_search_session end --session-id {session_id} --coverage-report <path>"
    )


def _search_prompt_continue(session_id: str, queries_run: int, candidates: int, remaining: int) -> str:
    return (
        f"Continue session {session_id}. "
        f"Progress so far: queries_run={queries_run}, candidates_captured={candidates}, "
        f"budget_remaining={remaining} queries.\n"
        f"Continue web_search → web_fetch → career_log_candidates loop. "
        f"When done (≥20 candidates or budget exhausted), write coverage_report.md "
        f"and call career_search_session end."
    )


def _reflect_prompt(session_id: str) -> str:
    return (
        f"Processing pipeline for session {session_id} is complete. "
        f"Please read run_summary.md for session {session_id}, then call "
        f"career_update_strategy to record this run's learnings into strategy_state.json. "
        f"Focus on: which sources produced real JDs, which failed, and "
        f"recommended next search directions."
    )


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

    # 2. Agent driving loop — mirrors monitor_search.sh multi-turn pattern
    wall_start = time.time()
    turn = 0
    search_complete = False

    while turn < AGENT_RUN_MAX_TURNS:
        elapsed = time.time() - wall_start
        if elapsed > AGENT_RUN_WALL_CLOCK_S:
            logger.warning(
                "Wall-clock limit (%ds) reached after %d turns — stopping search phase",
                AGENT_RUN_WALL_CLOCK_S, turn,
            )
            raise AgentRunError(
                f"Wall-clock limit of {AGENT_RUN_WALL_CLOCK_S}s exceeded "
                f"after {turn} turns for session {session_id}"
            )

        status = get_session_status(workspace_root, session_id)
        queries_run = status.get("queries_run", 0)
        candidates_captured = status.get("candidates_captured", 0)
        remaining = status.get("budget_used", {}).get("queries_remaining", max_queries)

        if turn == 0:
            prompt = _search_prompt_initial(
                session_id, profile_name, search_brief, max_queries, max_pages
            )
        else:
            prompt = _search_prompt_continue(session_id, queries_run, candidates_captured, remaining)

        turn += 1
        try:
            output = _openclaw_turn(prompt, repo_root)
            logger.info("Turn %d output: %.200s", turn, str(output))
        except subprocess.TimeoutExpired:
            logger.error(
                "Turn %d timed out after %ds — continuing to next turn",
                turn, AGENT_TURN_TIMEOUT_S,
            )
            continue
        except FileNotFoundError as exc:
            raise AgentRunError(
                f"'openclaw' binary not found — ensure it is on PATH: {exc}"
            ) from exc

        # Check if search phase is complete
        if _run_status(workspace_root, session_id) == "search_complete":
            search_complete = True
            logger.info("Search phase complete after %d turns", turn)
            break

        # Check if budget is exhausted
        if remaining <= 0:
            logger.info("Search budget exhausted after %d turns", turn)
            break

    # Re-read final status after loop exits
    final_status = get_session_status(workspace_root, session_id)
    queries_run = final_status.get("queries_run", 0)
    candidates_captured = final_status.get("candidates_captured", 0)

    # 3. Provenance validation — hard gate before pipeline
    if queries_run == 0:
        raise SearchValidationError(
            f"Agent produced 0 queries in {turn} turns for session {session_id}. "
            f"Pipeline aborted — fabricated candidates would corrupt the catalog. "
            f"Fix: ensure agent executes real web_search before career_log_candidates."
        )

    if candidates_captured == 0:
        logger.warning(
            "Session %s: queries_run=%d but 0 candidates captured — "
            "pipeline will process an empty pool",
            session_id, queries_run,
        )

    # 4. Deterministic processing pipeline (Python direct — no subprocess)
    candidates_file = workspace_root / "runs" / session_id / "candidate_pool.jsonl"
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

    # 5. Reflect turn — agent writes strategy patch (best-effort, non-blocking)
    try:
        _openclaw_turn(_reflect_prompt(session_id), repo_root)
        logger.info("Reflect turn complete for session %s", session_id)
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as exc:
        logger.warning("Reflect turn failed (non-fatal): %s", exc)

    return {
        "session_id": session_id,
        "run_id": session_id,
        "turns_used": turn,
        "search_complete": search_complete,
        "queries_run": queries_run,
        "candidates_captured": candidates_captured,
        "jobs_fetched": pipeline_result.get("jobs_fetched", 0),
        "jobs_structured": pipeline_result.get("jobs_structured", 0),
        "jobs_saved": pipeline_result.get("jobs_saved", 0),
        "jobs_failed": pipeline_result.get("jobs_failed", 0),
        "duration_seconds": pipeline_result.get("duration_seconds", 0),
    }
