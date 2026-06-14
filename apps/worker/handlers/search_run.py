"""Worker handler for search_run tasks.

Invoked by the agent-lane worker when a search_run task is claimed.
Drives a full OpenClaw discovery session (search → process → reflect)
against the shared catalog workspace.

Expected task payload:
    profile_name  str   Search profile name from configs/search_profiles.yaml
    search_brief  str   Free-text objective for the agent
    mode          str   "exploratory" | "refresh"  (optional, default exploratory)
    max_queries   int   Hard query budget            (optional, default 30)
    max_pages     int   Hard fetch-page budget       (optional, default 40)
"""

from __future__ import annotations

import logging
from typing import Any

from career_intelligence.services import task_service
from career_intelligence.services.agent_service import (
    AgentRunError,
    SearchValidationError,
    run_discovery_session,
)

logger = logging.getLogger(__name__)


def handle_search_run(task: dict[str, Any]) -> None:
    """Claim and execute a search_run task end-to-end."""
    task_id = task["task_id"]
    payload = task.get("payload", {})

    profile_name: str = payload.get("profile_name", "")
    search_brief: str = payload.get("search_brief", "")

    if not profile_name:
        task_service.complete_task(task_id, error="Missing required payload field: profile_name")
        return
    if not search_brief:
        task_service.complete_task(task_id, error="Missing required payload field: search_brief")
        return

    logger.info(
        "search_run task %s: profile=%s brief=%.80s", task_id, profile_name, search_brief
    )

    try:
        result = run_discovery_session(
            profile_name=profile_name,
            search_brief=search_brief,
            mode=payload.get("mode", "exploratory"),
            max_queries=int(payload.get("max_queries", 30)),
            max_pages=int(payload.get("max_pages", 40)),
        )
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
        task_service.complete_task(task_id, error=f"SearchValidationError: {exc}")

    except AgentRunError as exc:
        logger.error("search_run task %s agent error: %s", task_id, exc)
        task_service.complete_task(task_id, error=f"AgentRunError: {exc}")
