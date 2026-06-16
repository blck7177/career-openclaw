"""
Pipeline Runner — orchestrates the processing pipeline for a candidate pool.

Pipeline: fetch → research → classify → extract → validate → save → log

This is the ONLY place that knows the step order.
Called by career_run_discovery wrapper via tools/run_discovery.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .classifier import classify_workstream
from .connectors.connector_router import load_company_boards, route as connector_route
from .contracts import (
    FETCH_STATUS_FAILED,
    FETCH_STATUS_PARTIAL,
    FETCH_STATUS_SUCCESS,
    SOURCE_TYPE_UNKNOWN,
)
from .extractor import extract_fields
from .fetcher import FetchResult, save_raw_jd
from .llm_role_context import get_llm_role_context
from .run_logger import log_step, log_validation_error, write_jobs_structured, write_run_summary
from .storage_jsonl import upsert_job
from .validator import validate_record

RUNNER_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0.0"


def _job_id(url: str) -> str:
    return "job_" + hashlib.md5(url.encode()).hexdigest()[:8]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _get_llm_client():
    from .llm_client import make_client
    return make_client()


def run_processing_pipeline(
    workspace_root: Path,
    session_id: str,
    candidates_file: Path,
    dry_run: bool = False,
    max_jobs: int | None = None,
    config_root: Path | None = None,
) -> dict[str, Any]:
    """
    Process a candidate_pool.jsonl and produce structured job records.

    workspace_root : path to workspace data directory (runs/, db/).
                     e.g. data/workspaces/dev_default/
    config_root    : path containing configs/ and schemas/ subdirectories.
                     Defaults to workspace_root for backward compatibility.
                     In production, pass the repo root.

    Returns a summary dict.
    """
    t_start = time.time()
    _config_root = config_root if config_root is not None else workspace_root

    run_dir = workspace_root / "runs" / session_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "raw_jds").mkdir(exist_ok=True)

    rc_path = run_dir / "run_config.yaml"
    if rc_path.exists():
        with open(rc_path) as f:
            run_config = yaml.safe_load(f) or {}
    else:
        run_config = {}

    profile_name = run_config.get("profile_name", "unknown")

    candidates = _read_jsonl(candidates_file)
    if max_jobs:
        candidates = candidates[:max_jobs]

    log_step(run_dir, "pipeline_start", None, "started", {
        "session_id": session_id,
        "candidates_count": len(candidates),
        "dry_run": dry_run,
    })

    llm_client = _get_llm_client()
    if llm_client is None:
        log_step(run_dir, "llm_init", None, "warning", {"message": "No LLM client — extraction will use empty stubs"})

    boards_registry = load_company_boards(_config_root)
    db_dir = workspace_root / "db"

    stats = {"jobs_discovered": len(candidates), "jobs_fetched": 0,
             "jobs_structured": 0, "jobs_saved": 0, "jobs_failed": 0, "jobs_skipped": 0}
    structured_records: list[dict[str, Any]] = []
    workstream_counts: dict[str, int] = {}

    for cand in candidates:
        url = cand.get("url", "")
        title = cand.get("title", "Unknown")
        company = cand.get("company", "Unknown")
        location = cand.get("location", "")
        job_id = _job_id(url)
        # source_type will be set by the connector; use a placeholder until fetch
        source_type = SOURCE_TYPE_UNKNOWN

        log_step(run_dir, "fetch_start", job_id, "started", {"url": url})

        # Step 1: Fetch via connector router (ATS-aware)
        fetch_result: FetchResult
        if url:
            fetch_result = connector_route(url, boards_registry)
        else:
            fetch_result = FetchResult(status=FETCH_STATUS_FAILED, error="no URL provided", source_type=SOURCE_TYPE_UNKNOWN)

        raw_jd_path = ""
        if fetch_result.status in (FETCH_STATUS_SUCCESS, FETCH_STATUS_PARTIAL):
            stats["jobs_fetched"] += 1
            raw_jd_path = save_raw_jd(fetch_result.text, run_dir / "raw_jds", job_id)
            log_step(run_dir, "fetch_done", job_id, "success", {
                "chars": fetch_result.content_length,
                "source_type": fetch_result.source_type,
            })
        else:
            log_step(run_dir, "fetch_done", job_id, "failed", {
                "error": fetch_result.error,
                "url": url,
                "source_type": fetch_result.source_type,
                "failure_stage": fetch_result.failure_stage,
                "error_type": fetch_result.error_type,
                "retryable": fetch_result.retryable,
                "recommended_next_actions": fetch_result.recommended_next_actions,
            })
            if fetch_result.status == FETCH_STATUS_FAILED:
                stats["jobs_failed"] += 1
                continue

        jd_text = fetch_result.text

        # Step 2: LLM role context (training-knowledge hint for extraction, not web research)
        role_context_obj = get_llm_role_context(company, title, llm_client)
        role_context_str = role_context_obj.company_description
        log_step(run_dir, "llm_context_done", job_id, "success")

        # Step 3: Classify
        classification = classify_workstream(jd_text, {}, _config_root, llm_client)
        log_step(run_dir, "classify_done", job_id, "success", {
            "primary": classification.primary_workstream,
            "confidence": classification.classification_confidence,
        })

        # Step 4: Extract
        extracted = extract_fields(jd_text, company, title, role_context_str, llm_client)
        log_step(run_dir, "extract_done", job_id, "success")

        # Assemble record
        record: dict[str, Any] = {
            "job_id": job_id,
            "title": title,
            "company": company,
            "location": location,
            "source_url": url,
            "source_type": fetch_result.source_type,
            "date_found": _date_today(),
            "fetch_status": fetch_result.status,
            "raw_jd_path": raw_jd_path,
            **extracted,
            "primary_workstream": classification.primary_workstream,
            "secondary_workstreams": classification.secondary_workstreams,
            "classification_confidence": classification.classification_confidence,
            "classification_evidence": classification.classification_evidence,
            "uncertainty_notes": classification.uncertainty_notes,
            "possible_duplicate": False,
            "validation_status": "pending",
            "validation_errors": [],
            "run_id": session_id,
            "schema_version": SCHEMA_VERSION,
        }

        # Step 5: Validate
        # Use a temp copy so that the schema's validation_status enum constraint
        # (which disallows "pending") does not block self-validation.
        record_for_validation = {**record, "validation_status": "passed", "validation_errors": []}
        validation = validate_record(record_for_validation, _config_root)
        record["validation_status"] = "passed" if validation.passed else "failed"
        record["validation_errors"] = validation.errors

        if not validation.passed:
            stats["jobs_failed"] += 1
            log_validation_error(run_dir, job_id, validation.errors)
            log_step(run_dir, "validate_done", job_id, "failed", {"errors": validation.errors})
            structured_records.append(record)
            continue

        stats["jobs_structured"] += 1
        log_step(run_dir, "validate_done", job_id, "passed")

        # Step 6: Save
        if not dry_run:
            save_result = upsert_job(record, db_dir)
            stats["jobs_saved"] += 1
            log_step(run_dir, "save_done", job_id, save_result["action"])
        else:
            log_step(run_dir, "save_done", job_id, "dry_run_skipped")

        structured_records.append(record)

        ws = classification.primary_workstream
        workstream_counts[ws] = workstream_counts.get(ws, 0) + 1

    # Step 7: Artifacts
    write_jobs_structured(run_dir, structured_records)

    top_workstreams = sorted(
        [{"workstream": ws, "count": cnt} for ws, cnt in workstream_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )

    duration = time.time() - t_start
    write_run_summary(run_dir, session_id, profile_name, stats, top_workstreams, duration)

    log_step(run_dir, "pipeline_complete", None, "completed", {**stats, "duration_seconds": round(duration, 1)})

    return {
        "run_id": session_id,
        "run_dir": str(run_dir),
        "dry_run": dry_run,
        **stats,
        "top_workstreams": top_workstreams,
        "duration_seconds": round(duration, 1),
    }


