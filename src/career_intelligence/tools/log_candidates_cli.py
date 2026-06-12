"""CLI adapter — career_log_candidates wrapper."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from career_intelligence.search_session import log_candidates

from career_intelligence.app_state.context import DEV_CTX
from career_intelligence.app_state.workspace_paths import get_workspace_paths
WORKSPACE_ROOT = get_workspace_paths(DEV_CTX.workspace_id).root


@click.command()
@click.option("--session-id", required=True)
@click.option("--candidates-file", default=None, help="JSON file with list of candidate objects")
@click.option("--url", default=None, help="Single candidate URL")
@click.option("--title", default="")
@click.option("--company", default="")
@click.option("--location", default="")
@click.option("--relevance", default="relevant", type=click.Choice(["relevant", "maybe"]))
@click.option("--reason", default="")
@click.option("--query-id", default="")
@click.option("--workstream-hint", default="")
def main(
    session_id: str,
    candidates_file: str | None,
    url: str | None,
    title: str,
    company: str,
    location: str,
    relevance: str,
    reason: str,
    query_id: str,
    workstream_hint: str,
) -> None:
    """Log triaged job candidates to the candidate pool."""
    if candidates_file:
        cpath = Path(candidates_file)
        if not cpath.exists():
            click.echo(json.dumps({"error": f"candidates-file not found: {candidates_file}"}))
            sys.exit(1)
        candidates = json.loads(cpath.read_text())
        if not isinstance(candidates, list):
            candidates = [candidates]
    elif url:
        candidates = [{
            "url": url,
            "title": title,
            "company": company,
            "location": location,
            "relevance": relevance,
            "relevance_reason": reason,
            "source_query_id": query_id,
            "workstream_hint": workstream_hint,
        }]
    else:
        click.echo(json.dumps({"error": "Provide --candidates-file or --url"}))
        sys.exit(1)

    result = log_candidates(WORKSPACE_ROOT, session_id, candidates)
    click.echo(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
