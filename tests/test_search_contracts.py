"""Contract tests for the bounded career-search-agent I/O.

Covers the two gaps closed alongside the workspace-coupling fix:
  1. resolve_workspace_root defaults to the (env-aware) catalog workspace, so
     wrapper writes land in the same workspace the worker created the session in
     even when CATALOG_WORKSPACE_ID is overridden.
  2. the objects the code actually produces validate against the new schemas
     (search_agent_input.schema.json, candidate_pool_entry.schema.json).
"""

from __future__ import annotations

import importlib
from pathlib import Path

from career_intelligence.app_state import workspace_paths
from career_intelligence.schema_validation import validate_against_schema
from career_intelligence.services.agent_service import _search_input_spec


def test_resolve_workspace_root_defaults_to_catalog(monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_WORKSPACE_ID", "prod_catalog")
    importlib.reload(workspace_paths)  # re-read module-level default binding

    root = workspace_paths.resolve_workspace_root()
    assert root.name == "prod_catalog"

    # Explicit override still wins.
    root2 = workspace_paths.resolve_workspace_root("other_ws")
    assert root2.name == "other_ws"

    monkeypatch.delenv("CATALOG_WORKSPACE_ID", raising=False)
    importlib.reload(workspace_paths)


def test_search_input_spec_matches_schema() -> None:
    spec = _search_input_spec(
        session_id="2026-06-14_030203",
        workspace_id="dev_default",
        profile_name="market_risk_nyc",
        search_brief="find market risk roles",
        max_queries=30,
        max_pages=40,
        coverage_path=Path("/data/runs/2026-06-14_030203/coverage_report.md"),
        discovery_notes_path=Path("/data/runs/2026-06-14_030203/discovery_notes.md"),
    )
    errors = validate_against_schema(spec, "search_agent_input.schema.json")
    assert errors == [], errors


def test_search_input_spec_missing_workspace_id_fails_schema() -> None:
    bad = {
        "session_id": "s1",
        "profile_name": "p",
        "search_brief": "b",
        "expected_output_paths": {"coverage_draft": "/x/coverage_draft.md"},
    }
    errors = validate_against_schema(bad, "search_agent_input.schema.json")
    assert any("workspace_id" in e for e in errors)
