"""Tests for search_session.log_query field normalization + validation.

Covers the fixes that stop a mistyped query field from silently producing a
malformed ledger entry that slips past the provenance gate:
  1. inline alias `query` -> canonical `query_text`
  2. unknown top-level fields are rejected with a readable error
  3. a query with no query_text is rejected
"""

from __future__ import annotations

import json
from pathlib import Path

from career_intelligence.search_session import (
    get_session_status,
    log_query,
    start_session,
)


def _new_session(tmp_path: Path, session_id: str) -> None:
    start_session(
        workspace_root=tmp_path,
        profile_name="test_profile",
        max_queries=5,
        max_fetched_pages=5,
        session_id=session_id,
    )


def _ledger(tmp_path: Path, session_id: str) -> list[dict]:
    path = tmp_path / "runs" / session_id / "search_ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_query_alias_normalized_to_query_text(tmp_path: Path) -> None:
    _new_session(tmp_path, "s1")
    result = log_query(tmp_path, "s1", {"query": "market risk nyc"})

    assert result.get("logged") is True
    assert get_session_status(tmp_path, "s1")["queries_run"] == 1

    entries = _ledger(tmp_path, "s1")
    assert len(entries) == 1
    # canonical field present, alias key gone
    assert entries[0]["query_text"] == "market risk nyc"
    assert "query" not in entries[0]


def test_unknown_field_rejected(tmp_path: Path) -> None:
    _new_session(tmp_path, "s2")
    result = log_query(tmp_path, "s2", {"query_text": "x", "bogus_field": 1})

    assert "error" in result
    assert "bogus_field" in result.get("unknown_fields", [])
    # nothing was written
    assert _ledger(tmp_path, "s2") == []
    assert get_session_status(tmp_path, "s2")["queries_run"] == 0


def test_missing_query_text_rejected(tmp_path: Path) -> None:
    _new_session(tmp_path, "s3")
    result = log_query(tmp_path, "s3", {"source_type": "ats_board"})

    assert "error" in result
    assert _ledger(tmp_path, "s3") == []


def test_known_observability_fields_pass_through(tmp_path: Path) -> None:
    _new_session(tmp_path, "s4")
    result = log_query(
        tmp_path,
        "s4",
        {
            "query_text": "valuation control associate nyc",
            "source_type": "ats_board",
            "valid_url_count": 2,
            "candidate_yield": 1,
            "observed_failure_mode": "none",
        },
    )

    assert result.get("logged") is True
    entry = _ledger(tmp_path, "s4")[0]
    assert entry["source_type"] == "ats_board"
    assert entry["valid_url_count"] == 2
    assert entry["candidate_yield"] == 1
