"""CLI adapter — career_analyze_roles wrapper.

Runs two-layer role dossier analysis on jobs from a completed discovery run.

Prerequisites:
  - career_run_discovery must have completed for the run (jobs_structured.json + raw_jds/ exist)
  - OPENAI_API_KEY or ANTHROPIC_API_KEY must be set in .env

Outputs (written to runs/<run_id>/):
  - role_dossier_reports/<job_id>.md   Layer 1 narrative report per job
  - role_dossiers.jsonl                Layer 2 structured dossiers (append mode)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
ANALYSIS_VERSION = "0.1.0"


@click.command()
@click.option("--run-id", required=True, help="Run ID to analyze (e.g. 2026-06-10_215935).")
@click.option("--limit", default=None, type=int, help="Max number of jobs to analyze.")
@click.option("--job-ids", default=None, help="Comma-separated job IDs to analyze (overrides --limit).")
@click.option("--dry-run", is_flag=True, default=False, help="List eligible jobs without running analysis.")
def main(run_id: str, limit: int | None, job_ids: str | None, dry_run: bool) -> None:
    """Generate Role Dossier reports for jobs from a completed discovery run."""
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(WORKSPACE_ROOT / ".env")

    run_dir = WORKSPACE_ROOT / "runs" / run_id
    if not run_dir.exists():
        click.echo(json.dumps({"error": f"Run directory not found: {run_dir}"}))
        sys.exit(1)

    jobs_file = run_dir / "jobs_structured.json"
    if not jobs_file.exists():
        click.echo(json.dumps({
            "error": f"jobs_structured.json not found in {run_id}. Run career_run_discovery first."
        }))
        sys.exit(1)

    with open(jobs_file, encoding="utf-8") as f:
        all_jobs = json.load(f)

    # Select eligible jobs (must have been fetched successfully and have a raw JD on disk)
    eligible = [
        j for j in all_jobs
        if j.get("fetch_status") in ("success", "partial_success")
        and _raw_jd_path(j).exists()
    ]

    # Apply filters
    if job_ids:
        requested = set(job_ids.split(","))
        selected = [j for j in eligible if j.get("job_id") in requested]
        missing = requested - {j["job_id"] for j in selected}
        if missing:
            click.echo(
                json.dumps({"warning": f"Job IDs not found or not eligible: {sorted(missing)}"}),
                err=True,
            )
    else:
        selected = eligible

    if limit and not job_ids:
        selected = selected[:limit]

    if dry_run:
        click.echo(json.dumps({
            "would_analyze": len(selected),
            "job_ids": [j["job_id"] for j in selected],
        }, indent=2))
        return

    if not selected:
        click.echo(json.dumps({"error": "No eligible jobs found for this run."}))
        sys.exit(1)

    # LLM client
    from career_intelligence.llm_client import make_client  # type: ignore
    llm_client = make_client()
    if llm_client is None:
        click.echo(json.dumps({"error": "No LLM client available. Check OPENAI_API_KEY or ANTHROPIC_API_KEY in .env."}))
        sys.exit(1)

    # Taxonomy
    taxonomy_path = WORKSPACE_ROOT / "configs" / "workstream_taxonomy.yaml"
    with open(taxonomy_path, encoding="utf-8") as f:
        taxonomy_data = yaml.safe_load(f)
    taxonomy = taxonomy_data.get("workstreams", [])

    # Output dirs / files
    reports_dir = run_dir / "role_dossier_reports"
    reports_dir.mkdir(exist_ok=True)
    dossiers_path = run_dir / "role_dossiers.jsonl"

    stats = {"total": len(selected), "succeeded": 0, "failed": 0, "skipped": 0}

    from career_intelligence.role_analyzer import analyze_role  # type: ignore

    for job in selected:
        job_id = job["job_id"]
        title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")

        # Skip if dossier already exists for this job in this run
        if _dossier_exists(dossiers_path, job_id):
            click.echo(f"[SKIP] {job_id}: dossier already exists", err=True)
            stats["skipped"] += 1
            continue

        click.echo(f"[ANALYZING] {job_id}: {title} @ {company}", err=True)

        try:
            jd_text = _raw_jd_path(job).read_text(encoding="utf-8")

            report_md, dossier = analyze_role(
                jd_text=jd_text,
                job_record=job,
                taxonomy=taxonomy,
                llm_client=llm_client,
            )

            # Write Layer 1 report
            report_path = reports_dir / f"{job_id}.md"
            report_path.write_text(report_md, encoding="utf-8")

            # Assemble Layer 2 record with metadata
            dossier_record = {
                "job_id": job_id,
                "run_id": run_id,
                "analysis_version": ANALYSIS_VERSION,
                "analyzed_at": _now_iso(),
                "title": title,
                "company": company,
                "source_url": job.get("source_url", ""),
                **dossier,
            }

            # Append to run's role_dossiers.jsonl
            with open(dossiers_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(dossier_record, ensure_ascii=False) + "\n")

            stats["succeeded"] += 1
            click.echo(f"[OK] {job_id}", err=True)

        except Exception as e:
            click.echo(f"[FAIL] {job_id}: {e}", err=True)
            stats["failed"] += 1

    click.echo(json.dumps(stats, indent=2))
    if stats["failed"] > 0 and stats["succeeded"] == 0:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_jd_path(job: dict) -> Path:
    raw_path = job.get("raw_jd_path", "")
    if raw_path:
        # raw_jd_path is stored relative to workspace_root/runs/
        # e.g. "2026-06-10_055307/raw_jds/job_abc.txt"
        return WORKSPACE_ROOT / "runs" / raw_path
    return Path("/nonexistent")


def _dossier_exists(dossiers_path: Path, job_id: str) -> bool:
    if not dossiers_path.exists():
        return False
    with open(dossiers_path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line.strip())
                if rec.get("job_id") == job_id:
                    return True
            except json.JSONDecodeError:
                continue
    return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    main()
