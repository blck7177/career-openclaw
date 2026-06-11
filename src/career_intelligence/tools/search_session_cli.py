"""CLI adapter for search_session.py — career_search_session wrapper."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from career_intelligence.search_session import (
    end_session,
    get_session_status,
    log_candidates,
    log_query,
    log_query_expansion,
    start_session,
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]  # src/../../../..


def _print_json(data: dict) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))


@click.group()
def main() -> None:
    """Manage career search sessions."""


@main.command()
@click.option("--profile", required=True, help="Search profile name from configs/search_profiles.yaml")
@click.option("--mode", default="exploratory", type=click.Choice(["exploratory", "refresh"]))
@click.option("--max-queries", default=30, type=int)
@click.option("--max-pages", default=40, type=int)
@click.option("--stop-empty", default=3, type=int)
def start(profile: str, mode: str, max_queries: int, max_pages: int, stop_empty: int) -> None:
    """Start a new search session."""
    result = start_session(
        workspace_root=WORKSPACE_ROOT,
        profile_name=profile,
        mode=mode,
        max_queries=max_queries,
        max_fetched_pages=max_pages,
        stop_on_consecutive_empty=stop_empty,
    )
    _print_json(result)


@main.command()
@click.option("--session-id", required=True, help="Session ID (timestamp string)")
def status(session_id: str) -> None:
    """Show current session coverage stats."""
    result = get_session_status(WORKSPACE_ROOT, session_id)
    _print_json(result)


@main.command("log-query")
@click.option("--session-id", required=True)
@click.option("--query-file", required=True, help="Path to JSON file with query data")
def log_query_cmd(session_id: str, query_file: str) -> None:
    """Log a web search query and its results to the search ledger."""
    qpath = Path(query_file)
    if not qpath.exists():
        click.echo(json.dumps({"error": f"query-file not found: {query_file}"}))
        sys.exit(1)
    query_data = json.loads(qpath.read_text())
    result = log_query(WORKSPACE_ROOT, session_id, query_data)
    _print_json(result)
    if result.get("budget_exceeded"):
        sys.exit(2)


@main.command("log-expansion")
@click.option("--session-id", required=True)
@click.option("--new-query", required=True)
@click.option("--derived-from-query-id", default=None)
@click.option("--derived-from-jd-url", default=None)
@click.option("--reason", required=True)
def log_expansion_cmd(
    session_id: str, new_query: str, derived_from_query_id: str | None,
    derived_from_jd_url: str | None, reason: str
) -> None:
    """Log a query expansion event."""
    result = log_query_expansion(WORKSPACE_ROOT, session_id, {
        "new_query": new_query,
        "derived_from_query_id": derived_from_query_id,
        "derived_from_jd_url": derived_from_jd_url,
        "reason": reason,
    })
    _print_json(result)


@main.command("end")
@click.option("--session-id", required=True)
@click.option("--coverage-report", required=True, help="Path to coverage_report.md written by agent")
def end_cmd(session_id: str, coverage_report: str) -> None:
    """End a search session (requires coverage_report.md)."""
    result = end_session(WORKSPACE_ROOT, session_id, coverage_report)
    _print_json(result)
    if result.get("error"):
        sys.exit(1)

if __name__ == "__main__":
    main()
