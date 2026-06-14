"""Tests for research_service.ensure_research_bundle() with a mocked agent gateway."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

import career_intelligence.services.research_service as rsvc
from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.services import agent_gateway

URL = "https://flex.com/risk-platform"

JOB_RECORD = {
    "job_id": "job_aaaaaaaa",
    "title": "Risk Engineer",
    "company": "Flex",
    "source_url": "https://flex.com/jobs/1",
    "division_or_business_line": "Risk Platform team",
    "finance_domains": ["credit risk"],
    "jd_text": "We need a risk engineer to build exposure monitoring.",
}


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture()
def ctx() -> RequestContext:
    return RequestContext(workspace_id="test_ws", user_id="test_user")


def _fake_invoke_factory(sources: list[dict], tool_calls: list[dict], write_sources=True):
    def _fake_invoke(inv: agent_gateway.AgentInvocation) -> agent_gateway.AgentRunResult:
        notes_path, sources_path = inv.expected_outputs
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        notes_path.write_text("# Research Notes\nfindings", encoding="utf-8")
        if write_sources:
            sources_path.write_text(json.dumps(sources), encoding="utf-8")
        return agent_gateway.AgentRunResult(
            status="complete",
            turns_used=1,
            outputs_present=[p for p in inv.expected_outputs if p.exists()],
            outputs_missing=[p for p in inv.expected_outputs if not p.exists()],
            tool_calls=tool_calls,
            raw_outputs=[],
            raw_log_path=None,
        )
    return _fake_invoke


@contextmanager
def _patches(data_root: Path, fake_invoke):
    with patch("career_intelligence.services.research_service.get_data_root", return_value=data_root), \
         patch("career_intelligence.app_state.workspace_paths.get_data_root", return_value=data_root), \
         patch("career_intelligence.services.research_service.get_catalog_workspace_id", return_value="test_ws"), \
         patch("career_intelligence.services.research_service.get_job", return_value=dict(JOB_RECORD)), \
         patch("career_intelligence.services.research_service.make_client", return_value=None), \
         patch.object(rsvc.agent_gateway, "invoke", fake_invoke):
        yield


def test_passed_bundle_persisted_and_used(data_root: Path, ctx: RequestContext):
    sources = [{"url": URL, "title": "t", "source_type": "company_website",
                "related_jd_signal": "risk platform", "boundary": "n/a"}]
    fake = _fake_invoke_factory(sources, [{"tool": "web_fetch", "url": URL}])
    with _patches(data_root, fake):
        bundle = rsvc.ensure_research_bundle(ctx, JOB_RECORD["job_id"])

    assert bundle["validation_status"] == "passed"
    assert bundle["used_research"] is True
    assert bundle["bundle_hash"] != "none"
    assert bundle["verified_source_count"] == 1

    store = MetadataStore.from_data_root(data_root)
    row = store.get_active_research_bundle(JOB_RECORD["job_id"], bundle_inputs_hash(data_root, ctx))
    assert row is not None
    assert row["validation_status"] == "passed"


def test_failed_bundle_degrades(data_root: Path, ctx: RequestContext):
    """No real web_fetch -> failed, not usable, bundle_hash 'none'."""
    sources = [{"url": URL, "related_jd_signal": "x", "boundary": "y"}]
    fake = _fake_invoke_factory(sources, tool_calls=[])  # no fetches
    with _patches(data_root, fake):
        bundle = rsvc.ensure_research_bundle(ctx, JOB_RECORD["job_id"])

    assert bundle["validation_status"] == "failed"
    assert bundle["used_research"] is False
    assert bundle["bundle_hash"] == "none"


def test_cache_hit_skips_agent(data_root: Path, ctx: RequestContext):
    sources = [{"url": URL, "related_jd_signal": "x", "boundary": "y"}]
    fake = _fake_invoke_factory(sources, [{"tool": "web_fetch", "url": URL}])
    with _patches(data_root, fake):
        first = rsvc.ensure_research_bundle(ctx, JOB_RECORD["job_id"])

    # Second call: gateway must NOT be invoked again
    sentinel_called = {"n": 0}

    def _should_not_run(inv):  # noqa: ARG001
        sentinel_called["n"] += 1
        raise AssertionError("agent gateway should not run on cache hit")

    with _patches(data_root, _should_not_run):
        second = rsvc.ensure_research_bundle(ctx, JOB_RECORD["job_id"])

    assert sentinel_called["n"] == 0
    assert second["validation_status"] == first["validation_status"]
    assert second["reason"] == "cache_hit"


def bundle_inputs_hash(data_root: Path, ctx: RequestContext) -> str:
    """Recompute inputs hash the way research_service does (for assertions)."""
    jd_hash = rsvc._jd_hash(JOB_RECORD["jd_text"])
    return rsvc._research_inputs_hash(JOB_RECORD["job_id"], jd_hash)
