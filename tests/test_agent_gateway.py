"""Tests for the generic agent gateway (subprocess-free)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from career_intelligence.services import agent_gateway
from career_intelligence.services.agent_gateway import AgentInvocation


def _msg(role: str, *content: dict) -> dict:
    return {"type": "message", "message": {"role": role, "content": list(content)}}


def _user(text: str) -> dict:
    return _msg("user", {"type": "text", "text": text})


def _toolcall(name: str, **arguments) -> dict:
    return {"type": "toolCall", "name": name, "arguments": arguments}


def _write_session(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def _polluted_meta(session_file: Path) -> dict:
    """An output meta that carries the static tool *schema* catalogue (the bug
    source) plus the real sessionFile pointer."""
    return {
        "agentMeta": {"sessionFile": str(session_file)},
        "systemPromptReport": {
            "tools": {
                "entries": [
                    {"name": "read", "schemaChars": 120},
                    {"name": "web_search", "schemaChars": 991, "propertiesCount": 2},
                    {"name": "web_fetch", "schemaChars": 317, "propertiesCount": 1},
                ]
            }
        },
    }


def test_tool_schema_entry_is_not_a_call():
    """A tool *schema* descriptor (no type:toolCall, no arguments) must never
    be mistaken for a real call."""
    assert agent_gateway._tool_call_from_content_item(
        {"name": "web_search", "schemaChars": 991}
    ) is None
    assert agent_gateway._tool_call_from_content_item(
        {"type": "toolCall", "name": "web_fetch", "arguments": {"url": "https://x.com/j"}}
    ) == {"tool": "web_fetch", "url": "https://x.com/j"}


def test_extract_tool_calls_from_session_scopes_to_last_turn(tmp_path: Path):
    """--local appends to a persistent session; only the most recent turn (after
    the last user message) must be counted, not stale history."""
    session = tmp_path / "session.jsonl"
    _write_session(session, [
        {"type": "session", "id": "s1"},
        _user("OLD turn from a previous run"),
        _msg("assistant", _toolcall("web_fetch", url="https://old.com/stale")),
        _user("NEW turn we just sent"),
        _msg("assistant", _toolcall("web_search", query="flex risk")),
        {"type": "message", "message": {"role": "toolResult", "toolName": "web_search"}},
        _msg("assistant", _toolcall("web_fetch", url="https://new.com/job")),
    ])

    calls = agent_gateway._extract_tool_calls_from_session(session)

    assert calls == [
        {"tool": "web_search", "url": "flex risk"},
        {"tool": "web_fetch", "url": "https://new.com/job"},
    ]
    assert all("old.com" not in (c.get("url") or "") for c in calls)


def test_extract_tool_calls_from_session_missing_file(tmp_path: Path):
    assert agent_gateway._extract_tool_calls_from_session(tmp_path / "nope.jsonl") == []


def test_invoke_uses_session_and_ignores_schema_pollution(tmp_path: Path):
    """Regression: the web_search/web_fetch entries in meta.systemPromptReport
    are a schema catalogue, not calls. invoke must read the session jsonl and
    report only the real toolCall there."""
    out_file = tmp_path / "out.json"
    spec_path = tmp_path / "spec.json"
    log_path = tmp_path / "log.json"
    session = tmp_path / "session.jsonl"

    def _fake_turn(agent_id, message, repo_root, timeout_s):  # noqa: ARG001
        _write_session(session, [
            _user("do it"),
            _msg("assistant", _toolcall("web_fetch", url="https://flex.com/x")),
        ])
        out_file.write_text("done", encoding="utf-8")
        return {"payloads": [{"text": "ok"}], "meta": _polluted_meta(session)}

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
    # exactly the one real fetch — schema catalogue entries are ignored
    assert result.web_fetch_count == 1
    assert result.fetch_urls == ["https://flex.com/x"]
    assert sum(1 for tc in result.tool_calls if tc.get("tool") == "web_search") == 0
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
