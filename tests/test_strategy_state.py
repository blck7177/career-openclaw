"""Tests for the deterministic strategy-patch applier (Phase 3 reflect)."""

from __future__ import annotations

from pathlib import Path

import pytest

from career_intelligence.strategy_state import (
    StrategyPatchError,
    apply_strategy_patch,
    read_state,
)


def test_apply_valid_patch_merges_and_increments(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()

    state = apply_strategy_patch(
        ws, "run1",
        {"key_learnings": ["a"], "coverage_by_workstream": {"Market Risk": "weak"}},
    )
    assert state["runs_completed"] == 1
    assert state["last_run_id"] == "run1"
    assert state["key_learnings"] == ["a"]
    assert state["coverage_by_workstream"]["Market Risk"] == "weak"

    # Second patch: list fields union-merge, runs_completed increments.
    state2 = apply_strategy_patch(ws, "run2", {"key_learnings": ["a", "b"]})
    assert state2["key_learnings"] == ["a", "b"]
    assert state2["runs_completed"] == 2
    assert state2["last_run_id"] == "run2"


def test_recommended_next_searches_is_replaced(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    apply_strategy_patch(ws, "run1", {"recommended_next_searches": ["x", "y"]})
    state = apply_strategy_patch(ws, "run2", {"recommended_next_searches": ["z"]})
    assert state["recommended_next_searches"] == ["z"]


def test_empty_patch_is_valid(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    state = apply_strategy_patch(ws, "run1", {})
    assert state["runs_completed"] == 1


def test_unknown_field_raises(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(StrategyPatchError):
        apply_strategy_patch(ws, "run1", {"not_a_field": 1})
    # Rejected patch must not have written state.
    assert not (ws / "strategy_state.json").exists()


def test_non_dict_patch_raises(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(StrategyPatchError):
        apply_strategy_patch(ws, "run1", ["nope"])  # type: ignore[arg-type]


def test_read_state_defaults_when_missing(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    state = read_state(ws)
    assert state["runs_completed"] == 0
    assert state["effective_sources"] == []
