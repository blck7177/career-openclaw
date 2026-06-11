"""CLI adapter — career_prepare_research wrapper.

Generates targeted research plans for jobs from a completed discovery run.
Each plan contains JD-guided search queries for the agent to execute via
web_search / web_fetch before running career_analyze_roles.

Prerequisites:
  - career_run_discovery must have completed (jobs_structured.json exists)

Query generation strategy (three-tier):
  1. High priority: company + division_or_business_line  (if field is populated)
  2. Medium priority: company + top finance_domains
  3. Low priority (fallback): company + cleaned title keywords

When division_or_business_line is empty, a small LLM call extracts the most
search-relevant org name from inferred_team_context before falling back.

Skip logic:
  - Jobs with an existing research_notes/<job_id>.md are skipped (idempotent).
  - Pass --force to regenerate plans for all eligible jobs.

Outputs (written to runs/<run_id>/):
  role_research_plans/<job_id>.json   Per-job research plan with queries + gaps
  role_research_tasks.jsonl           Flat list of all search tasks (agent-readable)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]

_TITLE_NOISE_WORDS = frozenset({
    "senior", "sr", "junior", "jr", "lead", "staff", "principal", "associate",
    "assistant", "head", "vp", "director", "managing", "executive", "manager",
    "officer", "specialist", "analyst", "engineer", "developer", "consultant",
    "f/m/d", "f/m", "m/f/d",
})

_ORG_EXTRACT_SYSTEM = (
    "You are a concise data extractor. Extract the single most search-useful "
    "organizational unit name from the provided team context sentence. "
    "Return ONLY the name as a plain string — no quotes, no explanation. "
    "If no useful org name is present, return an empty string."
)


def _clean_title_keywords(title: str) -> list[str]:
    """Return meaningful words from a job title, dropping noise words."""
    words = re.split(r"[\s,/\-()]+", title.lower())
    return [w for w in words if w and w not in _TITLE_NOISE_WORDS and len(w) > 2]


def _extract_org_name_via_llm(inferred_team_context: str, llm_client) -> str:
    """Use a minimal LLM call to pull the best org/team name from free text."""
    if not inferred_team_context.strip():
        return ""
    try:
        result = llm_client.call(
            system=_ORG_EXTRACT_SYSTEM,
            user=f"Team context: {inferred_team_context[:400]}",
            max_tokens=40,
        ).strip().strip('"').strip("'")
        # Reject suspiciously long results (hallucination guard)
        return result if len(result) <= 80 else ""
    except Exception:
        return ""


def _build_queries(job: dict, org_name: str) -> list[dict]:
    """Build prioritised search queries from job_record fields."""
    company = job.get("company", "").strip()
    title = job.get("title", "").strip()
    finance_domains = [d for d in job.get("finance_domains", []) if d]
    queries: list[dict] = []

    # High priority: company + explicit org name
    if org_name:
        queries.append({
            "query": f'"{company}" "{org_name}"',
            "purpose": f"Understand what {org_name} covers within {company}",
            "priority": "high",
            "derived_from": "division_or_business_line" if job.get("division_or_business_line") else "inferred_team_context_llm",
        })

    # Medium priority: company + top domain terms
    if finance_domains:
        top_domains = finance_domains[:3]
        domain_part = " ".join(f'"{d}"' for d in top_domains)
        queries.append({
            "query": f'"{company}" {domain_part}',
            "purpose": f"Confirm {company}'s scope in these domains",
            "priority": "medium",
            "derived_from": "finance_domains",
        })

    # Low priority: company + cleaned title keywords (always present as fallback)
    kw = _clean_title_keywords(title)
    if kw:
        kw_part = " ".join(f'"{w}"' for w in kw[:3])
        queries.append({
            "query": f'"{company}" {kw_part}',
            "purpose": f"Locate {company} team/role context for this position type",
            "priority": "low",
            "derived_from": "title_keywords",
        })

    return queries


def _build_context_gaps(job: dict) -> list[str]:
    """Derive research context gaps from job_record signals."""
    gaps: list[str] = []
    conf = job.get("classification_confidence", "")
    if conf in ("medium", "low"):
        gaps.append(
            "Workstream classification confidence is not high — research may clarify "
            "whether this role is analytics/risk/ops/engineering focused."
        )
    team_ctx = job.get("inferred_team_context", "")
    uncertainty_markers = ("appears to be", "likely", "possibly", "unclear", "uncertain")
    if any(m in team_ctx.lower() for m in uncertainty_markers):
        gaps.append("Team context contains uncertain language — confirm actual team scope.")
    if not job.get("division_or_business_line"):
        gaps.append(
            "JD did not explicitly name a division or business line — "
            "research should identify the team's place in the org."
        )
    return gaps


def _build_avoid_queries(job: dict, org_name: str) -> list[str]:
    """Return generic queries that should be avoided when targeted ones exist."""
    company = job.get("company", "")
    avoid = []
    if org_name:
        avoid.append(f'"{company}" company overview')
        avoid.append(f'"{company}" about us')
    return avoid


def _research_notes_exist(run_dir: Path, job_id: str) -> bool:
    return (run_dir / "research_notes" / f"{job_id}.md").exists()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@click.command()
@click.option("--run-id", required=True, help="Run ID to prepare research for.")
@click.option("--limit", default=None, type=int, help="Max number of jobs to process.")
@click.option("--job-ids", default=None, help="Comma-separated job IDs to process.")
@click.option("--force", is_flag=True, default=False,
              help="Regenerate plans even if research_notes already exist.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print what would be generated without writing files.")
def main(
    run_id: str,
    limit: int | None,
    job_ids: str | None,
    force: bool,
    dry_run: bool,
) -> None:
    """Generate targeted research plans for jobs from a completed discovery run."""
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

    eligible = [
        j for j in all_jobs
        if j.get("fetch_status") in ("success", "partial_success")
    ]

    if job_ids:
        requested = set(job_ids.split(","))
        eligible = [j for j in eligible if j.get("job_id") in requested]

    if limit and not job_ids:
        eligible = eligible[:limit]

    # Initialise LLM client (needed for org-name extraction fallback)
    from career_intelligence.llm_client import make_client  # type: ignore
    llm_client = make_client()
    if llm_client is None:
        click.echo(
            json.dumps({"warning": "No LLM client available — org name extraction fallback disabled."}),
            err=True,
        )

    plans_dir = run_dir / "role_research_plans"
    tasks_path = run_dir / "role_research_tasks.jsonl"

    if not dry_run:
        plans_dir.mkdir(exist_ok=True)

    stats = {"total": len(eligible), "planned": 0, "skipped": 0}
    all_tasks: list[dict] = []

    for job in eligible:
        job_id = job["job_id"]
        title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")

        if not force and _research_notes_exist(run_dir, job_id):
            click.echo(f"[SKIP] {job_id}: research_notes already exist", err=True)
            stats["skipped"] += 1
            continue

        # Resolve best org name for targeted queries
        org_name = (job.get("division_or_business_line") or "").strip()
        org_source = "division_or_business_line"
        if not org_name and llm_client is not None:
            team_ctx = job.get("inferred_team_context", "")
            if team_ctx.strip():
                org_name = _extract_org_name_via_llm(team_ctx, llm_client)
                org_source = "inferred_team_context_llm"

        queries = _build_queries(job, org_name)
        context_gaps = _build_context_gaps(job)
        avoid_queries = _build_avoid_queries(job, org_name)

        plan = {
            "job_id": job_id,
            "run_id": run_id,
            "title": title,
            "company": company,
            "division_or_business_line": job.get("division_or_business_line", ""),
            "org_name_used": org_name,
            "org_name_source": org_source if org_name else "none",
            "generated_at": _now_iso(),
            "search_queries": queries,
            "context_gaps": context_gaps,
            "avoid_queries": avoid_queries,
            "research_notes_target": f"runs/{run_id}/research_notes/{job_id}.md",
        }

        if dry_run:
            click.echo(json.dumps(plan, indent=2))
        else:
            plan_path = plans_dir / f"{job_id}.json"
            plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

            for q in queries:
                all_tasks.append({
                    "job_id": job_id,
                    "run_id": run_id,
                    "title": title,
                    "company": company,
                    "query": q["query"],
                    "purpose": q["purpose"],
                    "priority": q["priority"],
                    "research_notes_target": plan["research_notes_target"],
                })

            click.echo(f"[OK] {job_id}: {len(queries)} queries ({org_source})", err=True)

        stats["planned"] += 1

    if not dry_run and all_tasks:
        mode = "w" if not tasks_path.exists() else "a"
        with open(tasks_path, mode, encoding="utf-8") as f:
            for task in all_tasks:
                f.write(json.dumps(task, ensure_ascii=False) + "\n")

    click.echo(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
