"""
ReportService — global Job Intelligence Report queries.

Reports are global (no workspace_id) — they describe a job role itself,
not any user's relationship to it.

Artifact layout (under data/global/job_report_artifacts/<job_report_id>/):
  report.md         — Layer 1 narrative markdown
  structured.json   — Layer 2 structured JSON (conforms to job_report.schema.json)
  sources.json      — web research sources used

MetadataStore is the index; the filesystem holds the actual content.
"""

from __future__ import annotations

import json
from typing import Any

from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import get_data_root, get_global_paths


def _store() -> MetadataStore:
    store = MetadataStore.from_data_root(get_data_root())
    store.init_schema()
    return store


def get_job_report(job_id: str) -> dict[str, Any] | None:
    """
    Return the active Job Intelligence Report for a job, or None if none exists.

    The returned dict contains:
      job_report_id, job_id, jd_hash, prompt_version, model, status, created_at
      narrative      : str | None  — content of report.md
      structured     : dict | None — parsed structured.json
      sources        : list | None — parsed sources.json
    """
    store = _store()
    global_paths = get_global_paths()

    # Find the most recently created active report for this job
    with store._conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM job_reports
            WHERE job_id = ? AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()

    if row is None:
        return None

    report = dict(row)
    report_id = report["job_report_id"]
    report_dir = global_paths.job_report_dir(report_id)

    report["narrative"] = _read_text(report_dir / "report.md")
    report["structured"] = _read_json(report_dir / "structured.json")
    report["sources"] = _read_json(report_dir / "sources.json")

    return report


def list_job_reports(job_id: str) -> list[dict[str, Any]]:
    """
    Return all Job Intelligence Reports for a job (active + superseded),
    newest first.

    Does NOT load artifact content — use get_job_report for full content.
    """
    store = _store()

    with store._conn() as conn:
        rows = conn.execute(
            """
            SELECT job_report_id, job_id, jd_hash, prompt_version, model,
                   status, superseded_by, created_at
            FROM job_reports
            WHERE job_id = ?
            ORDER BY created_at DESC
            """,
            (job_id,),
        ).fetchall()

    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_text(path: Any) -> str | None:
    try:
        from pathlib import Path
        p = Path(path)
        if p.exists():
            return p.read_text(encoding="utf-8")
    except OSError:
        pass
    return None


def _read_json(path: Any) -> Any:
    try:
        from pathlib import Path
        p = Path(path)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return None
