"""Stage 2 minimal-budget REAL discovery smoke test.

Runs one full discovery session (search -> validate -> process -> reflect) with a
tiny budget, then prints the gateway-parsed tool_calls so we can confirm the
provenance fix: real web_search/web_fetch from the session jsonl, no schema
pollution from meta.systemPromptReport.

Run from repo root:
    .venv/bin/python scripts/stage2_smoke_discovery.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

# --- Minimal budget: keep this cheap. Overridable via env. ---
os.environ.setdefault("AGENT_RUN_MAX_TURNS", "4")
os.environ.setdefault("AGENT_TURN_TIMEOUT_S", "150")
os.environ.setdefault("AGENT_RUN_WALL_CLOCK_S", "600")
os.environ.setdefault("AGENT_REFLECT_MAX_TURNS", "2")

from career_intelligence.app_state.workspace_paths import (  # noqa: E402
    get_catalog_workspace_id,
    get_workspace_paths,
)
from career_intelligence.search_session import session_dir  # noqa: E402
from career_intelligence.services.agent_service import (  # noqa: E402
    AgentRunError,
    SearchValidationError,
    run_discovery_session,
)


def _banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> None:
    profile_name = os.environ.get("STAGE2_PROFILE", "market_risk_nyc")
    search_brief = os.environ.get(
        "STAGE2_BRIEF",
        "Entry/associate-level market risk and valuation control roles in NYC; "
        "find 1-2 real job postings with direct application URLs.",
    )
    max_queries = int(os.environ.get("STAGE2_MAX_QUERIES", "3"))
    max_pages = int(os.environ.get("STAGE2_MAX_PAGES", "4"))

    _banner("STAGE 2 REAL DISCOVERY — minimal budget")
    print(f"profile      : {profile_name}")
    print(f"brief        : {search_brief}")
    print(f"max_queries  : {max_queries}")
    print(f"max_pages    : {max_pages}")
    print(f"max_turns    : {os.environ['AGENT_RUN_MAX_TURNS']}")
    print(f"wall_clock_s : {os.environ['AGENT_RUN_WALL_CLOCK_S']}")

    try:
        result = run_discovery_session(
            profile_name=profile_name,
            search_brief=search_brief,
            max_queries=max_queries,
            max_pages=max_pages,
        )
    except SearchValidationError as exc:
        _banner("RESULT: SearchValidationError (fabrication gate fired)")
        print(exc)
        return
    except AgentRunError as exc:
        _banner("RESULT: AgentRunError")
        print(exc)
        return

    _banner("DISCOVERY RESULT SUMMARY")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # --- Inspect the run log to verify the provenance fix ---
    catalog_id = get_catalog_workspace_id()
    workspace_root = get_workspace_paths(catalog_id).root
    session_root = session_dir(workspace_root, result["session_id"])
    run_log = session_root / "agent_run_log.json"

    _banner("GATEWAY-PARSED TOOL CALLS (provenance ground truth)")
    if not run_log.exists():
        print(f"!! run log missing: {run_log}")
        return
    log = json.loads(run_log.read_text(encoding="utf-8"))
    tool_calls = log.get("tool_calls", [])
    web_search = [tc for tc in tool_calls if tc.get("tool") == "web_search"]
    web_fetch = [tc for tc in tool_calls if tc.get("tool") == "web_fetch"]
    print(f"run log      : {run_log}")
    print(f"turns_used   : {log.get('turns_used')}")
    print(f"status       : {log.get('status')}")
    print(f"tool_calls   : {len(tool_calls)} total")
    print(f"  web_search : {len(web_search)}")
    print(f"  web_fetch  : {len(web_fetch)}  (with URL: "
          f"{sum(1 for tc in web_fetch if tc.get('url'))})")
    print(json.dumps(tool_calls, indent=2, ensure_ascii=False))

    _banner("PROVENANCE SANITY CHECK")
    # Bug signature would be: exactly 1 phantom web_search + 1 phantom web_fetch
    # (the schema entries) with empty URLs and no corresponding queries_run.
    phantom_fetch = [tc for tc in web_fetch if not tc.get("url")]
    if phantom_fetch:
        print(f"WARNING: {len(phantom_fetch)} web_fetch entries have NO url — "
              "possible schema pollution leaking through.")
    else:
        print("OK: every web_fetch carries a real URL (no URL-less schema phantoms).")
    print(f"queries_run (ledger) : {result.get('queries_run')}")
    print(f"candidates_captured  : {result.get('candidates_captured')}")
    print(f"jobs_fetched/saved   : {result.get('jobs_fetched')}/{result.get('jobs_saved')}")


if __name__ == "__main__":
    main()
