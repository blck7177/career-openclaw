"""
Agent Gateway — generic bounded-agent invocation for the worker.

Wraps the OpenClaw subprocess interface so worker-side services can invoke any
bounded agent (career-search-agent / career-research / career-reflect-agent)
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


def _find_url(node: dict[str, Any]) -> str:
    """Best-effort URL extraction from a tool-call node."""
    for key in ("url", "uri", "link", "target"):
        val = node.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    args = node.get("args") or node.get("input") or node.get("arguments")
    if isinstance(args, dict):
        for key in ("url", "uri", "link", "query", "q"):
            val = args.get(key)
            if isinstance(val, str):
                return val
    return ""


def _extract_tool_calls(output: Any) -> list[dict[str, Any]]:
    """
    Recursively scan an agent JSON output for web_search / web_fetch tool calls.

    This is the fabrication ground-truth: an agent that never calls web_fetch
    cannot produce these entries (it does not control the run log). The exact
    OpenClaw JSON shape is not contractually fixed, so this scan is defensive —
    it matches any dict that names a known web tool.
    """
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            raw_name = node.get("tool") or node.get("name") or node.get("tool_name")
            if isinstance(raw_name, str):
                alias = _WEB_TOOL_ALIASES.get(raw_name.strip().lower())
                if alias:
                    found.append({"tool": alias, "url": _find_url(node)})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(output)
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
        tool_calls.extend(_extract_tool_calls(output))

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
