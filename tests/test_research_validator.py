"""Tests for the research anti-fabrication gate (research_validator)."""

from __future__ import annotations

from career_intelligence.research_validator import validate_research_bundle
from career_intelligence.url_utils import url_hash

URL_A = "https://flex.com/risk-platform"
URL_B = "https://news.example.com/flex-funding"


def _source(url, **extra):
    base = {"url": url, "related_jd_signal": "x", "boundary": "y"}
    base.update(extra)
    return base


def test_zero_real_fetch_fails():
    """No web_fetch in tool_calls and empty ledger -> fabrication guard fires."""
    res = validate_research_bundle(
        notes_text="# Notes\nlots of plausible text",
        sources=[_source(URL_A)],
        fetch_ledger=[],
        tool_calls=[],
    )
    assert res.status == "failed"
    assert "no real web_fetch" in res.reason


def test_notes_without_sources_fails():
    res = validate_research_bundle(
        notes_text="# Notes\nsome findings",
        sources=[],
        fetch_ledger=[{"url": URL_A, "url_hash": url_hash(URL_A)}],
        tool_calls=[{"tool": "web_fetch", "url": URL_A}],
    )
    assert res.status == "failed"
    assert "empty" in res.reason


def test_all_sources_verified_passes():
    res = validate_research_bundle(
        notes_text="# Notes",
        sources=[_source(URL_A)],
        fetch_ledger=[],
        tool_calls=[{"tool": "web_fetch", "url": URL_A}],
    )
    assert res.status == "passed"
    assert res.verified_source_count == 1


def test_partial_when_some_unverified():
    res = validate_research_bundle(
        notes_text="# Notes",
        sources=[_source(URL_A), _source(URL_B)],
        fetch_ledger=[],
        tool_calls=[{"tool": "web_fetch", "url": URL_A}],  # only A fetched
    )
    assert res.status == "partial"
    assert res.verified_source_count == 1
    assert res.source_count == 2


def test_no_source_matches_real_fetch_fails():
    res = validate_research_bundle(
        notes_text="# Notes",
        sources=[_source(URL_A)],
        fetch_ledger=[],
        tool_calls=[{"tool": "web_fetch", "url": "https://other.com/x"}],
    )
    assert res.status == "failed"


def test_ledger_fallback_layer_b():
    """When tool_calls don't expose fetches, the self-reported ledger is used."""
    res = validate_research_bundle(
        notes_text="# Notes",
        sources=[_source(URL_A)],
        fetch_ledger=[{"url": URL_A, "url_hash": url_hash(URL_A)}],
        tool_calls=[],
    )
    assert res.status == "passed"


def test_format_guard_downgrades_source_missing_boundary():
    """A fetched source missing related_jd_signal/boundary is not counted verified."""
    res = validate_research_bundle(
        notes_text="# Notes",
        sources=[{"url": URL_A, "related_jd_signal": "x", "boundary": ""}],
        fetch_ledger=[],
        tool_calls=[{"tool": "web_fetch", "url": URL_A}],
    )
    assert res.status == "failed"
    assert res.verified_source_count == 0


def test_min_verified_threshold():
    res = validate_research_bundle(
        notes_text="# Notes",
        sources=[_source(URL_A), _source(URL_B)],
        fetch_ledger=[],
        tool_calls=[{"tool": "web_fetch", "url": URL_A}],
        min_verified=2,
    )
    assert res.status == "failed"
    assert "min_verified" in res.reason
