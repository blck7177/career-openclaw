"""CLI adapter for runner.py — career_run_discovery wrapper."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from career_intelligence.app_state.context import DEV_CTX
from career_intelligence.app_state.workspace_paths import get_repo_root, get_workspace_paths

# REPO_ROOT: repo root — contains configs/, schemas/, .env
REPO_ROOT = get_repo_root()
# WORKSPACE_ROOT: workspace data root — contains runs/, db/, strategy_state.json
WORKSPACE_ROOT = get_workspace_paths(DEV_CTX.workspace_id).root


@click.command()
@click.option("--from-candidates", required=True, help="Path to candidate_pool.jsonl")
@click.option("--dry-run", is_flag=True, default=False, help="Run pipeline without saving to db")
@click.option("--max-jobs", default=None, type=int, help="Limit number of candidates processed")
def main(from_candidates: str, dry_run: bool, max_jobs: int | None) -> None:
    """Process a candidate pool through the full pipeline (fetch → classify → extract → validate → save)."""
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(REPO_ROOT / ".env")

    candidates_path = Path(from_candidates)
    if not candidates_path.exists():
        click.echo(json.dumps({"error": f"candidates file not found: {from_candidates}"}))
        sys.exit(1)

    # Derive session_id from the path (parent dir name = session_id)
    session_id = candidates_path.parent.name

    from career_intelligence.runner import run_processing_pipeline

    result = run_processing_pipeline(
        workspace_root=WORKSPACE_ROOT,
        session_id=session_id,
        candidates_file=candidates_path,
        dry_run=dry_run,
        max_jobs=max_jobs,
        config_root=REPO_ROOT,
    )

    click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    if result.get("jobs_failed", 0) > 0 and result.get("jobs_saved", 0) == 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
