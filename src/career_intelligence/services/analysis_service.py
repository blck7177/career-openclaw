"""
AnalysisService — orchestrates Job Intelligence Report generation.

This is the single entry point for creating a global job report.  It:
  1. Resolves the raw JD text from the workspace job record.
  2. Checks the MetadataStore cache (job_id + jd_hash + prompt_version).
  3. On cache miss, calls role_analyzer.analyze_role() and writes artifacts.
  4. Inserts the new report into MetadataStore, superseding any prior active report.

The output (report.md + structured.json) is written to:
  data/global/job_report_artifacts/<job_report_id>/

Design notes:
  - Takes RequestContext so it can locate the workspace-scoped job record / raw JD.
  - The output is global (shared across workspaces) even though the trigger is workspace-scoped.
  - Use force=True to re-generate even when a cached report exists.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import yaml

from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import (
    get_catalog_workspace_id,
    get_data_root,
    get_global_paths,
    get_workspace_paths,
)
from career_intelligence.llm_client import make_client
from career_intelligence.role_analyzer import PROMPT_VERSION, analyze_role
from career_intelligence.services.job_service import get_job


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_job_report(
    ctx: RequestContext,
    job_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """
    Generate (or return cached) a global Job Intelligence Report.

    Args:
        ctx:     RequestContext — used to locate the workspace job record and raw JD.
        job_id:  The job to analyze.
        force:   If True, skip cache and regenerate even if an active report exists.

    Returns:
        {
          "job_report_id": str,
          "status": "created" | "cache_hit",
          "report_path": str,
          "structured_path": str,
        }

    Raises:
        ValueError  — job not found, or no JD text available.
        RuntimeError — LLM client unavailable or analysis failed.
    """
    data_root = get_data_root()
    store = MetadataStore.from_data_root(data_root)
    store.init_schema()

    # 1. Load job record from the shared catalog
    job_record = get_job(ctx, job_id)
    if job_record is None:
        raise ValueError(f"Job not found in catalog: {job_id}")

    # 2. Resolve raw JD text from the catalog workspace (where the pipeline wrote it)
    jd_text = _resolve_jd_text(job_record, get_catalog_workspace_id(), data_root)

    # 3. Compute cache key
    jd_hash = hashlib.md5(jd_text.encode("utf-8")).hexdigest()[:16]

    # 4. Cache lookup
    if not force:
        cached = store.get_active_job_report(job_id, jd_hash, PROMPT_VERSION)
        if cached:
            return {
                "job_report_id": cached["job_report_id"],
                "status": "cache_hit",
                "report_path": cached.get("report_path", ""),
                "structured_path": cached.get("structured_path", ""),
            }

    # 5. Load taxonomy and LLM client
    taxonomy = _load_taxonomy(data_root)
    llm_client = make_client()
    if llm_client is None:
        raise RuntimeError(
            "No LLM API key configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY."
        )

    # 6. Run analysis
    report_md, structured_report, prompt_version = analyze_role(
        jd_text=jd_text,
        job_record=job_record,
        taxonomy=taxonomy,
        llm_client=llm_client,
    )

    # 7. Write artifacts
    global_paths = get_global_paths(data_root)
    job_report_id = "rpt_" + uuid.uuid4().hex[:8]
    artifact_dir = global_paths.job_report_dir(job_report_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    report_path = global_paths.job_report_narrative(job_report_id)
    structured_path = global_paths.job_report_structured(job_report_id)

    report_path.write_text(report_md, encoding="utf-8")
    structured_path.write_text(
        json.dumps(structured_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 8. Insert into MetadataStore (auto-supersedes prior active report)
    model_name = getattr(llm_client, "_default_model", None)
    store.insert_job_report(
        job_id=job_id,
        jd_hash=jd_hash,
        prompt_version=prompt_version,
        model=model_name if isinstance(model_name, str) else None,
        report_path=str(report_path),
        structured_path=str(structured_path),
        job_report_id=job_report_id,
    )

    return {
        "job_report_id": job_report_id,
        "status": "created",
        "report_path": str(report_path),
        "structured_path": str(structured_path),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_jd_text(
    job_record: dict[str, Any],
    workspace_id: str,
    data_root: Path,
) -> str:
    """
    Return the raw JD text for a job record.

    Resolution order:
      1. job_record["jd_text"] — inline text (future use)
      2. job_record["raw_jd_path"] — relative path under runs_root/
      3. Raise ValueError if neither is available.
    """
    # Inline text (not currently written by runner, reserved for future use)
    inline = (job_record.get("jd_text") or "").strip()
    if inline:
        return inline

    # File path relative to workspace runs_root
    raw_jd_rel = (job_record.get("raw_jd_path") or "").strip()
    if raw_jd_rel:
        ws_paths = get_workspace_paths(workspace_id, data_root)
        jd_file = ws_paths.runs_root / raw_jd_rel
        if jd_file.exists():
            text = jd_file.read_text(encoding="utf-8").strip()
            if text:
                return text

    raise ValueError(
        f"No JD text available for job {job_record.get('job_id')}. "
        f"Expected inline jd_text or readable raw_jd_path "
        f"(got: {job_record.get('raw_jd_path')!r})."
    )


def _load_taxonomy(data_root: Path) -> list[dict[str, Any]]:
    """Load workstream taxonomy from configs/workstream_taxonomy.yaml."""
    from career_intelligence.app_state.workspace_paths import get_repo_root

    taxonomy_path = get_repo_root() / "configs" / "workstream_taxonomy.yaml"
    if not taxonomy_path.exists():
        return []
    with open(taxonomy_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("workstreams", []) if isinstance(data, dict) else []
