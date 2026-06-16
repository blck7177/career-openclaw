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

import pytest

from career_intelligence.search_session import (
    _is_search_result_url,
    get_session_status,
    log_candidates,
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


# ---------------------------------------------------------------------------
# search_query.schema.json enforcement (types + enums), not just field names.
# ---------------------------------------------------------------------------


def test_invalid_source_type_enum_rejected_by_schema(tmp_path: Path) -> None:
    _new_session(tmp_path, "s5")
    result = log_query(
        tmp_path, "s5", {"query_text": "x", "source_type": "telegram"}
    )

    assert "error" in result
    assert result.get("schema_errors")
    # nothing written
    assert _ledger(tmp_path, "s5") == []


def test_non_integer_candidate_yield_rejected_by_schema(tmp_path: Path) -> None:
    _new_session(tmp_path, "s6")
    result = log_query(
        tmp_path, "s6", {"query_text": "x", "candidate_yield": "lots"}
    )

    assert "error" in result
    assert result.get("schema_errors")
    assert _ledger(tmp_path, "s6") == []


# ---------------------------------------------------------------------------
# candidate_pool_entry.schema.json enforcement on write.
# ---------------------------------------------------------------------------


def _candidate_pool(tmp_path: Path, session_id: str) -> list[dict]:
    path = tmp_path / "runs" / session_id / "candidate_pool.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_valid_candidate_admitted(tmp_path: Path) -> None:
    _new_session(tmp_path, "c1")
    log_query(tmp_path, "c1", {"query_text": "risk roles"})  # satisfy provenance gate

    result = log_candidates(
        tmp_path, "c1",
        [{"url": "https://flex.com/jobs/1", "title": "Risk Eng", "company": "Flex",
          "relevance": "relevant"}],
    )

    assert result["added"] == 1
    pool = _candidate_pool(tmp_path, "c1")
    assert len(pool) == 1
    assert pool[0]["url"] == "https://flex.com/jobs/1"
    assert pool[0]["fetch_status"] == "pending"


def test_invalid_relevance_enum_rejected_on_write(tmp_path: Path) -> None:
    _new_session(tmp_path, "c2")
    log_query(tmp_path, "c2", {"query_text": "risk roles"})

    result = log_candidates(
        tmp_path, "c2",
        [{"url": "https://flex.com/jobs/2", "relevance": "super-relevant"}],
    )

    assert result["added"] == 0
    assert result.get("rejected_schema") == 1
    assert _candidate_pool(tmp_path, "c2") == []


# ---------------------------------------------------------------------------
# Search-results / listing pages are not jobs and must never enter the pool.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.google.com/search?q=market+risk+analyst+nyc",
        "https://www.bing.com/search?q=valuation+control",
        "https://duckduckgo.com/?q=risk+jobs",
        "https://www.linkedin.com/jobs/search?keywords=market%20risk",
        "https://boards.greenhouse.io/acme/jobs/search?q=risk",
    ],
)
def test_is_search_result_url_true(url: str) -> None:
    assert _is_search_result_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/acme/jobs/4567890",
        "https://jobs.lever.co/point72/abc-123-def",
        "https://careers.morganstanley.com/job/12345/market-risk-analyst",
    ],
)
def test_is_search_result_url_false_for_real_jds(url: str) -> None:
    assert _is_search_result_url(url) is False


def test_search_result_page_rejected_on_write(tmp_path: Path) -> None:
    _new_session(tmp_path, "c3")
    log_query(tmp_path, "c3", {"query_text": "risk roles"})

    result = log_candidates(
        tmp_path, "c3",
        [
            {"url": "https://www.google.com/search?q=market+risk", "title": "x", "company": "y"},
            {"url": "https://acme.com/careers/job/777", "title": "Risk", "company": "Acme"},
        ],
    )

    assert result["added"] == 1
    assert result.get("rejected_search_page") == 1
    pool = _candidate_pool(tmp_path, "c3")
    assert len(pool) == 1
    assert pool[0]["url"] == "https://acme.com/careers/job/777"
