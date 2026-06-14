"""
Worker — polls the SQLite task_queue and dispatches tasks by type.

Usage:
    python -m apps.worker.worker

Dual-lane operation (fast lane + agent lane):
    Set WORKER_TASK_TYPES to a comma-separated list of task types this worker
    instance should handle.  Leave unset to handle all types (single-worker /
    backward-compatible).

    Fast lane  (job_report, fit_report):
        WORKER_TASK_TYPES=job_report,fit_report python -m apps.worker.worker

    Agent lane (search_run — long-running, isolated from fast tasks):
        WORKER_TASK_TYPES=search_run python -m apps.worker.worker

Design:
    - Single process, single thread per instance.
    - On startup, resets any 'running' tasks (for this lane) to 'pending'.
    - Dispatches to type-specific handlers; unknown types are failed immediately.
    - Any unhandled exception from a handler is caught and written to error_message.
    - Sleeps POLL_INTERVAL_S seconds when the queue is empty.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import get_data_root
from career_intelligence.services import task_service

from apps.worker.handlers.fit_report import handle_fit_report
from apps.worker.handlers.job_report import handle_job_report
from apps.worker.handlers.search_run import handle_search_run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 5

# Max number of times a task may be *started* (claimed), not handler-level
# retries. Bounds crash-mid-run re-execution so a poison task that repeatedly
# kills the worker cannot loop forever. Overridable via env.
MAX_ATTEMPTS = int(os.environ.get("TASK_MAX_ATTEMPTS", "3"))

# Optional lane filter: comma-separated list of task_type values this worker
# will claim.  Empty / unset = claim any task type (single-worker default).
# Example: WORKER_TASK_TYPES=search_run  → agent lane
#          WORKER_TASK_TYPES=job_report,fit_report → fast lane
_WORKER_TASK_TYPES_RAW = os.environ.get("WORKER_TASK_TYPES", "").strip()
WORKER_TASK_TYPES: list[str] | None = (
    [t.strip() for t in _WORKER_TASK_TYPES_RAW.split(",") if t.strip()]
    if _WORKER_TASK_TYPES_RAW
    else None
)

HANDLERS = {
    "job_report": handle_job_report,
    "fit_report": handle_fit_report,
    "search_run": handle_search_run,
}


# ---------------------------------------------------------------------------
# Startup recovery
# ---------------------------------------------------------------------------


def _recover_stale_tasks(store: MetadataStore) -> int:
    """
    Recover tasks left stuck in 'running' by a crashed/killed worker.

    SEMANTICS: `attempts` counts task *starts* (incremented on claim), not
    handler-level retries. A task whose handler raises is terminally failed by
    the main loop (except -> complete_task(error=...) -> 'failed') and never
    reaches this function. This recovery ONLY bounds crash-mid-run
    re-execution — i.e. the worker died (OOM / kill / crash) while a task was
    in-flight, leaving it stuck at 'running'.

    When WORKER_TASK_TYPES is set, only tasks belonging to this lane are
    recovered — preventing a fast-lane restart from incorrectly requeuing a
    long-running search_run that the agent lane is legitimately executing.

    On startup:
      - running tasks at/over MAX_ATTEMPTS  -> 'failed' (poison-task guard)
      - running tasks under MAX_ATTEMPTS    -> 'pending' (started_at cleared)

    Returns the number of tasks requeued to 'pending'.
    """
    now = datetime.now(timezone.utc).isoformat()

    lane_clause = ""
    lane_params: list[Any] = []
    if WORKER_TASK_TYPES:
        placeholders = ",".join("?" * len(WORKER_TASK_TYPES))
        lane_clause = f" AND task_type IN ({placeholders})"
        lane_params = list(WORKER_TASK_TYPES)

    with store._conn() as conn:
        failed = conn.execute(
            f"UPDATE task_queue SET status = 'failed', finished_at = ?, "
            f"error_message = 'exceeded max attempts' "
            f"WHERE status = 'running' AND attempts >= ?{lane_clause}",
            [now, MAX_ATTEMPTS, *lane_params],
        ).rowcount
        requeued = conn.execute(
            f"UPDATE task_queue SET status = 'pending', started_at = NULL "
            f"WHERE status = 'running' AND attempts < ?{lane_clause}",
            [MAX_ATTEMPTS, *lane_params],
        ).rowcount
    if failed:
        logger.error(
            "Failed %d 'running' task(s) over max attempts (%d)", failed, MAX_ATTEMPTS
        )
    if requeued:
        logger.warning("Recovered %d stale 'running' task(s) → 'pending'", requeued)
    return requeued


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

    lane_label = ",".join(WORKER_TASK_TYPES) if WORKER_TASK_TYPES else "all"
    logger.info("Worker starting (data_root=%s, lane=%s)", data_root, lane_label)
    _recover_stale_tasks(store)
    logger.info("Worker ready — polling every %ds", POLL_INTERVAL_S)

    while True:
        task = task_service.poll_pending_tasks(task_types=WORKER_TASK_TYPES)
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
