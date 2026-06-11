"""
Run Logger — generates run artifacts in runs/<session_id>/
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_step(run_dir: Path, step: str, job_id: str | None, status: str, detail: dict[str, Any] | None = None) -> None:
    _append_jsonl(run_dir / "run_log.jsonl", {
        "timestamp": _now_iso(),
        "step": step,
        "job_id": job_id,
        "status": status,
        **(detail or {}),
    })


def log_validation_error(run_dir: Path, job_id: str, errors: list[str]) -> None:
    _append_jsonl(run_dir / "validation_errors.jsonl", {
        "timestamp": _now_iso(),
        "job_id": job_id,
        "errors": errors,
    })


def write_jobs_structured(run_dir: Path, records: list[dict[str, Any]]) -> None:
    with open(run_dir / "jobs_structured.json", "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def _extract_fetch_failures(run_dir: Path) -> list[dict[str, Any]]:
    """Read run_log.jsonl and return deduplicated fetch_done failure events.

    URL is taken from the 'url' field when present (new logs), or parsed
    from the error string (legacy logs formatted as 'HTTP NNN: <url>').
    Deduplication is by URL to avoid counting retry attempts multiple times.
    """
    log_path = run_dir / "run_log.jsonl"
    if not log_path.exists():
        return []

    seen_urls: set[str] = set()
    failures: list[dict[str, Any]] = []

    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("step") != "fetch_done" or entry.get("status") != "failed":
                continue

            error = entry.get("error", "unknown error")
            url = entry.get("url", "")

            # Legacy log format: error = "HTTP NNN: <url>"
            if not url and ": http" in error:
                url = error.split(": ", 1)[1].strip()

            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Normalise error to just the status part (strip the URL from it)
            error_short = error.split(": http")[0] if ": http" in error else error

            failures.append({
                "job_id": entry.get("job_id", ""),
                "url": url,
                "error": error_short,
                "source_type": entry.get("source_type", "unknown"),
                "failure_stage": entry.get("failure_stage", ""),
                "error_type": entry.get("error_type", ""),
                "retryable": entry.get("retryable", True),
                "recommended_next_actions": entry.get("recommended_next_actions", []),
            })

    return failures


def _compute_source_performance(run_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """
    Read run_log.jsonl and compute per-source success/failure counts
    and aggregated recommended_next_actions.

    Returns:
        (source_performance dict, recommended_next_actions list)
    """
    log_path = run_dir / "run_log.jsonl"
    if not log_path.exists():
        return {}, []

    # source_type → {"success": int, "failed": int, "error_types": Counter-like dict}
    perf: dict[str, dict[str, Any]] = {}
    next_actions_seen: list[str] = []
    next_actions_set: set[str] = set()

    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("step") != "fetch_done":
                continue

            source_type = entry.get("source_type", "unknown")
            status = entry.get("status", "")
            error_type = entry.get("error_type", "")
            actions = entry.get("recommended_next_actions", [])

            if source_type not in perf:
                perf[source_type] = {"success": 0, "failed": 0, "error_types": {}}

            if status == "success":
                perf[source_type]["success"] += 1
            else:
                perf[source_type]["failed"] += 1
                if error_type:
                    et_counts = perf[source_type]["error_types"]
                    et_counts[error_type] = et_counts.get(error_type, 0) + 1

            for action in actions:
                if action not in next_actions_set:
                    next_actions_set.add(action)
                    next_actions_seen.append(action)

    # Derive main_failure for each source
    source_performance: dict[str, Any] = {}
    for src, data in perf.items():
        entry_out: dict[str, Any] = {
            "success": data["success"],
            "failed": data["failed"],
        }
        if data["error_types"]:
            main_failure = max(data["error_types"], key=lambda k: data["error_types"][k])
            entry_out["main_failure"] = main_failure
        source_performance[src] = entry_out

    return source_performance, next_actions_seen


def write_run_summary(
    run_dir: Path,
    run_id: str,
    profile_used: str,
    stats: dict[str, Any],
    top_workstreams: list[dict[str, Any]],
    duration_seconds: float,
) -> None:
    """Write both run_summary.json (machine) and run_summary.md (human)."""
    fetch_failures = _extract_fetch_failures(run_dir)
    source_performance, recommended_next_actions = _compute_source_performance(run_dir)

    summary = {
        "run_id": run_id,
        "session_id": run_id,
        "run_timestamp": _now_iso(),
        "profile_used": profile_used,
        "runner_version": "0.1.0",
        **stats,
        "top_workstreams": top_workstreams,
        "duration_seconds": round(duration_seconds, 1),
        "fetch_failures": fetch_failures,
        "source_performance": source_performance,
        "recommended_next_actions": recommended_next_actions,
    }

    with open(run_dir / "run_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    total = stats.get("jobs_discovered", 0)
    saved = stats.get("jobs_saved", 0)
    failed = stats.get("jobs_failed", 0)
    skipped = stats.get("jobs_skipped", 0)

    top_ws_lines = "\n".join(
        f"  - {ws['workstream']}: {ws['count']}" for ws in top_workstreams
    ) or "  (none)"

    if fetch_failures:
        failure_lines = "\n".join(
            f"  - `{f['job_id']}` [{f.get('source_type','?')}] {f['url']} → {f['error']}"
            + (f" (error_type: {f['error_type']})" if f.get("error_type") else "")
            for f in fetch_failures
        )
        fetch_failures_section = f"\n## Fetch Failures\n\n{failure_lines}\n"
    else:
        fetch_failures_section = ""

    if source_performance:
        perf_rows = "\n".join(
            f"| {src} | {data['success']} | {data['failed']} | {data.get('main_failure', '-')} |"
            for src, data in sorted(source_performance.items())
        )
        source_perf_section = (
            "\n## Source Performance\n\n"
            "| Source | Success | Failed | Main Failure |\n"
            "|--------|---------|--------|--------------|\n"
            f"{perf_rows}\n"
        )
    else:
        source_perf_section = ""

    if recommended_next_actions:
        action_lines = "\n".join(f"  - {a}" for a in recommended_next_actions)
        next_actions_section = f"\n## Recommended Next Actions\n\n{action_lines}\n"
    else:
        next_actions_section = ""

    md = f"""# Run Summary

**Run ID:** `{run_id}`
**Profile:** {profile_used}
**Timestamp:** {summary['run_timestamp']}
**Duration:** {duration_seconds:.1f}s

## Results

| Metric | Count |
|--------|-------|
| Jobs discovered (candidates) | {total} |
| Jobs fetched | {stats.get('jobs_fetched', 0)} |
| Jobs structured | {stats.get('jobs_structured', 0)} |
| Jobs saved to db | {saved} |
| Jobs failed | {failed} |
| Jobs skipped | {skipped} |

## Top Workstreams

{top_ws_lines}
{fetch_failures_section}{source_perf_section}{next_actions_section}
## Next Steps

- Review `runs/{run_id}/jobs_structured.json` for structured records
- Validate: `./wrappers/career_validate_run --run-id {run_id}`
- Query: `./wrappers/career_query_jobs --workstream "Market Risk"`
"""
    with open(run_dir / "run_summary.md", "w", encoding="utf-8") as f:
        f.write(md)
