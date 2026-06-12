"""
Worker — polls the SQLite task_queue and dispatches tasks by type.

Usage:
    python -m apps.worker.worker

Design:
    - Single process, single thread — task_queue is designed for one worker.
    - On startup, resets any 'running' tasks to 'pending' (crash recovery).
    - Dispatches to type-specific handlers; unknown types are failed immediately.
    - Any unhandled exception from a handler is caught and written to error_message.
    - Sleeps POLL_INTERVAL_S seconds when the queue is empty.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import get_data_root
from career_intelligence.services import task_service

from apps.worker.handlers.fit_report import handle_fit_report
from apps.worker.handlers.job_report import handle_job_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 5

HANDLERS = {
    "job_report": handle_job_report,
    "fit_report": handle_fit_report,
}


# ---------------------------------------------------------------------------
# Startup recovery
# ---------------------------------------------------------------------------


def _recover_stale_tasks(store: MetadataStore) -> int:
    """
    Reset any tasks stuck in 'running' state to 'pending'.

    This handles the case where the worker process was killed while a task
    was in-flight.  On restart, those tasks become eligible for re-execution.

    Returns the number of tasks reset.
    """
    with store._conn() as conn:
        cursor = conn.execute(
            "UPDATE task_queue SET status = 'pending', started_at = NULL "
            "WHERE status = 'running'"
        )
        count = cursor.rowcount
    if count:
        logger.warning("Recovered %d stale 'running' task(s) → 'pending'", count)
    return count


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _dispatch(task: dict[str, Any]) -> None:
    """
    Route a claimed task to the appropriate handler.

    Unknown task types are immediately failed (rather than crashing the worker).
    Handler exceptions bubble up to the caller, which writes them to error_message.
    """
    task_type = task.get("task_type", "")
    handler = HANDLERS.get(task_type)

    if handler is None:
        task_service.complete_task(
            task["task_id"],
            error=f"Unknown task_type: {task_type!r}",
        )
        logger.error("Unknown task_type %r — task %s failed", task_type, task["task_id"])
        return

    logger.info("Starting task %s (type=%s)", task["task_id"], task_type)
    handler(task)
    logger.info("Completed task %s", task["task_id"])


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> None:
    data_root = get_data_root()
    store = MetadataStore.from_data_root(data_root)
    store.init_schema()

    logger.info("Worker starting (data_root=%s)", data_root)
    _recover_stale_tasks(store)
    logger.info("Worker ready — polling every %ds", POLL_INTERVAL_S)

    while True:
        task = task_service.poll_pending_tasks()
        if task is None:
            time.sleep(POLL_INTERVAL_S)
            continue

        try:
            _dispatch(task)
        except Exception as exc:
            logger.exception("Task %s failed: %s", task["task_id"], exc)
            try:
                task_service.complete_task(task["task_id"], error=str(exc))
            except Exception:
                logger.exception("Failed to mark task %s as failed", task["task_id"])


if __name__ == "__main__":
    main()
