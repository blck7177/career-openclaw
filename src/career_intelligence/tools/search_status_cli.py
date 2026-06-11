"""CLI adapter — career_search_status wrapper."""

from __future__ import annotations

import json
from pathlib import Path

import click

from career_intelligence.search_session import get_session_status

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


@click.command()
@click.option("--session-id", required=True)
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "text"]))
def main(session_id: str, fmt: str) -> None:
    """Show session coverage statistics."""
    result = get_session_status(WORKSPACE_ROOT, session_id)
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
