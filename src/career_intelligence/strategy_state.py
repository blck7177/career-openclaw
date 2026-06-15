"""
Cross-run strategy state — persists search learnings across runs.

Stored at db/strategy_state.json.
Updated by the agent at the end of each run via career_update_strategy.
Read by the agent at the start of each run via career_read_strategy.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STRATEGY_STATE_VERSION = "1.0.0"

# The only fields a reflect patch may contain. Shared by the deterministic
# applier (apply_strategy_patch) and the career_update_strategy CLI so the two
# never drift. Anything outside this set is rejected.
PATCH_FIELDS = frozenset(
    {
        "effective_sources",
        "avoid_sources",
        "effective_query_patterns",
        "avoid_query_patterns",
        "coverage_by_workstream",
        "key_learnings",
        "recommended_next_searches",
    }
)


class StrategyPatchError(ValueError):
    """Raised when a reflect strategy patch is malformed or has unknown fields."""

_DEFAULT_STATE: dict[str, Any] = {
    "version": STRATEGY_STATE_VERSION,
    "last_updated": None,
    "last_run_id": None,
    "runs_completed": 0,

    # Sources confirmed to return real JD pages
    "effective_sources": [],

    # Sources to avoid (403, high 404 rate, aggregator-only, etc.)
    "avoid_sources": [],

    # Query patterns that produced valid job posting URLs
    "effective_query_patterns": [],

    # Query patterns that consistently failed (search result pages, irrelevant, etc.)
    "avoid_query_patterns": [],

    # Per-workstream coverage assessment
    # Values: "sufficient" | "weak" | "missing" | "unknown"
    "coverage_by_workstream": {},

    # Key learnings accumulated across runs (agent-written strings)
    "key_learnings": [],

    # Where to focus next run (agent-written)
    "recommended_next_searches": [],
}


def _state_path(workspace_root: Path) -> Path:
    # strategy_state.json lives at the workspace root (not under db/).
    # workspace_root = data/workspaces/<workspace_id>/
    return workspace_root / "strategy_state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_state(workspace_root: Path) -> dict[str, Any]:
    """
    Read the current cross-run strategy state.
    Returns default state if the file doesn't exist yet.
    """
    path = _state_path(workspace_root)
    if not path.exists():
        return dict(_DEFAULT_STATE)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # Forward-compat: fill any missing keys from defaults
    for key, default_val in _DEFAULT_STATE.items():
        if key not in data:
            data[key] = default_val
    return data


def update_state(
    workspace_root: Path,
    run_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """
    Merge a patch dict into the current strategy state and persist.

    List fields (effective_sources, avoid_sources, etc.) are merged
    (union, deduped) rather than replaced, so learnings accumulate.
    Scalar fields (coverage_by_workstream keys, recommended_next_searches)
    are replaced by the patch value.

    Returns the updated state.
    """
    state = read_state(workspace_root)

    list_union_fields = {
        "effective_sources",
        "avoid_sources",
        "effective_query_patterns",
        "avoid_query_patterns",
        "key_learnings",
    }

    for key, value in patch.items():
        if key in list_union_fields and isinstance(value, list):
            existing = state.get(key, [])
            merged = list(dict.fromkeys(existing + value))  # preserve order, dedup
            state[key] = merged
        elif key == "coverage_by_workstream" and isinstance(value, dict):
            state["coverage_by_workstream"].update(value)
        elif key == "recommended_next_searches" and isinstance(value, list):
            state["recommended_next_searches"] = value  # replace, not merge
        elif key not in ("version", "last_updated", "last_run_id", "runs_completed"):
            state[key] = value

    state["last_updated"] = _now_iso()
    state["last_run_id"] = run_id
    state["runs_completed"] = state.get("runs_completed", 0) + 1

    path = _state_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    return state


def apply_strategy_patch(
    workspace_root: Path,
    run_id: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate a reflect-produced strategy patch, then merge it into the state.

    This is the deterministic, worker-owned applier for the bounded
    career-reflect-agent: the agent only writes strategy_patch.json; the
    platform validates the shape here and is the sole writer of
    strategy_state.json (Agent owns bounded action, Service owns persistence).

    Raises:
        StrategyPatchError — patch is not an object or contains unknown fields.
    """
    if not isinstance(patch, dict):
        raise StrategyPatchError("strategy patch must be a JSON object")
    unknown = set(patch.keys()) - set(PATCH_FIELDS)
    if unknown:
        raise StrategyPatchError(f"unknown patch fields: {sorted(unknown)}")
    return update_state(workspace_root, run_id, patch)
