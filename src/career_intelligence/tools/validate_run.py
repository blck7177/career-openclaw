"""CLI adapter for validator.py — career_validate_run wrapper."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from career_intelligence.app_state.context import DEV_CTX
from career_intelligence.app_state.workspace_paths import get_repo_root, get_workspace_paths

REPO_ROOT = get_repo_root()
WORKSPACE_ROOT = get_workspace_paths(DEV_CTX.workspace_id).root


@click.command()
@click.option("--run-id", required=True, help="Run ID (session timestamp)")
@click.option("--format", "fmt", default="text", type=click.Choice(["json", "text"]))
def main(run_id: str, fmt: str) -> None:
    """Validate all structured records from a run against the job_record schema."""
    from career_intelligence.validator import validate_record

    run_dir = WORKSPACE_ROOT / "runs" / run_id
    jobs_file = run_dir / "jobs_structured.json"

    if not jobs_file.exists():
        click.echo(json.dumps({"error": f"jobs_structured.json not found for run {run_id}"}))
        sys.exit(1)

    with open(jobs_file) as f:
        records = json.load(f)

    results = []
    all_passed = True
    for record in records:
        vr = validate_record(record, REPO_ROOT)
        results.append({
            "job_id": record.get("job_id"),
            "title": record.get("title"),
            "company": record.get("company"),
            "passed": vr.passed,
            "errors": vr.errors,
        })
        if not vr.passed:
            all_passed = False

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    if fmt == "json":
        click.echo(json.dumps({"run_id": run_id, "total": total, "passed": passed, "failed": failed, "results": results}, indent=2))
    else:
        click.echo(f"Run: {run_id}")
        click.echo(f"Total: {total} | Passed: {passed} | Failed: {failed}")
        click.echo("")
        for r in results:
            status = "PASS" if r["passed"] else "FAIL"
            click.echo(f"  [{status}] {r['job_id']} — {r['title']} @ {r['company']}")
            for err in r.get("errors", []):
                click.echo(f"         • {err}")

    sys.exit(0 if all_passed else 1)

if __name__ == "__main__":
    main()
