"""
Agent Gateway — generic bounded-agent invocation for the worker.

Wraps the OpenClaw subprocess interface so worker-side services can invoke any
bounded agent (career-search-agent, career-research, career-reflect-agent)
through a single contract:

    worker writes an input_spec → invoke() drives the agent turn(s) → returns an
    AgentRunResult describing which expected outputs landed on disk, the tool
    calls parsed from the agent run log (fabrication ground-truth), the raw log
    path, turns used, and a coarse status.

The gateway is business-agnostic: it does NOT know about search sessions,
candidate pools, research bundles, or any validation rules. Callers own the
workflow, validation, and persistence. This is the "Worker owns workflow,
Agent owns bounded action" boundary, expressed as code.

See protocols/AGENT_IO_CONTRACT.md for the file-based I/O contract.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Reliability defaults (shared with agent_service via the same env vars).
AGENT_TURN_TIMEOUT_S = int(os.environ.get("AGENT_TURN_TIMEOUT_S", "180"))
AGENT_RUN_WALL_CLOCK_S = int(os.environ.get("AGENT_RUN_WALL_CLOCK_S", "3600"))

# Tool names we treat as "real external actions" when parsing the run log.
_WEB_TOOL_ALIASES = {
    "web_fetch": "web_fetch",
    "webfetch": "web_fetch",
    "fetch": "web_fetch",
    "web_search": "web_search",
    "websearch": "web_search",
    "search": "web_search",
}


class AgentGatewayError(Exception):
    """Unrecoverable gateway failure (e.g. openclaw binary missing)."""


@dataclass
class AgentInvocation:
    """One bounded agent invocation request."""

    agent_id: str
    prompt: str
    repo_root: Path
    expected_outputs: list[Path] = field(default_factory=list)
    input_spec: dict[str, Any] | None = None
    input_spec_path: Path | None = None
    run_log_path: Path | None = None
    turn_timeout_s: int = AGENT_TURN_TIMEOUT_S
    max_turns: int = 1
    wall_clock_s: int = AGENT_RUN_WALL_CLOCK_S


@dataclass
class AgentRunResult:
    """Outcome of an agent invocation. Business-agnostic; callers validate."""

    status: str  # "complete" | "incomplete" | "timeout"
    turns_used: int
    outputs_present: list[Path]
    outputs_missing: list[Path]
    tool_calls: list[dict[str, Any]]  # parsed web_fetch/web_search — ground truth
    raw_outputs: list[dict[str, Any]]
    raw_log_path: Path | None = None

    @property
    def fetch_urls(self) -> list[str]:
        """URLs from real web_fetch tool calls (fabrication ground-truth)."""
        return [
            tc["url"]
            for tc in self.tool_calls
            if tc.get("tool") == "web_fetch" and tc.get("url")
        ]

    @property
    def web_fetch_count(self) -> int:
        return sum(1 for tc in self.tool_calls if tc.get("tool") == "web_fetch")


def _run_agent_turn(
    agent_id: str,
    message: str,
    repo_root: Path,
    timeout_s: int,
) -> dict[str, Any]:
    """
    Send one message to an OpenClaw agent, return parsed JSON output.

    Raises subprocess.TimeoutExpired if the agent exceeds timeout_s.
    On non-zero exit or unparseable JSON, returns a dict with raw_output/exit_code.
    """
    cmd = [
        "openclaw", "agent",
        "--agent", agent_id,
        "--local",
        "--message", message,
        "--json",
    ]
    logger.info("Agent turn [%s] → %.80s…", agent_id, message)
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    stdout = (proc.stdout or "").strip()
    if proc.returncode != 0:
        logger.warning(
            "openclaw [%s] exit %d  stderr: %.200s",
            agent_id, proc.returncode, proc.stderr or "",
        )
    # Output may carry a non-JSON leading line from streamed output; find first '{'.
    json_start = stdout.find("{")
    if json_start != -1:
        try:
            return json.loads(stdout[json_start:])
        except json.JSONDecodeError:
            pass
    return {"raw_output": stdout[:500], "exit_code": proc.returncode}


def _tool_call_from_content_item(item: Any) -> dict[str, Any] | None:
    """
    Map one assistant-message content item to a web tool call, or None.

    Only genuine `{"type": "toolCall"}` entries count. URL is read from the
    call's arguments (web_fetch → url, web_search → query). This deliberately
    does NOT match a tool *schema* descriptor (which has no `type: toolCall`
    and no arguments), so the system-prompt tool catalogue can never pose as a
    real call.
    """
    if not isinstance(item, dict) or item.get("type") != "toolCall":
        return None
    raw_name = item.get("name") or item.get("tool")
    if not isinstance(raw_name, str):
        return None
    alias = _WEB_TOOL_ALIASES.get(raw_name.strip().lower())
    if not alias:
        return None
    args = item.get("arguments") or item.get("args") or item.get("input")
    url = ""
    if isinstance(args, dict):
        for key in ("url", "uri", "link", "target", "query", "q"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                url = val.strip()
                break
    return {"tool": alias, "url": url}


def _session_file_from_output(output: Any) -> Path | None:
    """Extract `meta.agentMeta.sessionFile` (the per-turn message log) if present."""
    if not isinstance(output, dict):
        return None
    meta = output.get("meta")
    agent_meta = meta.get("agentMeta") if isinstance(meta, dict) else None
    session_file = agent_meta.get("sessionFile") if isinstance(agent_meta, dict) else None
    if isinstance(session_file, str) and session_file.strip():
        return Path(session_file)
    return None


def _extract_tool_calls_from_session(session_file: Path) -> list[dict[str, Any]]:
    """
    Ground-truth web tool calls for the *most recent turn* in a session log.

    This is the fabrication ground-truth: an agent that never calls web_fetch /
    web_search cannot produce these entries (it does not author the session
    log). Two subtleties drive the implementation:

    1. OpenClaw `--local` resumes a persistent per-agent session and *appends*
       each turn, so the jsonl accumulates across turns and across runs. We
       scope to the last user message (the message this turn just sent) and only
       collect tool calls emitted after it — otherwise stale calls from earlier
       turns/runs would be counted.
    2. Real calls live in assistant-message `content[].type == "toolCall"`
       items, NOT in the `--json` stdout summary (whose only tool reference is
       the static schema catalogue under `meta.systemPromptReport`).
    """
    try:
        raw_lines = session_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    records: list[dict[str, Any]] = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)

    # Boundary: start after the last user message (= the turn we just sent).
    start = 0
    for idx, rec in enumerate(records):
        msg = rec.get("message")
        if (
            rec.get("type") == "message"
            and isinstance(msg, dict)
            and msg.get("role") == "user"
        ):
            start = idx + 1

    found: list[dict[str, Any]] = []
    for rec in records[start:]:
        if rec.get("type") != "message":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            tc = _tool_call_from_content_item(item)
            if tc:
                found.append(tc)
    return found


def invoke(inv: AgentInvocation) -> AgentRunResult:
    """
    Drive a bounded agent invocation.

    Writes input_spec (if provided), runs up to max_turns turns within the
    wall-clock budget, stops early once all expected_outputs exist, parses tool
    calls for downstream validation, and persists a run log.

    Raises:
        AgentGatewayError — openclaw binary not found (unrecoverable).
    """
    if inv.input_spec is not None and inv.input_spec_path is not None:
        inv.input_spec_path.parent.mkdir(parents=True, exist_ok=True)
        inv.input_spec_path.write_text(
            json.dumps(inv.input_spec, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    wall_start = time.time()
    turn = 0
    status = "incomplete"
    tool_calls: list[dict[str, Any]] = []
    raw_outputs: list[dict[str, Any]] = []

    while turn < inv.max_turns:
        if time.time() - wall_start > inv.wall_clock_s:
            logger.warning("Agent [%s] wall-clock %ds reached", inv.agent_id, inv.wall_clock_s)
            status = "timeout"
            break

        turn += 1
        try:
            output = _run_agent_turn(
                inv.agent_id, inv.prompt, inv.repo_root, inv.turn_timeout_s
            )
        except subprocess.TimeoutExpired:
            logger.error("Agent [%s] turn %d timed out after %ds", inv.agent_id, turn, inv.turn_timeout_s)
            status = "timeout"
            continue
        except FileNotFoundError as exc:
            raise AgentGatewayError(
                f"'openclaw' binary not found — ensure it is on PATH: {exc}"
            ) from exc

        raw_outputs.append(output)
        session_file = _session_file_from_output(output)
        if session_file is not None and session_file.exists():
            tool_calls.extend(_extract_tool_calls_from_session(session_file))
        else:
            logger.warning(
                "Agent [%s] turn %d: no readable sessionFile in output meta — "
                "tool-call ground truth unavailable for this turn",
                inv.agent_id, turn,
            )

        if inv.expected_outputs and all(p.exists() for p in inv.expected_outputs):
            status = "complete"
            break

    outputs_present = [p for p in inv.expected_outputs if p.exists()]
    outputs_missing = [p for p in inv.expected_outputs if not p.exists()]
    if status == "incomplete" and inv.expected_outputs and not outputs_missing:
        status = "complete"

    raw_log_path = inv.run_log_path
    if raw_log_path is not None:
        raw_log_path.parent.mkdir(parents=True, exist_ok=True)
        raw_log_path.write_text(
            json.dumps(
                {
                    "agent_id": inv.agent_id,
                    "turns_used": turn,
                    "status": status,
                    "tool_calls": tool_calls,
                    "raw_outputs": raw_outputs,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return AgentRunResult(
        status=status,
        turns_used=turn,
        outputs_present=outputs_present,
        outputs_missing=outputs_missing,
        tool_calls=tool_calls,
        raw_outputs=raw_outputs,
        raw_log_path=raw_log_path,
    )
