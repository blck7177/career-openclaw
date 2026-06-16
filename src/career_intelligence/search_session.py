"""
Search session state manager.

Manages the lifecycle of an agent-led search session:
- Creates and initializes run directory structure
- Maintains visited URL deduplication set
- Writes search_ledger.jsonl, candidate_pool.jsonl, skipped_results.jsonl, query_expansion_log.jsonl
- Checks search budget
- Validates coverage report before session end
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .url_utils import url_hash as _url_hash

RUNNER_VERSION = "0.1.0"

SESSION_DIR_NAMES = [
    "raw_jds",
]

# Canonical query-ledger input fields. Single source of truth shared with
# schemas/search_query.schema.json and the career_search_session log-query CLI.
# Anything outside this set is rejected (no silent splat of mistyped keys).
_KNOWN_QUERY_FIELDS = frozenset({
    "query_id",
    "query_text",
    "search_intent",
    "query_type",
    "query_family",
    "derived_from",
    "results_seen",
    "new_terms_discovered",
    "source_type",
    "observed_failure_mode",
    "valid_url_count",
    "candidate_yield",
})

# Convenience aliases an agent is likely to use for the query string. Mapped to
# the canonical key so a natural `{"query": "..."}` does not produce a malformed
# ledger entry that slips past the provenance gate.
_QUERY_FIELD_ALIASES = {
    "query": "query_text",
    "text": "query_text",
}


def _normalize_query_data(
    query_data: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """
    Map known aliases to canonical keys and collect any unknown top-level fields.

    Returns (normalized_dict, unknown_fields). The caller rejects the query when
    unknown_fields is non-empty rather than silently storing mistyped keys.
    """
    normalized: dict[str, Any] = {}
    for key, value in query_data.items():
        canonical = _QUERY_FIELD_ALIASES.get(key, key)
        normalized[canonical] = value
    unknown = sorted(set(normalized) - _KNOWN_QUERY_FIELDS)
    return normalized, unknown


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_id_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def _runs_dir(workspace_root: Path) -> Path:
    return workspace_root / "runs"


def session_dir(workspace_root: Path, session_id: str) -> Path:
    return _runs_dir(workspace_root) / session_id


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def start_session(
    workspace_root: Path,
    profile_name: str,
    mode: str = "exploratory",
    max_queries: int = 30,
    max_fetched_pages: int = 40,
    stop_on_consecutive_empty: int = 3,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Create a new search session directory and write run_config.yaml.

    session_id:
        - None (default): a fresh timestamp-based id is generated. Standalone /
          manual usage where the caller does not own an id.
        - provided: the caller (e.g. the platform agent_service) owns the
          session identity. This makes the function idempotent — if the
          directory already exists with a run_config.yaml, the existing session
          is returned unchanged (with reused=True) instead of clobbering any
          in-progress ledger/candidate state. This is what lets the platform
          pre-create a session and force the agent to reuse the same id rather
          than starting a divergent one.
    """
    if session_id is None:
        session_id = _session_id_now()
    sdir = session_dir(workspace_root, session_id)

    import yaml  # type: ignore

    rc_path = sdir / "run_config.yaml"
    if rc_path.exists():
        with open(rc_path) as f:
            existing_config = yaml.safe_load(f) or {}
        return {
            "session_id": session_id,
            "session_dir": str(sdir),
            "run_config": existing_config,
            "reused": True,
        }

    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "raw_jds").mkdir(exist_ok=True)

    run_config = {
        "session_id": session_id,
        "profile_name": profile_name,
        "mode": mode,
        "run_timestamp": _now_iso(),
        "runner_version": RUNNER_VERSION,
        "search_budget": {
            "max_queries": max_queries,
            "max_fetched_pages": max_fetched_pages,
            "stop_on_consecutive_empty": stop_on_consecutive_empty,
        },
        "status": "search_in_progress",
    }

    with open(rc_path, "w") as f:
        yaml.dump(run_config, f, default_flow_style=False, allow_unicode=True)

    return {
        "session_id": session_id,
        "session_dir": str(sdir),
        "run_config": run_config,
        "reused": False,
    }


def get_session_status(workspace_root: Path, session_id: str) -> dict[str, Any]:
    """Return current coverage statistics for a session."""
    sdir = session_dir(workspace_root, session_id)
    if not sdir.exists():
        return {"error": f"Session {session_id} not found"}

    ledger = _read_jsonl(sdir / "search_ledger.jsonl")
    candidates = _read_jsonl(sdir / "candidate_pool.jsonl")
    skipped = _read_jsonl(sdir / "skipped_results.jsonl")
    fetched = _read_jsonl(sdir / "fetched_pages.jsonl")
    expansions = _read_jsonl(sdir / "query_expansion_log.jsonl")

    urls_seen: set[str] = set()
    for entry in ledger:
        for result in entry.get("results_seen", []):
            if result.get("url"):
                urls_seen.add(result["url"])

    query_families = sorted({e.get("query_family", "") for e in ledger if e.get("query_family")})
    candidate_families = sorted({c.get("workstream_hint", "") for c in candidates if c.get("workstream_hint")})

    import yaml  # type: ignore
    rc_path = sdir / "run_config.yaml"
    budget = {}
    if rc_path.exists():
        with open(rc_path) as f:
            rc = yaml.safe_load(f)
        budget = rc.get("search_budget", {})

    return {
        "session_id": session_id,
        "queries_run": len(ledger),
        "urls_seen": len(urls_seen),
        "urls_fetched": len(fetched),
        "candidates_captured": len(candidates),
        "candidates_relevant": len([c for c in candidates if c.get("relevance") == "relevant"]),
        "candidates_maybe": len([c for c in candidates if c.get("relevance") == "maybe"]),
        "candidates_skipped": len(skipped),
        "query_expansions": len(expansions),
        "query_families_covered": query_families,
        "budget": budget,
        "budget_used": {
            "queries": len(ledger),
            "fetched_pages": len(fetched),
            "queries_remaining": max(0, budget.get("max_queries", 30) - len(ledger)),
            "fetches_remaining": max(0, budget.get("max_fetched_pages", 40) - len(fetched)),
        },
    }


def log_query(
    workspace_root: Path,
    session_id: str,
    query_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Log one search query to search_ledger.jsonl.

    query_data expected fields:
      query_id, query_text, search_intent, query_type, query_family,
      derived_from, results_seen (list), new_terms_discovered

    Observability fields (provide when known; defaults filled if omitted):
      source_type         — "company_career_page" | "ats_board" | "aggregator" |
                            "recruiter_post" | "unknown"
      observed_failure_mode — "none" | "blocked_403" | "no_results" |
                              "fake_urls" | "search_result_pages_only" | "other"
      valid_url_count     — int: how many URLs in results_seen were confirmed real JD pages
      candidate_yield     — int: how many candidates were added to pool from this query
    """
    sdir = session_dir(workspace_root, session_id)
    if not sdir.exists():
        return {"error": f"Session {session_id} not found"}

    # Normalize aliases (query -> query_text) and reject mistyped fields so a
    # malformed ledger entry cannot slip past the provenance gate.
    query_data, unknown = _normalize_query_data(query_data)
    if unknown:
        return {
            "error": (
                f"Unknown query field(s): {unknown}. "
                f"Allowed fields: {sorted(_KNOWN_QUERY_FIELDS)}."
            ),
            "unknown_fields": unknown,
        }
    if not str(query_data.get("query_text") or "").strip():
        return {
            "error": (
                "Missing required field 'query_text' (inline alias: 'query'). "
                "Log the actual search query string you ran."
            ),
        }

    status = get_session_status(workspace_root, session_id)
    budget = status.get("budget", {})
    max_queries = budget.get("max_queries", 30)
    if status["queries_run"] >= max_queries:
        return {
            "error": f"Search budget exceeded: {status['queries_run']}/{max_queries} queries used. End session and write coverage_report.",
            "budget_exceeded": True,
        }

    record = {
        "query_id": query_data.get("query_id", f"q_{status['queries_run'] + 1:03d}"),
        "timestamp": _now_iso(),
        **{k: v for k, v in query_data.items() if k != "query_id"},
    }

    for result in record.get("results_seen", []):
        if result.get("url"):
            result["url_hash"] = _url_hash(result["url"])

    # ensure observability fields always present in ledger
    for field, default in [
        ("source_type", "unknown"),
        ("observed_failure_mode", "none"),
        ("valid_url_count", None),
        ("candidate_yield", None),
    ]:
        if field not in record:
            record[field] = default

    _append_jsonl(sdir / "search_ledger.jsonl", record)

    return {"logged": True, "query_id": record["query_id"], "queries_total": status["queries_run"] + 1}


def log_fetched_page(workspace_root: Path, session_id: str, url: str, fetch_status: str = "success") -> dict[str, Any]:
    """Record that a page was fetched (for budget tracking and dedup)."""
    sdir = session_dir(workspace_root, session_id)
    if not sdir.exists():
        return {"error": f"Session {session_id} not found"}

    fetched = _read_jsonl(sdir / "fetched_pages.jsonl")
    status = get_session_status(workspace_root, session_id)
    budget = status.get("budget", {})
    max_pages = budget.get("max_fetched_pages", 40)

    if len(fetched) >= max_pages:
        return {
            "error": f"Fetch budget exceeded: {len(fetched)}/{max_pages} pages fetched.",
            "budget_exceeded": True,
        }

    already_fetched = any(e.get("url") == url for e in fetched)
    if already_fetched:
        return {"duplicate": True, "url": url, "message": "URL already fetched in this session"}

    _append_jsonl(sdir / "fetched_pages.jsonl", {
        "url": url,
        "url_hash": _url_hash(url),
        "fetch_status": fetch_status,
        "timestamp": _now_iso(),
    })
    return {"logged": True, "url": url}


def log_candidates(
    workspace_root: Path,
    session_id: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Write triaged candidates to candidate_pool.jsonl.
    Deduplicates by url_hash within the session.
    Rejects candidates with no source_url — they cannot be fetched by the pipeline.

    Provenance guard: requires at least one real web_search query to have been
    logged (via career_search_session log-query) before any candidates can be
    admitted. This prevents fabricated or memory-sourced URLs from entering the
    pool even if the agent bypasses the web_search step.
    """
    sdir = session_dir(workspace_root, session_id)
    if not sdir.exists():
        return {"error": f"Session {session_id} not found"}

    # Provenance gate: candidate pool is only writable after at least one real
    # web_search has been recorded in the search ledger.
    ledger = _read_jsonl(sdir / "search_ledger.jsonl")
    if not ledger:
        return {
            "error": (
                "Provenance violation: search_ledger is empty (queries_run=0). "
                "You must call web_search and career_search_session log-query "
                "before logging candidates. Memory-sourced or fabricated URLs "
                "are not permitted."
            ),
            "queries_run": 0,
            "candidates_rejected": len(candidates),
            "action_required": (
                "Execute web_search → career_search_session log-query first, "
                "then re-submit candidates."
            ),
        }

    existing = _read_jsonl(sdir / "candidate_pool.jsonl")
    existing_hashes = {e.get("url_hash") for e in existing}

    added = []
    duplicates = []
    rejected_no_url = []
    for cand in candidates:
        url = (cand.get("url") or cand.get("source_url") or "").strip()
        if not url:
            rejected_no_url.append({
                "title": cand.get("title", ""),
                "company": cand.get("company", ""),
                "skip_reason": "no_url_provided",
                "timestamp": _now_iso(),
            })
            continue
        h = _url_hash(url)
        if h in existing_hashes:
            duplicates.append(url)
            continue
        record = {
            "candidate_id": cand.get("candidate_id", f"cand_{len(existing) + len(added) + 1:03d}"),
            "url": url,
            "url_hash": h,
            "title": cand.get("title", ""),
            "company": cand.get("company", ""),
            "location": cand.get("location", ""),
            "source_query_id": cand.get("source_query_id", ""),
            "relevance": cand.get("relevance", "maybe"),
            "relevance_reason": cand.get("relevance_reason", ""),
            "workstream_hint": cand.get("workstream_hint", ""),
            "fetch_status": "pending",
            "timestamp_captured": _now_iso(),
        }
        _append_jsonl(sdir / "candidate_pool.jsonl", record)
        existing_hashes.add(h)
        added.append(url)

    if rejected_no_url:
        skipped_path = sdir / "skipped_results.jsonl"
        for entry in rejected_no_url:
            _append_jsonl(skipped_path, entry)

    result: dict[str, Any] = {
        "added": len(added),
        "duplicates_blocked": len(duplicates),
        "total_candidates": len(existing) + len(added),
    }
    if rejected_no_url:
        result["rejected_no_url"] = len(rejected_no_url)
        result["rejected_no_url_details"] = [
            f"{r['company']} / {r['title']}" for r in rejected_no_url
        ]
        result["action_required"] = (
            "The above candidates were rejected because no source_url was provided. "
            "Use web_fetch on the job posting page to get the direct URL, then re-submit."
        )
    return result


def log_query_expansion(
    workspace_root: Path,
    session_id: str,
    expansion: dict[str, Any],
) -> dict[str, Any]:
    """Log a query expansion event."""
    sdir = session_dir(workspace_root, session_id)
    existing = _read_jsonl(sdir / "query_expansion_log.jsonl")
    record = {
        "expansion_id": f"exp_{len(existing) + 1:03d}",
        "timestamp": _now_iso(),
        **expansion,
    }
    _append_jsonl(sdir / "query_expansion_log.jsonl", record)
    return {"logged": True, "expansion_id": record["expansion_id"]}


def end_session(
    workspace_root: Path,
    session_id: str,
    coverage_report_path: str,
) -> dict[str, Any]:
    """
    End a search session.
    Requires a coverage_report.md to be written first.
    Updates run_config.yaml status to 'search_complete'.
    """
    sdir = session_dir(workspace_root, session_id)
    if not sdir.exists():
        return {"error": f"Session {session_id} not found"}

    coverage_src = Path(coverage_report_path)
    if not coverage_src.exists():
        return {"error": f"coverage_report not found at {coverage_report_path}. You must write it before ending the session."}

    import shutil
    shutil.copy(coverage_src, sdir / "coverage_report.md")

    status = get_session_status(workspace_root, session_id)

    import yaml  # type: ignore
    rc_path = sdir / "run_config.yaml"
    with open(rc_path) as f:
        rc = yaml.safe_load(f)
    rc["status"] = "search_complete"
    rc["search_completed_at"] = _now_iso()
    rc["final_stats"] = {
        "queries_run": status["queries_run"],
        "candidates_captured": status["candidates_captured"],
    }
    with open(rc_path, "w") as f:
        yaml.dump(rc, f, default_flow_style=False, allow_unicode=True)

    return {
        "session_ended": True,
        "session_id": session_id,
        "candidates_ready": status["candidates_captured"],
        "candidate_pool": f"runs/{session_id}/candidate_pool.jsonl",
    }
