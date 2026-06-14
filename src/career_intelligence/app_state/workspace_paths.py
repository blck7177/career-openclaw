"""
WorkspacePaths and GlobalPaths — single source of truth for all filesystem paths.

Rules:
- No code outside app_state/ or services/ should construct data paths manually.
- All paths are derived from data_root, which defaults to get_data_root().
- CLI tools and wrappers call get_workspace_paths(ctx) to obtain a WorkspacePaths instance.

Directory layout:

    data/
      app.sqlite
      global/
        jobs_cache.jsonl
        job_reports.jsonl
        job_report_artifacts/
          <job_report_id>/
            report.md
            structured.json
            sources.json
      workspaces/
        <workspace_id>/
          db/
            jobs.jsonl
            job_index.json
            fit_reports.jsonl
          runs/
            <run_id>/
              run_config.yaml
              candidate_pool.jsonl
              ...
          uploads/
            resumes/
          profiles/
          strategy_state.json
"""

from __future__ import annotations

import os
from pathlib import Path

# Workspace id whose job store backs the shared, browsable job catalog.
# Job records (titles, JDs, structured fields) are not user-specific, so every
# workspace browses this one catalog. It defaults to dev_default, which is where
# the search/process pipeline writes. Override with CATALOG_WORKSPACE_ID.
_DEFAULT_CATALOG_WORKSPACE_ID = "dev_default"


def get_repo_root() -> Path:
    """Absolute path to the career-openclaw repo root.

    This file lives at:
      career-openclaw/src/career_intelligence/app_state/workspace_paths.py
    parents[3] resolves to career-openclaw/.
    """
    return Path(__file__).resolve().parents[3]


def get_data_root() -> Path:
    """Absolute path to the data/ directory at the repo root."""
    return get_repo_root() / "data"


def get_catalog_workspace_id() -> str:
    """
    Return the workspace id that backs the shared, browsable job catalog.

    Job records are not user-specific, so all workspaces read jobs from this one
    catalog workspace (a newly-invited user therefore sees jobs immediately).
    Defaults to dev_default; override with the CATALOG_WORKSPACE_ID env var.
    """
    return os.getenv("CATALOG_WORKSPACE_ID", _DEFAULT_CATALOG_WORKSPACE_ID)


class WorkspacePaths:
    """All filesystem paths scoped to a single workspace."""

    def __init__(self, data_root: Path, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        self.root = data_root / "workspaces" / workspace_id

    # -------------------------------------------------------------------------
    # Database (structured job records, fit reports)
    # -------------------------------------------------------------------------

    @property
    def db_dir(self) -> Path:
        return self.root / "db"

    @property
    def jobs_db(self) -> Path:
        return self.db_dir / "jobs.jsonl"

    @property
    def job_index(self) -> Path:
        return self.db_dir / "job_index.json"

    @property
    def fit_reports_db(self) -> Path:
        return self.db_dir / "fit_reports.jsonl"

    # -------------------------------------------------------------------------
    # Strategy state
    # -------------------------------------------------------------------------

    @property
    def strategy_state(self) -> Path:
        """Cross-run search strategy, workspace-scoped."""
        return self.root / "strategy_state.json"

    # -------------------------------------------------------------------------
    # Runs
    # -------------------------------------------------------------------------

    @property
    def runs_root(self) -> Path:
        return self.root / "runs"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    # -------------------------------------------------------------------------
    # Uploads and profiles (user-private)
    # -------------------------------------------------------------------------

    @property
    def uploads_dir(self) -> Path:
        return self.root / "uploads"

    @property
    def resumes_dir(self) -> Path:
        return self.uploads_dir / "resumes"

    @property
    def profiles_dir(self) -> Path:
        return self.root / "profiles"

    def candidate_profile_path(self, candidate_profile_id: str) -> Path:
        """Path to the JSON file for a specific candidate profile."""
        return self.profiles_dir / f"{candidate_profile_id}.json"

    # -------------------------------------------------------------------------
    # Reports (fit reports, workspace-scoped)
    # -------------------------------------------------------------------------

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    def fit_report_dir(self, fit_report_id: str) -> Path:
        return self.reports_dir / fit_report_id

    def fit_report_narrative(self, fit_report_id: str) -> Path:
        """Path to the narrative markdown for a specific fit report."""
        return self.fit_report_dir(fit_report_id) / "fit_report.md"

    def fit_report_structured(self, fit_report_id: str) -> Path:
        """Path to the structured JSON for a specific fit report."""
        return self.fit_report_dir(fit_report_id) / "structured.json"

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def ensure_dirs(self) -> None:
        """Create all workspace subdirectories if they don't exist."""
        for d in [
            self.db_dir,
            self.runs_root,
            self.uploads_dir,
            self.resumes_dir,
            self.profiles_dir,
            self.reports_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


class GlobalPaths:
    """All filesystem paths for global (cross-workspace) data."""

    def __init__(self, data_root: Path) -> None:
        self.root = data_root / "global"

    # -------------------------------------------------------------------------
    # Global job cache
    # -------------------------------------------------------------------------

    @property
    def jobs_cache(self) -> Path:
        return self.root / "jobs_cache.jsonl"

    # -------------------------------------------------------------------------
    # Job Intelligence Reports
    # -------------------------------------------------------------------------

    @property
    def job_reports_index(self) -> Path:
        """Global JSONL index of all Job Intelligence Reports."""
        return self.root / "job_reports.jsonl"

    @property
    def job_report_artifacts_root(self) -> Path:
        return self.root / "job_report_artifacts"

    def job_report_dir(self, job_report_id: str) -> Path:
        """Directory containing all artifacts for one Job Intelligence Report."""
        return self.job_report_artifacts_root / job_report_id

    def job_report_narrative(self, job_report_id: str) -> Path:
        """Layer 1 narrative markdown report."""
        return self.job_report_dir(job_report_id) / "report.md"

    def job_report_structured(self, job_report_id: str) -> Path:
        """Layer 2 structured JSON (conforms to job_report.schema.json)."""
        return self.job_report_dir(job_report_id) / "structured.json"

    def job_report_sources(self, job_report_id: str) -> Path:
        """Web research sources used to produce this report."""
        return self.job_report_dir(job_report_id) / "sources.json"

    # -------------------------------------------------------------------------
    # Research bundles (career-research evidence)
    # -------------------------------------------------------------------------

    @property
    def research_artifacts_root(self) -> Path:
        return self.root / "research_artifacts"

    def research_bundle_dir(self, job_id: str, research_inputs_hash: str) -> Path:
        """Directory holding one research bundle's artifacts."""
        return self.research_artifacts_root / job_id / research_inputs_hash

    def research_notes(self, job_id: str, research_inputs_hash: str) -> Path:
        return self.research_bundle_dir(job_id, research_inputs_hash) / "research_notes.md"

    def research_sources(self, job_id: str, research_inputs_hash: str) -> Path:
        return self.research_bundle_dir(job_id, research_inputs_hash) / "research_sources.json"

    def research_fetch_ledger(self, job_id: str, research_inputs_hash: str) -> Path:
        return self.research_bundle_dir(job_id, research_inputs_hash) / "research_fetch_ledger.jsonl"

    def research_input_spec(self, job_id: str, research_inputs_hash: str) -> Path:
        return self.research_bundle_dir(job_id, research_inputs_hash) / "agent_input.json"

    def research_run_log(self, job_id: str, research_inputs_hash: str) -> Path:
        return self.research_bundle_dir(job_id, research_inputs_hash) / "agent_run_log.json"

    def research_bundle_record(self, job_id: str, research_inputs_hash: str) -> Path:
        return self.research_bundle_dir(job_id, research_inputs_hash) / "research_bundle.json"

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def ensure_dirs(self) -> None:
        for d in [self.root, self.job_report_artifacts_root, self.research_artifacts_root]:
            d.mkdir(parents=True, exist_ok=True)


def get_workspace_paths(
    workspace_id: str,
    data_root: Path | None = None,
) -> WorkspacePaths:
    """
    Convenience factory. Uses get_data_root() if data_root is not provided.

    Usage in CLI tools:
        from career_intelligence.app_state import DEV_CTX
        from career_intelligence.app_state.workspace_paths import get_workspace_paths
        paths = get_workspace_paths(DEV_CTX.workspace_id)
    """
    return WorkspacePaths(data_root or get_data_root(), workspace_id)


def get_global_paths(data_root: Path | None = None) -> GlobalPaths:
    """Convenience factory for GlobalPaths."""
    return GlobalPaths(data_root or get_data_root())
