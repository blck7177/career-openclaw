"""CLI adapter — career_search_status wrapper."""

from __future__ import annotations

import json

import click

from career_intelligence.search_session import get_session_status

from career_intelligence.app_state.workspace_paths import resolve_workspace_root


@click.command()
@click.option("--session-id", required=True)
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "text"]))
@click.option(
    "--workspace-id",
    default=None,
    help=(
        "Workspace to operate in. Defaults to the catalog workspace "
        "(CATALOG_WORKSPACE_ID, else dev_default). Pass the workspace_id from "
        "your task spec when the platform created the session."
    ),
)
def main(session_id: str, fmt: str, workspace_id: str | None) -> None:
    """Show session coverage statistics."""
    result = get_session_status(resolve_workspace_root(workspace_id), session_id)
    if fmt == "text":
        click.echo(f"Session: {result.get('session_id')}")
        click.echo(f"Queries run:      {result.get('queries_run', 0)}")
        click.echo(f"URLs seen:        {result.get('urls_seen', 0)}")
        click.echo(f"Pages fetched:    {result.get('urls_fetched', 0)}")
        click.echo(f"Candidates:       {result.get('candidates_captured', 0)} (relevant: {result.get('candidates_relevant', 0)}, maybe: {result.get('candidates_maybe', 0)})")
        click.echo(f"Skipped:          {result.get('candidates_skipped', 0)}")
        budget = result.get("budget_used", {})
        click.echo(f"Budget remaining: {budget.get('queries_remaining', '?')} queries, {budget.get('fetches_remaining', '?')} fetches")
    else:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
