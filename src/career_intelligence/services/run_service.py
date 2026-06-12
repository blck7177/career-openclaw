"""
RunService — workspace-scoped run directory queries.

Runs live in data/workspaces/<workspace_id>/runs/<run_id>/.
Each run directory contains:
  run_config.yaml     — search parameters, final_stats, status (always present)
  run_summary.json    — structured summary produced by summarize_run tool
  run_summary.md      — narrative markdown summary (may be absent for old runs)

All functions take RequestContext as first argument.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.workspace_paths import get_workspace_paths


def list_runs(
    ctx: RequestContext,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Return run metadata for the workspace, sorted newest-first.

    Each item contains a merged view of run_config.yaml fields plus
    summary counts from run_summary.json (if present).
    """
    paths = get_workspace_paths(ctx.workspace_id)
    runs_root = paths.runs_root

    if not runs_root.exists():
        return []

    run_dirs = sorted(
        [d for d in runs_root.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )

    results: list[dict[str, Any]] = []
    for run_dir in run_dirs[:limit]:
        meta = _read_run_meta(run_dir)
        if meta:
            results.append(meta)

    return results


def get_run(ctx: RequestContext, run_id: str) -> dict[str, Any] | None:
    """
    Return full metadata for a single run, or None if not found.

    Merges run_config.yaml and run_summary.json into one dict.
    Adds a "has_summary_md" boolean indicating whether run_summary.md exists.
    """
    paths = get_workspace_paths(ctx.workspace_id)
    run_dir = paths.run_dir(run_id)

    if not run_dir.exists():
        return None

    meta = _read_run_meta(run_dir)
    if meta is None:
        return None

    # Include the full run_summary.json if present
    summary_json_path = run_dir / "run_summary.json"
    if summary_json_path.exists():
        try:
            with open(summary_json_path, encoding="utf-8") as f:
                meta["summary"] = json.load(f)
        except (OSError, json.JSONDecodeError):
            meta["summary"] = None
    else:
        meta["summary"] = None

    meta["has_summary_md"] = (run_dir / "run_summary.md").exists()
    return meta


def get_run_summary(ctx: RequestContext, run_id: str) -> str | None:
    """
    Return the raw markdown content of run_summary.md, or None if absent.
    """
    paths = get_workspace_paths(ctx.workspace_id)
    summary_path = paths.run_dir(run_id) / "run_summary.md"

    if not summary_path.exists():
        return None

    try:
        return summary_path.read_text(encoding="utf-8")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_run_meta(run_dir: Path) -> dict[str, Any] | None:
    """Read lightweight run metadata from run_config.yaml."""
    config_path = run_dir / "run_config.yaml"
    if not config_path.exists():
        return None

    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return None

    run_id = run_dir.name
    meta: dict[str, Any] = {
        "run_id": run_id,
        "profile_name": config.get("profile_name"),
        "mode": config.get("mode"),
        "status": config.get("status"),
        "run_timestamp": config.get("run_timestamp"),
        "search_completed_at": config.get("search_completed_at"),
    }

    # Include final_stats inline for list views
    final_stats = config.get("final_stats") or {}
    meta["candidates_captured"] = final_stats.get("candidates_captured")

    return meta
