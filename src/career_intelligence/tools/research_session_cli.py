"""CLI adapter for the research fetch ledger — career_research_session wrapper.

Used by career-research to record each real web_fetch into the research
fetch ledger. This is the Layer B (self-reported) signal of the anti-fabrication
gate; Layer A (tool-call ground truth, parsed by agent_gateway) takes priority.

The ledger lives alongside the research bundle artifacts at:
  data/global/research_artifacts/<job_id>/<inputs_hash>/research_fetch_ledger.jsonl
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import click

from career_intelligence.app_state.workspace_paths import get_global_paths
from career_intelligence.url_utils import url_hash


def _print_json(data: dict) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))


@click.group()
def main() -> None:
    """Manage research fetch ledger for career-research."""


@main.command("log-fetch")
@click.option("--job-id", required=True, help="Job ID the research is for.")
@click.option("--inputs-hash", required=True, help="research_inputs_hash from the task spec.")
@click.option("--url", required=True, help="URL that was fetched via web_fetch.")
@click.option("--fetch-status", default="success", help="success | failed")
def log_fetch(job_id: str, inputs_hash: str, url: str, fetch_status: str) -> None:
    """Append one fetched URL to the research fetch ledger."""
    ledger_path = get_global_paths().research_fetch_ledger(job_id, inputs_hash)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "url": url,
        "url_hash": url_hash(url),
        "fetch_status": fetch_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    _print_json({"logged": True, "url": url, "ledger": str(ledger_path)})


if __name__ == "__main__":
    main()
