"""CLI adapter — career_update_strategy wrapper.

Call at the end of each run to persist learnings into cross-run strategy state.
Accepts a JSON patch file with fields to merge into db/strategy_state.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from career_intelligence.app_state.context import DEV_CTX
from career_intelligence.app_state.workspace_paths import get_workspace_paths
from career_intelligence.strategy_state import PATCH_FIELDS, update_state

WORKSPACE_ROOT = get_workspace_paths(DEV_CTX.workspace_id).root

_PATCH_FIELDS = """
Supported fields in the patch JSON:
  effective_sources         list[str]  — sources that produced real JD URLs
  avoid_sources             list[str]  — sources with high 403/404/irrelevant rate
  effective_query_patterns  list[str]  — query patterns with good candidate yield
  avoid_query_patterns      list[str]  — patterns that returned search-result pages / irrelevant
  coverage_by_workstream    dict       — {workstream: "sufficient"|"weak"|"missing"}
  key_learnings             list[str]  — free-text learnings to accumulate across runs
  recommended_next_searches list[str]  — priority directions for the next run (replaced each time)

List fields are merged (union, deduped) with existing values.
recommended_next_searches replaces the previous value entirely.
"""


@click.command()
@click.option("--run-id", required=True, help="The current run ID (session timestamp).")
@click.option(
    "--patch-file",
    required=True,
    type=click.Path(exists=True),
    help="Path to a JSON file containing the fields to update.",
)
@click.option(
    "--format", "fmt",
    default="text",
    type=click.Choice(["json", "text"]),
)
def main(run_id: str, patch_file: str, fmt: str) -> None:
    """Merge run learnings into the cross-run workspace strategy state."""
    try:
        with open(patch_file, encoding="utf-8") as f:
            patch = json.load(f)
    except json.JSONDecodeError as e:
        click.echo(json.dumps({"error": f"Invalid JSON in patch file: {e}"}))
        sys.exit(1)

    if not isinstance(patch, dict):
        click.echo(json.dumps({"error": "Patch file must be a JSON object."}))
        sys.exit(1)

    unknown = set(patch.keys()) - set(PATCH_FIELDS)
    if unknown:
        click.echo(json.dumps({"error": f"Unknown patch fields: {sorted(unknown)}", "allowed_fields": _PATCH_FIELDS}))
        sys.exit(1)

    updated = update_state(WORKSPACE_ROOT, run_id, patch)

    if fmt == "json":
        click.echo(json.dumps(updated, indent=2, ensure_ascii=False))
    else:
        click.echo(f"Strategy state updated for run {run_id}.")
        click.echo(f"Runs completed: {updated['runs_completed']}")
        if patch.get("key_learnings"):
            click.echo(f"New learnings added: {len(patch['key_learnings'])}")
        if patch.get("avoid_sources"):
            click.echo(f"Avoid sources now: {len(updated['avoid_sources'])} total")
        if patch.get("recommended_next_searches"):
            click.echo("Next run direction updated.")


if __name__ == "__main__":
    main()
