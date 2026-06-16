"""CLI adapter for search_session.py — career_search_session wrapper."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from career_intelligence.app_state.context import DEV_CTX
from career_intelligence.app_state.workspace_paths import get_workspace_paths
from career_intelligence.search_session import (
    end_session,
    get_session_status,
    log_candidates,
    log_query,
    log_query_expansion,
    start_session,
)

WORKSPACE_ROOT = get_workspace_paths(DEV_CTX.workspace_id).root


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
@click.option(
    "--session-id",
    default=None,
    help=(
        "Reuse an existing caller-created session id instead of generating a "
        "new one. When the platform has already created the session, pass it "
        "here; start becomes idempotent and will not clobber existing state."
    ),
)
def start(
    profile: str, mode: str, max_queries: int, max_pages: int,
    stop_empty: int, session_id: str | None,
) -> None:
    """Start a new search session (or reuse one when --session-id is given)."""
    result = start_session(
        workspace_root=WORKSPACE_ROOT,
        profile_name=profile,
        mode=mode,
        max_queries=max_queries,
        max_fetched_pages=max_pages,
        stop_on_consecutive_empty=stop_empty,
        session_id=session_id,
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
@click.option(
    "--query-file",
    default=None,
    help="Path to JSON file with rich query data (use this when you want results_seen, etc.)",
)
@click.option(
    "--query-text",
    default=None,
    help="Inline query string actually searched (one-shot alternative to --query-file)",
)
@click.option(
    "--source-type",
    default=None,
    help="company_career_page | ats_board | aggregator | recruiter_post | unknown",
)
@click.option("--query-family", default=None, help="Query family label (from profile keywords)")
@click.option("--valid-url-count", default=None, type=int, help="How many results were real JD URLs")
@click.option("--candidate-yield", default=None, type=int, help="How many candidates this query added")
@click.option(
    "--failure-mode",
    "observed_failure_mode",
    default=None,
    help="none | blocked_403 | no_results | fake_urls | search_result_pages_only | other",
)
def log_query_cmd(
    session_id: str,
    query_file: str | None,
    query_text: str | None,
    source_type: str | None,
    query_family: str | None,
    valid_url_count: int | None,
    candidate_yield: int | None,
    observed_failure_mode: str | None,
) -> None:
    """Log a web search query to the ledger (inline via --query-text, or rich JSON via --query-file)."""
    if query_file:
        qpath = Path(query_file)
        if not qpath.exists():
            click.echo(json.dumps({"error": f"query-file not found: {query_file}"}))
            sys.exit(1)
        query_data = json.loads(qpath.read_text())
    elif query_text:
        query_data = {"query_text": query_text}
        for key, val in (
            ("source_type", source_type),
            ("query_family", query_family),
            ("valid_url_count", valid_url_count),
            ("candidate_yield", candidate_yield),
            ("observed_failure_mode", observed_failure_mode),
        ):
            if val is not None:
                query_data[key] = val
    else:
        click.echo(json.dumps({"error": "Provide --query-text (inline) or --query-file (JSON)"}))
        sys.exit(1)

    result = log_query(WORKSPACE_ROOT, session_id, query_data)
    _print_json(result)
    if result.get("error"):
        sys.exit(1)
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
