"""Tests for run_discovery_session after the Phase 2 gateway migration.

The bounded career-search-agent is mocked at the agent_gateway boundary; the
real search_session file ops run against a tmp workspace so we exercise the
worker-owned session finalization (end_session) and the provenance gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from career_intelligence.services import agent_service
from career_intelligence.services.agent_service import (
    AgentRunError,
    SearchValidationError,
    run_discovery_session,
)
from career_intelligence.services.agent_gateway import (
    AgentGatewayError,
    AgentRunResult,
)


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _fake_invoke_factory(*, write_ledger=True, write_candidate=True,
                         write_coverage=True, tool_calls=None, status="complete"):
    def _fake_invoke(inv) -> AgentRunResult:
        coverage = inv.expected_outputs[0]
        session_root = coverage.parent
        if write_ledger:
            _append_jsonl(session_root / "search_ledger.jsonl",
                          {"query_id": "q_001", "query_text": "risk eng", "results_seen": []})
        if write_candidate:
            _append_jsonl(session_root / "candidate_pool.jsonl",
                          {"candidate_id": "cand_001", "url": "https://flex.com/jobs/1",
                           "url_hash": "abc", "relevance": "relevant"})
        if write_coverage:
            coverage.write_text("# Coverage\nlooked at flex", encoding="utf-8")
        return AgentRunResult(
            status=status,
            turns_used=1,
            outputs_present=[p for p in inv.expected_outputs if p.exists()],
            outputs_missing=[p for p in inv.expected_outputs if not p.exists()],
            tool_calls=tool_calls if tool_calls is not None else [
                {"tool": "web_search", "url": "risk eng"},
                {"tool": "web_fetch", "url": "https://flex.com/jobs/1"},
            ],
            raw_outputs=[],
            raw_log_path=None,
        )
    return _fake_invoke


@pytest.fixture()
def workspace_root(tmp_path: Path) -> Path:
    return tmp_path / "ws"


def _patches(workspace_root: Path, fake_invoke, pipeline_result=None):
    paths = SimpleNamespace(root=workspace_root)
    return [
        patch("career_intelligence.services.agent_service.get_catalog_workspace_id",
              return_value="dev"),
        patch("career_intelligence.services.agent_service.get_workspace_paths",
              return_value=paths),
        patch("career_intelligence.services.agent_service.get_repo_root",
              return_value=workspace_root),
        patch.object(agent_service.agent_gateway, "invoke", fake_invoke),
        patch("career_intelligence.services.agent_service.run_processing_pipeline",
              return_value=pipeline_result or {"jobs_fetched": 1, "jobs_saved": 1, "jobs_failed": 0}),
        patch.object(agent_service, "_run_reflect",
                     return_value={"reflected": True, "patch_applied": False}),
    ]


def _run(patches_list):
    for p in patches_list:
        p.start()
    try:
        return run_discovery_session(profile_name="quant", search_brief="find risk roles")
    finally:
        for p in reversed(patches_list):
            p.stop()


def test_happy_path_finalizes_session_and_runs_pipeline(workspace_root: Path):
    result = _run(_patches(workspace_root, _fake_invoke_factory()))

    assert result["search_complete"] is True
    assert result["queries_run"] == 1
    assert result["candidates_captured"] == 1
    assert result["jobs_saved"] == 1

    # Worker finalized the session (agent did not call end).
    session_id = result["session_id"]
    rc = yaml.safe_load((workspace_root / "runs" / session_id / "run_config.yaml").read_text())
    assert rc["status"] == "search_complete"
    # Coverage was copied into the session dir by end_session.
    assert (workspace_root / "runs" / session_id / "coverage_report.md").exists()


def test_fabrication_raises_when_no_search_and_no_queries(workspace_root: Path):
    fake = _fake_invoke_factory(write_ledger=False, write_candidate=False,
                                write_coverage=False, tool_calls=[], status="incomplete")
    with pytest.raises(SearchValidationError):
        _run(_patches(workspace_root, fake))


def test_stub_coverage_written_when_agent_skips_it(workspace_root: Path):
    """queries_run > 0 (via ledger) but no coverage → worker stubs + finalizes."""
    fake = _fake_invoke_factory(write_coverage=False, tool_calls=[], status="incomplete")
    result = _run(_patches(workspace_root, fake))

    session_id = result["session_id"]
    assert (workspace_root / "runs" / session_id / "coverage_draft.md").exists()
    rc = yaml.safe_load((workspace_root / "runs" / session_id / "run_config.yaml").read_text())
    assert rc["status"] == "search_complete"


def test_gateway_error_wrapped_as_agent_run_error(workspace_root: Path):
    def _boom(inv):
        raise AgentGatewayError("openclaw not found")

    with pytest.raises(AgentRunError):
        _run(_patches(workspace_root, _boom))


# ---------------------------------------------------------------------------
# Phase 3 bounded reflect: agent writes a patch; worker validates + applies it.
# ---------------------------------------------------------------------------


def _reflect_invoke_factory(patch_obj, *, write_report=True):
    def _fake_invoke(inv) -> AgentRunResult:
        patch_path, report_path = inv.expected_outputs
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        if patch_obj is not None:
            patch_path.write_text(json.dumps(patch_obj), encoding="utf-8")
        if write_report:
            report_path.write_text("# Reflection\nlearned things", encoding="utf-8")
        return AgentRunResult(
            status="complete",
            turns_used=1,
            outputs_present=[p for p in inv.expected_outputs if p.exists()],
            outputs_missing=[p for p in inv.expected_outputs if not p.exists()],
            tool_calls=[],
            raw_outputs=[],
            raw_log_path=None,
        )
    return _fake_invoke


def test_reflect_applies_valid_patch(workspace_root: Path, tmp_path: Path):
    session_root = tmp_path / "runs" / "s1"
    session_root.mkdir(parents=True)
    (session_root / "run_summary.md").write_text("summary", encoding="utf-8")
    patch_obj = {"key_learnings": ["greenhouse works"], "avoid_sources": ["citi.com — 404"]}

    with patch.object(agent_service.agent_gateway, "invoke",
                      _reflect_invoke_factory(patch_obj)):
        out = agent_service._run_reflect(
            session_id="s1", workspace_root=workspace_root,
            session_root=session_root, repo_root=workspace_root,
        )

    assert out["patch_applied"] is True
    state = json.loads((workspace_root / "strategy_state.json").read_text())
    assert "greenhouse works" in state["key_learnings"]
    assert state["last_run_id"] == "s1"
    assert state["runs_completed"] == 1


def test_reflect_rejects_unknown_field_without_writing_state(workspace_root: Path, tmp_path: Path):
    session_root = tmp_path / "runs" / "s2"
    session_root.mkdir(parents=True)

    with patch.object(agent_service.agent_gateway, "invoke",
                      _reflect_invoke_factory({"bogus_field": 1})):
        out = agent_service._run_reflect(
            session_id="s2", workspace_root=workspace_root,
            session_root=session_root, repo_root=workspace_root,
        )

    assert out["patch_applied"] is False
    assert not (workspace_root / "strategy_state.json").exists()


def test_reflect_no_patch_file_is_noop(workspace_root: Path, tmp_path: Path):
    session_root = tmp_path / "runs" / "s3"
    session_root.mkdir(parents=True)

    with patch.object(agent_service.agent_gateway, "invoke",
                      _reflect_invoke_factory(None, write_report=True)):
        out = agent_service._run_reflect(
            session_id="s3", workspace_root=workspace_root,
            session_root=session_root, repo_root=workspace_root,
        )

    assert out["patch_applied"] is False
    assert not (workspace_root / "strategy_state.json").exists()
