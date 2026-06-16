"""
Research Service — produce and validate web-research bundles for Job Reports.

Worker-side orchestration of the career-research. Owns the workflow; the
agent only collects evidence:

  1. resolve job_record + JD, compute research_inputs_hash (cache/freshness key)
  2. on cache miss, derive a research plan (research_planner)
  3. invoke career-research via agent_gateway (it runs web_search/web_fetch
     and writes research_notes.md + research_sources.json + a fetch ledger)
  4. validate the bundle with research_validator (anti-fabrication gate)
  5. persist bundle provenance to MetadataStore + filesystem

A failed validation is NOT fatal: the caller falls back to a JD-only report.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import (
    get_catalog_workspace_id,
    get_data_root,
    get_global_paths,
    get_repo_root,
)
from career_intelligence.llm_client import make_client
from career_intelligence.research_planner import build_research_plan
from career_intelligence.research_validator import validate_research_bundle
from career_intelligence.services import agent_gateway
from career_intelligence.services.analysis_service import _resolve_jd_text
from career_intelligence.services.job_service import get_job
from career_intelligence.url_utils import url_hash

RESEARCH_PLANNER_VERSION = "0.1.0"
NONE_BUNDLE_HASH = "none"
_RESEARCH_AGENT_ID = os.environ.get("OPENCLAW_RESEARCH_AGENT_ID", "career-research")
_MAX_FETCHES = int(os.environ.get("RESEARCH_MAX_FETCHES", "3"))
_MIN_VERIFIED = int(os.environ.get("RESEARCH_MIN_VERIFIED", "1"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jd_hash(jd_text: str) -> str:
    return hashlib.md5(jd_text.encode("utf-8")).hexdigest()[:16]


def _research_inputs_hash(job_id: str, jd_hash: str) -> str:
    key = f"{job_id}:{jd_hash}:{RESEARCH_PLANNER_VERSION}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def _bundle_content_hash(notes_text: str, sources: list[dict[str, Any]]) -> str:
    blob = notes_text + json.dumps(sources, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(blob.encode("utf-8")).hexdigest()[:16]


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _build_prompt(job_record: dict[str, Any], input_spec_path: Path) -> str:
    """Task envelope only. Workflow/tool order/fetch budget/source-verification
    gate/output format/stopping rules live in the career-job-research-operator
    skill + references (single source of truth); the prompt never restates them."""
    return (
        "You are executing a bounded research turn for ONE known job.\n\n"
        "Read and follow the career-job-research-operator skill and its references. "
        "They are the source of truth for workflow, tool order, fetch budget, the "
        "source-verification gate, output format, and stopping rules. If anything "
        "in this prompt appears to conflict with the skill, follow the skill.\n\n"
        f"Read your task spec from: {input_spec_path}\n"
        f"  job_id : {job_record.get('job_id', '')}\n\n"
        "Write the expected outputs to the paths given in the task spec, then STOP."
    )


def _bundle_return(
    *,
    validation_status: str,
    bundle_hash: str,
    used_research: bool,
    notes_path: Path,
    sources_path: Path,
    sources: list[dict[str, Any]],
    source_count: int,
    verified_source_count: int,
    reason: str = "",
) -> dict[str, Any]:
    return {
        "validation_status": validation_status,
        "bundle_hash": bundle_hash,
        "used_research": used_research,
        "notes_path": str(notes_path),
        "sources_path": str(sources_path),
        "sources": sources,
        "source_count": source_count,
        "verified_source_count": verified_source_count,
        "reason": reason,
    }


def ensure_research_bundle(
    ctx: RequestContext,
    job_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """
    Ensure a (validated) research bundle exists for job_id; return its summary.

    Return contract (consumed by analysis_service.create_job_report):
        {
          validation_status: "passed" | "partial" | "failed",
          bundle_hash: str,          # "none" when not usable
          used_research: bool,       # whether report should use the notes
          notes_path: str, sources_path: str, sources: list,
          source_count: int, verified_source_count: int, reason: str,
        }

    Never raises on agent/validation failure — returns a failed bundle so the
    caller can fall back to a JD-only report. Raises ValueError only when the
    job or its JD text cannot be resolved at all.
    """
    data_root = get_data_root()
    store = MetadataStore.from_data_root(data_root)
    store.init_schema()

    job_record = get_job(ctx, job_id)
    if job_record is None:
        raise ValueError(f"Job not found in catalog: {job_id}")

    jd_text = _resolve_jd_text(job_record, get_catalog_workspace_id(), data_root)
    jd_hash = _jd_hash(jd_text)
    inputs_hash = _research_inputs_hash(job_id, jd_hash)

    global_paths = get_global_paths(data_root)
    notes_path = global_paths.research_notes(job_id, inputs_hash)
    sources_path = global_paths.research_sources(job_id, inputs_hash)
    ledger_path = global_paths.research_fetch_ledger(job_id, inputs_hash)
    input_spec_path = global_paths.research_input_spec(job_id, inputs_hash)
    run_log_path = global_paths.research_run_log(job_id, inputs_hash)
    bundle_record_path = global_paths.research_bundle_record(job_id, inputs_hash)

    # Cache hit
    if not force:
        cached = store.get_active_research_bundle(job_id, inputs_hash)
        if cached:
            sources = _read_json(sources_path, [])
            status = cached["validation_status"]
            return _bundle_return(
                validation_status=status,
                bundle_hash=cached["bundle_hash"] if status != "failed" else NONE_BUNDLE_HASH,
                used_research=status in ("passed", "partial"),
                notes_path=notes_path,
                sources_path=sources_path,
                sources=sources if isinstance(sources, list) else [],
                source_count=cached.get("source_count", 0),
                verified_source_count=cached.get("verified_source_count", 0),
                reason="cache_hit",
            )

    bundle_dir = global_paths.research_bundle_dir(job_id, inputs_hash)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # Build the research plan and the agent input spec
    llm_client = make_client()
    plan = build_research_plan(job_record, llm_client)
    input_spec = {
        "job_id": job_id,
        "research_inputs_hash": inputs_hash,
        "company": job_record.get("company", ""),
        "title": job_record.get("title", ""),
        "source_url": job_record.get("source_url", ""),
        "jd_excerpt": jd_text[:2000],
        "queries": plan.queries,
        "context_gaps": plan.context_gaps,
        "avoid_queries": plan.avoid_queries,
        "max_fetches": _MAX_FETCHES,
        "expected_output_paths": {
            "research_notes": str(notes_path),
            "research_sources": str(sources_path),
            "fetch_ledger": str(ledger_path),
        },
    }

    invocation = agent_gateway.AgentInvocation(
        agent_id=_RESEARCH_AGENT_ID,
        prompt=_build_prompt(job_record, input_spec_path),
        repo_root=get_repo_root(),
        expected_outputs=[notes_path, sources_path],
        input_spec=input_spec,
        input_spec_path=input_spec_path,
        run_log_path=run_log_path,
        max_turns=int(os.environ.get("RESEARCH_MAX_TURNS", "3")),
    )

    try:
        run_result = agent_gateway.invoke(invocation)
        tool_calls = run_result.tool_calls
    except agent_gateway.AgentGatewayError:
        # openclaw missing / unrecoverable — treat as a failed bundle (JD-only).
        tool_calls = []

    notes_text = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
    sources = _read_json(sources_path, [])
    if not isinstance(sources, list):
        sources = []
    fetch_ledger = _read_jsonl(ledger_path)

    validation = validate_research_bundle(
        notes_text=notes_text,
        sources=sources,
        fetch_ledger=fetch_ledger,
        tool_calls=tool_calls,
        min_verified=_MIN_VERIFIED,
    )

    # Annotate sources with verification result
    verified_by_hash = {p.url_hash: p.verified for p in validation.per_source}
    for src in sources:
        url = (src.get("url") or "").strip()
        src["verified"] = bool(verified_by_hash.get(url_hash(url), False)) if url else False

    bundle_hash = (
        _bundle_content_hash(notes_text, sources)
        if validation.usable
        else NONE_BUNDLE_HASH
    )

    # Persist filesystem bundle record + MetadataStore provenance
    bundle_record = {
        "job_id": job_id,
        "company": job_record.get("company", ""),
        "research_inputs_hash": inputs_hash,
        "bundle_hash": bundle_hash,
        "used_research": validation.usable,
        "validation_status": validation.status,
        "validation_reason": validation.reason,
        "source_count": validation.source_count,
        "verified_source_count": validation.verified_source_count,
        "sources": sources,
        "notes_path": str(notes_path),
        "sources_path": str(sources_path),
        "run_log_path": str(run_log_path),
        "generated_at": _now_iso(),
    }
    bundle_record_path.write_text(
        json.dumps(bundle_record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Re-write sources with verification annotation
    sources_path.write_text(
        json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    store.insert_research_bundle(
        job_id=job_id,
        research_inputs_hash=inputs_hash,
        bundle_hash=bundle_hash,
        validation_status=validation.status,
        source_count=validation.source_count,
        verified_source_count=validation.verified_source_count,
        notes_path=str(notes_path),
        sources_path=str(sources_path),
        run_log_path=str(run_log_path),
    )

    return _bundle_return(
        validation_status=validation.status,
        bundle_hash=bundle_hash,
        used_research=validation.usable,
        notes_path=notes_path,
        sources_path=sources_path,
        sources=sources,
        source_count=validation.source_count,
        verified_source_count=validation.verified_source_count,
        reason=validation.reason,
    )
