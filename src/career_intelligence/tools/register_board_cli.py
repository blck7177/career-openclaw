"""
CLI adapter for career_register_board wrapper.

Adds or updates a company entry in configs/company_boards.yaml.
This is the ONLY sanctioned way for the agent to write to company_boards.yaml.

Usage:
  python -m career_intelligence.tools.register_board_cli \\
    --slug schonfeld \\
    --source greenhouse \\
    --board-token schonfeld \\
    --status active \\
    --verified-at 2026-06-10 \\
    --notes "Verified via Greenhouse boards API"

Merge rules:
  - If the slug already exists, only fields explicitly passed are updated.
  - `verified_at` is only overwritten if the new value is more recent.
  - `status` is always overwritten (the caller has just verified the source).
  - Existing fields not mentioned in the call are left unchanged.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BOARDS_PATH = WORKSPACE_ROOT / "configs" / "company_boards.yaml"

VALID_SOURCES = {"greenhouse", "lever", "ashby", "workday", "html"}
VALID_STATUSES = {"active", "best_effort", "hard_source", "unknown"}

# Fields the agent is allowed to set / update via this tool
_AGENT_WRITABLE_FIELDS = {
    "source", "board_token", "board_url", "tenant", "host",
    "status", "verified_at", "notes",
}


def _load_boards() -> dict:
    if not BOARDS_PATH.exists():
        return {}
    with open(BOARDS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_boards(boards: dict) -> None:
    # Preserve the human header comment
    header = (
        "# Human-owned config. Do not modify via agent.\n"
        "# Agent-discovered entries are added via career_register_board wrapper.\n"
        "# Last updated: auto\n"
        "#\n"
        "# status values:\n"
        "#   active      — connector verified, regularly synced\n"
        "#   best_effort — connector available but success not guaranteed\n"
        "#   hard_source — known bot protection / auth gate; use search aggregator only\n"
        "#   unknown     — not yet verified\n\n"
    )
    # Group entries by their existing section comment structure is lost after yaml.safe_load,
    # so we just dump cleanly. Sections can be maintained manually by humans.
    with open(BOARDS_PATH, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.dump(boards, f, allow_unicode=True, default_flow_style=False, sort_keys=True)


def _is_more_recent(new_date: str, existing_date: str | None) -> bool:
    """Return True if new_date >= existing_date (or existing_date is absent)."""
    if not existing_date:
        return True
    try:
        return date.fromisoformat(new_date) >= date.fromisoformat(existing_date)
    except ValueError:
        return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register or update a company ATS board in company_boards.yaml"
    )
    parser.add_argument("--slug", required=True,
                        help="Company identifier key (snake_case, e.g. jane_street)")
    parser.add_argument("--source", required=True, choices=sorted(VALID_SOURCES),
                        help="ATS platform type")
    parser.add_argument("--board-token",
                        help="Board token / slug for Greenhouse, Lever, Ashby")
    parser.add_argument("--board-url",
                        help="Direct board URL for html-type sources")
    parser.add_argument("--tenant",
                        help="Tenant name for Workday sources")
    parser.add_argument("--host",
                        help="Hostname for Workday sources (e.g. gs.wd5.myworkdayjobs.com)")
    parser.add_argument("--status", required=True, choices=sorted(VALID_STATUSES),
                        help="Verification status")
    parser.add_argument("--verified-at",
                        help="Verification date in YYYY-MM-DD format (defaults to today)")
    parser.add_argument("--notes",
                        help="Human/agent-readable notes about this board")
    parser.add_argument("--output-format", default="summary",
                        choices=["json", "summary"])
    args = parser.parse_args()

    # Validate slug format
    if not re.match(r"^[a-z][a-z0-9_]*$", args.slug):
        print(json.dumps({"error": f"Invalid slug '{args.slug}'. Must be snake_case (a-z, 0-9, _)."}))
        sys.exit(1)

    # Validate source-specific required fields
    if args.source in {"greenhouse", "lever", "ashby"} and not args.board_token:
        print(json.dumps({"error": f"--board-token is required for source '{args.source}'"}))
        sys.exit(1)
    if args.source == "workday" and not (args.tenant or args.host):
        print(json.dumps({"error": "Workday source requires --tenant and/or --host"}))
        sys.exit(1)
    if args.source == "html" and not args.board_url:
        print(json.dumps({"error": "--board-url is required for source 'html'"}))
        sys.exit(1)

    # Default verified_at to today
    verified_at = args.verified_at or date.today().isoformat()
    try:
        date.fromisoformat(verified_at)
    except ValueError:
        print(json.dumps({"error": f"Invalid --verified-at date: '{verified_at}'. Use YYYY-MM-DD."}))
        sys.exit(1)

    boards = _load_boards()
    existing = boards.get(args.slug, {})
    action = "updated" if args.slug in boards else "created"

    # Build the updated entry by merging on top of existing
    entry: dict = dict(existing)
    entry["source"] = args.source
    entry["status"] = args.status

    if args.board_token:
        entry["board_token"] = args.board_token
    if args.board_url:
        entry["board_url"] = args.board_url
    if args.tenant:
        entry["tenant"] = args.tenant
    if args.host:
        entry["host"] = args.host
    if args.notes:
        entry["notes"] = args.notes

    # Only advance verified_at, never roll it back
    if _is_more_recent(verified_at, existing.get("verified_at")):
        entry["verified_at"] = verified_at

    boards[args.slug] = entry
    _save_boards(boards)

    result = {
        "action": action,
        "slug": args.slug,
        "entry": entry,
        "boards_file": str(BOARDS_PATH),
    }

    if args.output_format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Board {action}: {args.slug} ({args.source}, status={args.status})")
        print(f"  verified_at: {entry.get('verified_at')}")
        if entry.get("board_token"):
            print(f"  board_token: {entry['board_token']}")
        if entry.get("notes"):
            print(f"  notes: {entry['notes']}")
        print(f"  File: {BOARDS_PATH}")


if __name__ == "__main__":
    main()
