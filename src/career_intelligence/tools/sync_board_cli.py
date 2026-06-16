"""
CLI adapter for career_sync_board wrapper.

Usage:
  python -m career_intelligence.tools.sync_board_cli \
    --source greenhouse --slug schonfeld [--session-id <id>] [--workspace-id <id>]
    [--output-format json|summary]
    [--location-filter "New York,NYC,Jersey City"]
    [--title-keywords "risk,analyst,quant,valuation"]
    [--exclude-titles "intern,engineer,marketing,recruiter,hr,legal"]
    [--dry-run]

Syncs active jobs from a company's ATS board and writes them to the
session's candidate_pool.jsonl. Client-side filters are applied before writing.

--workspace-id must match the workspace_id in the agent task spec so that
candidates land in the same workspace the worker's pipeline reads from.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from career_intelligence.app_state.workspace_paths import resolve_workspace_root


def _matches_any(text: str, terms: list[str]) -> bool:
    """Return True if any term is a substring of text (case-insensitive)."""
    t = text.lower()
    return any(term in t for term in terms)


def _filter_jobs(jobs: list, location_filter: str, title_keywords: str, exclude_titles: str) -> tuple[list, dict]:
    """
    Apply client-side filters to a list of NormalizedJob objects.

    Returns (filtered_jobs, stats) where stats reports how many were dropped by each filter.
    """
    loc_terms = [t.strip().lower() for t in location_filter.split(",") if t.strip()] if location_filter else []
    kw_terms = [t.strip().lower() for t in title_keywords.split(",") if t.strip()] if title_keywords else []
    ex_terms = [t.strip().lower() for t in exclude_titles.split(",") if t.strip()] if exclude_titles else []

    kept = []
    stats = {"dropped_location": 0, "dropped_title_no_match": 0, "dropped_title_excluded": 0}

    for job in jobs:
        loc = (job.location or "").lower()
        title = (job.title or "").lower()

        if loc_terms and not _matches_any(loc, loc_terms):
            stats["dropped_location"] += 1
            continue

        if ex_terms and _matches_any(title, ex_terms):
            stats["dropped_title_excluded"] += 1
            continue

        if kw_terms and not _matches_any(title, kw_terms):
            stats["dropped_title_no_match"] += 1
            continue

        kept.append(job)

    return kept, stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync jobs from a company's ATS board into the candidate pool"
    )
    parser.add_argument("--source", required=True,
                        choices=["greenhouse", "lever", "ashby"],
                        help="ATS source type")
    parser.add_argument("--slug", required=True,
                        help="Company slug from company_boards.yaml (e.g. schonfeld)")
    parser.add_argument("--session-id",
                        help="Search session ID. If omitted, writes to agent_work/inputs/")
    parser.add_argument("--output-format", default="summary",
                        choices=["json", "summary"],
                        help="Output format (default: summary)")
    parser.add_argument("--location-filter",
                        help='Comma-separated substrings to match against job.location (OR logic). '
                             'Example: "New York,NYC,Jersey City"')
    parser.add_argument("--title-keywords",
                        help='Comma-separated keywords; keep jobs where title matches any (OR). '
                             'Example: "risk,analyst,quant,valuation,exposure,credit"')
    parser.add_argument("--exclude-titles",
                        help='Comma-separated keywords; drop jobs where title matches any (OR). '
                             'Example: "intern,software engineer,marketing,recruiter,hr,legal"')
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview filter results without writing to candidate_pool")
    parser.add_argument(
        "--workspace-id",
        default=None,
        help=(
            "Workspace to write candidates into. Defaults to the catalog workspace "
            "(CATALOG_WORKSPACE_ID, else dev_default). Pass the workspace_id from "
            "your task spec so board_sync candidates land in the same workspace "
            "the worker's pipeline reads from."
        ),
    )
    args = parser.parse_args()

    # repo_root is used only for configs (company_boards.yaml lives in the repo).
    # candidate_pool.jsonl is written to the workspace run directory, which may
    # differ from the repo root when a non-default workspace_id is active.
    repo_root = Path(__file__).parent.parent.parent.parent
    workspace_root = resolve_workspace_root(args.workspace_id)

    from career_intelligence.connectors.connector_router import load_company_boards, sync_board

    boards_registry = load_company_boards(repo_root)

    # Validate slug
    if args.slug not in boards_registry:
        print(json.dumps({
            "error": f"Company '{args.slug}' not found in company_boards.yaml",
            "available_slugs": sorted(boards_registry.keys()),
        }, indent=2))
        sys.exit(1)

    profile = boards_registry[args.slug]
    registered_source = profile.get("source", "html")
    if registered_source != args.source:
        print(json.dumps({
            "warning": f"Requested source '{args.source}' but company_boards.yaml says '{registered_source}'. Using '{registered_source}'.",
        }))

    try:
        jobs = sync_board(args.slug, boards_registry)
    except NotImplementedError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": f"Board sync failed: {type(e).__name__}: {e}"}, indent=2))
        sys.exit(1)

    # Apply client-side filters
    total_before = len(jobs)
    if args.location_filter or args.title_keywords or args.exclude_titles:
        jobs, filter_stats = _filter_jobs(
            jobs,
            args.location_filter or "",
            args.title_keywords or "",
            args.exclude_titles or "",
        )
    else:
        filter_stats = {"dropped_location": 0, "dropped_title_no_match": 0, "dropped_title_excluded": 0}
    total_after = len(jobs)

    if args.dry_run:
        preview = {
            "dry_run": True,
            "company_slug": args.slug,
            "total_from_board": total_before,
            "would_keep": total_after,
            "would_drop": total_before - total_after,
            "filter_stats": filter_stats,
            "filters_applied": {
                "location_filter": args.location_filter,
                "title_keywords": args.title_keywords,
                "exclude_titles": args.exclude_titles,
            },
            "sample_kept": [{"title": j.title, "location": j.location} for j in jobs[:10]],
        }
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        return

    # Determine output path (always inside the workspace, not the repo root).
    if args.session_id:
        out_dir = workspace_root / "runs" / args.session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "candidate_pool.jsonl"
    else:
        out_dir = workspace_root / "agent_work" / "inputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"sync_{args.slug}.jsonl"

    # Load existing candidates to detect duplicates
    existing_urls: set[str] = set()
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        existing_urls.add(rec.get("url", "") or rec.get("source_url", ""))
                    except json.JSONDecodeError:
                        pass

    inserted = 0
    unchanged = 0
    with open(out_path, "a", encoding="utf-8") as f:
        for job in jobs:
            if job.url in existing_urls:
                unchanged += 1
                continue
            candidate = {
                "url": job.url,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "source_type": job.source_type,
                "job_external_id": job.job_external_id,
                "relevance": "maybe",
                "relevance_reason": f"board_sync:{args.slug}",
                "workstream_hint": "unknown",
            }
            f.write(json.dumps(candidate, ensure_ascii=False) + "\n")
            inserted += 1

    result = {
        "company_slug": args.slug,
        "source": registered_source,
        "jobs_from_board": total_before,
        "jobs_after_filter": total_after,
        "jobs_dropped_by_filter": total_before - total_after,
        "filter_stats": filter_stats,
        "jobs_inserted": inserted,
        "jobs_unchanged": unchanged,
        "output_file": str(out_path),
    }

    if args.output_format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Board sync complete: {args.slug} ({registered_source})")
        if total_before != total_after:
            print(f"  Jobs from board: {total_before}  →  after filter: {total_after} "
                  f"(dropped {total_before - total_after}: "
                  f"location={filter_stats['dropped_location']}, "
                  f"no_title_match={filter_stats['dropped_title_no_match']}, "
                  f"excluded={filter_stats['dropped_title_excluded']})")
        else:
            print(f"  Jobs found:     {total_before}")
        print(f"  Jobs inserted:  {inserted}")
        print(f"  Jobs unchanged: {unchanged}")
        print(f"  Output file:    {out_path}")


if __name__ == "__main__":
    main()
