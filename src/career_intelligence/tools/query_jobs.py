"""CLI adapter for storage_jsonl.py — career_query_jobs wrapper."""

from __future__ import annotations

import json
from pathlib import Path

import click

from career_intelligence.app_state.context import DEV_CTX
from career_intelligence.app_state.workspace_paths import get_workspace_paths

WORKSPACE_ROOT = get_workspace_paths(DEV_CTX.workspace_id).root


@click.command()
@click.option("--workstream", default=None, help='Filter by workstream (e.g. "Market Risk")')
@click.option("--company", default=None, help="Filter by company name (partial match)")
@click.option("--since", default=None, help="Filter by date (YYYY-MM-DD)")
@click.option("--limit", default=50, type=int)
@click.option("--format", "fmt", default="jsonl", type=click.Choice(["jsonl", "summary"]))
def main(workstream: str | None, company: str | None, since: str | None, limit: int, fmt: str) -> None:
    """Query the job intelligence database."""
    from career_intelligence.storage_jsonl import query_jobs

    results = query_jobs(
        db_dir=WORKSPACE_ROOT / "db",
        workstream=workstream,
        company=company,
        since=since,
        limit=limit,
    )

    if fmt == "summary":
        click.echo(f"Found {len(results)} jobs")
        for r in results:
            ws = r.get("primary_workstream", "?")
            conf = r.get("classification_confidence", "?")
            click.echo(f"  [{ws}] ({conf}) {r.get('title')} @ {r.get('company')} — {r.get('location')} ({r.get('date_found')})")
    else:
        for r in results:
            click.echo(json.dumps(r, ensure_ascii=False))

if __name__ == "__main__":
    main()
