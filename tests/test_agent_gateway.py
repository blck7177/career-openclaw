"""Tests for the generic agent gateway (subprocess-free)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from career_intelligence.services import agent_gateway
from career_intelligence.services.agent_gateway import AgentInvocation


def test_extract_tool_calls_nested():
    output = {
        "steps": [
            {"tool": "web_search", "args": {"query": "flex risk"}},
            {"name": "WebFetch", "url": "https://flex.com/x"},
            {"unrelated": True},
        ]
    }
    calls = agent_gateway._extract_tool_calls(output)
    tools = {c["tool"] for c in calls}
    assert "web_search" in tools
    assert "web_fetch" in tools
    assert any(c.get("url") == "https://flex.com/x" for c in calls)


def test_invoke_writes_input_spec_and_detects_outputs(tmp_path: Path):
    out_file = tmp_path / "out.json"
    spec_path = tmp_path / "spec.json"
    log_path = tmp_path / "log.json"

    def _fake_turn(agent_id, message, repo_root, timeout_s):  # noqa: ARG001
        out_file.write_text("done", encoding="utf-8")
        return {"tool": "web_fetch", "url": "https://flex.com/x"}

    inv = AgentInvocation(
        agent_id="career-research",
        prompt="do it",
        repo_root=tmp_path,
        expected_outputs=[out_file],
        input_spec={"k": "v"},
        input_spec_path=spec_path,
        run_log_path=log_path,
        max_turns=2,
    )

    with patch.object(agent_gateway, "_run_agent_turn", _fake_turn):
        result = agent_gateway.invoke(inv)

    assert result.status == "complete"
    assert result.web_fetch_count == 1
    assert result.fetch_urls == ["https://flex.com/x"]
    assert json.loads(spec_path.read_text()) == {"k": "v"}
    assert log_path.exists()


def test_invoke_incomplete_when_outputs_missing(tmp_path: Path):
    missing = tmp_path / "never.json"

    def _fake_turn(agent_id, message, repo_root, timeout_s):  # noqa: ARG001
        return {"raw_output": "nothing written"}

    inv = AgentInvocation(
        agent_id="career-research",
        prompt="do it",
        repo_root=tmp_path,
        expected_outputs=[missing],
        max_turns=1,
    )
    with patch.object(agent_gateway, "_run_agent_turn", _fake_turn):
        result = agent_gateway.invoke(inv)

    assert result.status == "incomplete"
    assert missing in result.outputs_missing


def test_invoke_per_turn_timeout_continues_then_completes(tmp_path: Path):
    """A per-turn TimeoutExpired must not abort the run — the loop retries."""
    out_file = tmp_path / "out.json"
    calls = {"n": 0}

    def _fake_turn(agent_id, message, repo_root, timeout_s):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd="openclaw", timeout=timeout_s)
        out_file.write_text("done", encoding="utf-8")
        return {"tool": "web_fetch", "url": "https://flex.com/x"}

    inv = AgentInvocation(
        agent_id="career-research",
        prompt="do it",
        repo_root=tmp_path,
        expected_outputs=[out_file],
        max_turns=2,
    )
    with patch.object(agent_gateway, "_run_agent_turn", _fake_turn):
        result = agent_gateway.invoke(inv)

    assert calls["n"] == 2
    assert result.status == "complete"
    assert result.turns_used == 2


def test_invoke_wall_clock_returns_timeout_without_running(tmp_path: Path):
    """Exceeding the wall-clock budget yields a timeout status (degrade, no raise)."""
    out_file = tmp_path / "out.json"
    calls = {"n": 0}

    def _fake_turn(agent_id, message, repo_root, timeout_s):  # noqa: ARG001
        calls["n"] += 1
        return {}

    inv = AgentInvocation(
        agent_id="career-research",
        prompt="do it",
        repo_root=tmp_path,
        expected_outputs=[out_file],
        max_turns=3,
        wall_clock_s=-1,
    )
    with patch.object(agent_gateway, "_run_agent_turn", _fake_turn):
        result = agent_gateway.invoke(inv)

    assert result.status == "timeout"
    assert calls["n"] == 0
    assert out_file in result.outputs_missing
