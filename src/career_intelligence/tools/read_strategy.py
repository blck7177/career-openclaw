"""CLI adapter — career_read_strategy wrapper.

Call at the start of each run to load cross-run strategy state.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from career_intelligence.app_state.context import DEV_CTX
from career_intelligence.app_state.workspace_paths import get_workspace_paths
from career_intelligence.strategy_state import read_state

WORKSPACE_ROOT = get_workspace_paths(DEV_CTX.workspace_id).root


@click.command()
@click.option(
    "--format", "fmt",
    default="text",
    type=click.Choice(["json", "text"]),
    help="Output format.",
)
def main(fmt: str) -> None:
    """Read cross-run strategy state from the workspace strategy_state.json."""
    state = read_state(WORKSPACE_ROOT)

    if fmt == "json":
        click.echo(json.dumps(state, indent=2, ensure_ascii=False))
        return

    runs = state.get("runs_completed", 0)
    last_run = state.get("last_run_id") or "none"
    click.echo(f"Strategy State  (runs completed: {runs}, last run: {last_run})")
    click.echo("")

    effective_sources = state.get("effective_sources", [])
    if effective_sources:
        click.echo("Effective sources:")
        for s in effective_sources:
            click.echo(f"  + {s}")
    else:
        click.echo("Effective sources: (none recorded yet)")

    avoid_sources = state.get("avoid_sources", [])
    if avoid_sources:
        click.echo("\nAvoid sources:")
        for s in avoid_sources:
            click.echo(f"  - {s}")

    effective_queries = state.get("effective_query_patterns", [])
    if effective_queries:
        click.echo("\nEffective query patterns:")
        for q in effective_queries:
            click.echo(f"  + {q}")

    avoid_queries = state.get("avoid_query_patterns", [])
    if avoid_queries:
        click.echo("\nAvoid query patterns:")
        for q in avoid_queries:
            click.echo(f"  - {q}")

    coverage = state.get("coverage_by_workstream", {})
    if coverage:
        click.echo("\nWorkstream coverage:")
        for ws, status in coverage.items():
            click.echo(f"  {ws}: {status}")

    learnings = state.get("key_learnings", [])
    if learnings:
        click.echo("\nKey learnings:")
        for l in learnings:
            click.echo(f"  • {l}")

    next_searches = state.get("recommended_next_searches", [])
    if next_searches:
        click.echo("\nRecommended next searches:")
        for n in next_searches:
            click.echo(f"  → {n}")


if __name__ == "__main__":
    main()
