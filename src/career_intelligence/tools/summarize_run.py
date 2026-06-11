"""CLI adapter for run summary — career_summarize_run wrapper."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


@click.command()
@click.option("--run-id", required=True, help="Run ID (session timestamp)")
@click.option("--format", "fmt", default="markdown", type=click.Choice(["markdown", "json"]))
def main(run_id: str, fmt: str) -> None:
    """Display or generate a run summary."""
    run_dir = WORKSPACE_ROOT / "runs" / run_id

    if not run_dir.exists():
        click.echo(json.dumps({"error": f"Run {run_id} not found"}))
        sys.exit(1)

    if fmt == "markdown":
        md_path = run_dir / "run_summary.md"
        if md_path.exists():
            click.echo(md_path.read_text())
        else:
            click.echo(f"run_summary.md not found for {run_id}. Run career_run_discovery first.")
            sys.exit(1)
    else:
        json_path = run_dir / "run_summary.json"
        if json_path.exists():
            click.echo(json_path.read_text())
        else:
            click.echo(json.dumps({"error": f"run_summary.json not found for run {run_id}"}))
            sys.exit(1)

if __name__ == "__main__":
    main()
