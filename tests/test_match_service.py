"""
Tests for match_service.create_fit_report().

Strategy:
  - Patch make_client(), match_service.make_client, and get_data_root() at their
    usage sites in match_service.
  - Use tmp_path for filesystem isolation.
  - LLM response is mocked to return a valid JSON fit report.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import career_intelligence.services.match_service as svc
from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import WorkspacePaths
from career_intelligence.services.match_service import FIT_PROMPT_VERSION
from career_intelligence.services.profile_service import FIT_PROFILE_VERSION


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture()
def ctx() -> RequestContext:
    return RequestContext(workspace_id="test_ws", user_id="test_user")


@pytest.fixture()
def store(data_root: Path) -> MetadataStore:
    s = MetadataStore.from_data_root(data_root)
    s.init_schema()
    return s


def _write_job(data_root: Path, workspace_id: str, job_id: str) -> dict:
    ws = WorkspacePaths(data_root, workspace_id)
    ws.ensure_dirs()
    record = {
        "job_id": job_id,
        "title": "Risk Analyst",
        "company": "Test Bank",
        "location": "New York",
        "primary_workstream": "Market Risk / Exposure Monitoring",
        "raw_jd_path": "",
        "fetch_status": "success",
    }
    db_dir = ws.db_dir
    db_dir.mkdir(parents=True, exist_ok=True)
    (db_dir / "jobs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    (db_dir / "job_index.json").write_text(
        json.dumps({"by_job_id": {job_id: {"line": 0, "url_hash": ""}}, "total_jobs": 1}),
        encoding="utf-8",
    )
    return record


def _write_job_report(data_root: Path, job_id: str) -> str:
    """Insert an active job report into MetadataStore and write a fake structured.json."""
    from career_intelligence.app_state.workspace_paths import get_global_paths
    gp = get_global_paths(data_root)
    job_report_id = "rpt_test0001"
    artifact_dir = gp.job_report_dir(job_report_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    structured = {"primary_workstream": "Market Risk / Exposure Monitoring", "demand_profile": {}}
    (artifact_dir / "structured.json").write_text(json.dumps(structured), encoding="utf-8")
    (artifact_dir / "report.md").write_text("# Test Report", encoding="utf-8")

    store = MetadataStore.from_data_root(data_root)
    store.init_schema()
    store.insert_job_report(
        job_id=job_id,
        jd_hash="abc123",
        prompt_version="0.2.0",
        report_path=str(artifact_dir / "report.md"),
        structured_path=str(artifact_dir / "structured.json"),
        job_report_id=job_report_id,
    )
    return job_report_id


def _write_profile(data_root: Path, workspace_id: str) -> dict:
    ws = WorkspacePaths(data_root, workspace_id)
    ws.profiles_dir.mkdir(parents=True, exist_ok=True)
    profile_id = "prof_testprofile"
    profile = {
        "candidate_profile_id": profile_id,
        "workspace_id": workspace_id,
        "created_at": "2026-06-12T10:00:00+00:00",
        "profile_version": FIT_PROFILE_VERSION,
        "years_experience": 5,
        "current_background": "Risk analyst at a bank.",
        "domain_experience": ["Market Risk"],
        "technical_skills": ["Python"],
        "analytical_methods": ["VaR"],
        "finance_domains": ["Equities"],
        "tools": ["Excel"],
        "representative_projects": [
            {
                "title": "VaR Build",
                "description": "Built VaR pipeline.",
                "skills_used": ["Python", "VaR"],
            }
        ],
    }
    profile_path = ws.candidate_profile_path(profile_id)
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    store = MetadataStore.from_data_root(data_root)
    store.init_schema()
    store.insert_candidate_profile(
        workspace_id=workspace_id,
        profile_path=str(profile_path),
        candidate_profile_id=profile_id,
    )
    return profile


def _fake_fit_structured(
    fit_report_id: str,
    workspace_id: str,
    job_id: str,
    job_report_id: str,
    profile_id: str,
) -> dict:
    return {
        "fit_report_id": fit_report_id,
        "workspace_id": workspace_id,
        "job_id": job_id,
        "job_report_id": job_report_id,
        "candidate_profile_id": profile_id,
        "analyzed_at": "2026-06-12T10:00:00+00:00",
        "prompt_version": FIT_PROMPT_VERSION,
        "overall_match_score": 75,
        "match_summary": "Good alignment on technical skills.",
        "strong_matches": [{"demand": "Python", "evidence": "VaR pipeline project."}],
        "partial_matches": [],
        "gaps": [],
        "risk_flags": [],
        "interview_talking_points": ["Discuss VaR rebuild."],
        "resume_rewrite_strategy": {
            "positioning": "Frame as a risk technologist.",
            "keywords_to_add": ["Greeks"],
            "bullets_to_reframe": [],
            "evidence_to_surface": ["VaR Build project"],
        },
        "recommended_next_action": "apply now",
    }


def _make_fake_llm(data_root, job_id, job_report_id, workspace_id, profile_id) -> MagicMock:
    """Return a mock LLM client whose call() returns valid fit report JSON."""
    client = MagicMock()
    client._default_model = "gpt-4o-test"

    def _call(system, user, max_tokens=4096, model=None):
        # Extract fit_report_id from the prompt
        import re
        m = re.search(r'"fit_report_id":\s*"(fit_[a-f0-9]+)"', user)
        fid = m.group(1) if m else "fit_testxxxx"
        return json.dumps(
            _fake_fit_structured(fid, workspace_id, job_id, job_report_id, profile_id)
        )

    client.call.side_effect = _call
    return client


@contextmanager
def _patches(data_root: Path, *, llm_none: bool = False, llm_client=None):
    with patch("career_intelligence.services.match_service.get_data_root", return_value=data_root), \
         patch("career_intelligence.services.match_service.get_workspace_paths",
               side_effect=lambda ws_id, dr=None: WorkspacePaths(data_root, ws_id)), \
         patch("career_intelligence.services.profile_service.get_data_root", return_value=data_root), \
         patch("career_intelligence.services.job_service.get_catalog_workspace_id", return_value="test_ws"), \
         patch("career_intelligence.services.job_service.get_workspace_paths",
               side_effect=lambda ws_id, dr=None: WorkspacePaths(data_root, ws_id)), \
         patch("career_intelligence.services.match_service.make_client",
               return_value=None if llm_none else llm_client):
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCreateFitReport:

    def test_creates_report_writes_artifacts(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """Happy path: fit report is generated, artifacts written, MetadataStore updated."""
        job_id = "job_abcd1234"
        _write_job(data_root, ctx.workspace_id, job_id)
        job_report_id = _write_job_report(data_root, job_id)
        profile = _write_profile(data_root, ctx.workspace_id)
        profile_id = profile["candidate_profile_id"]

        llm = _make_fake_llm(data_root, job_id, job_report_id, ctx.workspace_id, profile_id)

        with _patches(data_root, llm_client=llm):
            result = svc.create_fit_report(ctx, job_id, profile_id)

        assert result["status"] == "created"
        assert result["fit_report_id"].startswith("fit_")

        assert Path(result["report_path"]).exists(), "fit_report.md not written"
        assert Path(result["structured_path"]).exists(), "structured.json not written"

        structured = json.loads(Path(result["structured_path"]).read_text())
        assert structured["overall_match_score"] == 75

    def test_cache_hit_skips_llm(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """Second call with same inputs returns cache_hit and does not call LLM."""
        job_id = "job_abcd2222"
        _write_job(data_root, ctx.workspace_id, job_id)
        job_report_id = _write_job_report(data_root, job_id)
        profile = _write_profile(data_root, ctx.workspace_id)
        profile_id = profile["candidate_profile_id"]

        llm = _make_fake_llm(data_root, job_id, job_report_id, ctx.workspace_id, profile_id)

        with _patches(data_root, llm_client=llm):
            r1 = svc.create_fit_report(ctx, job_id, profile_id)
            r2 = svc.create_fit_report(ctx, job_id, profile_id)

        assert r1["status"] == "created"
        assert r2["status"] == "cache_hit"
        assert r2["fit_report_id"] == r1["fit_report_id"]
        assert llm.call.call_count == 1  # LLM called only once

    def test_force_bypasses_cache(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """force=True regenerates even when cache hit exists."""
        job_id = "job_abcd3333"
        _write_job(data_root, ctx.workspace_id, job_id)
        job_report_id = _write_job_report(data_root, job_id)
        profile = _write_profile(data_root, ctx.workspace_id)
        profile_id = profile["candidate_profile_id"]

        llm = _make_fake_llm(data_root, job_id, job_report_id, ctx.workspace_id, profile_id)

        with _patches(data_root, llm_client=llm):
            svc.create_fit_report(ctx, job_id, profile_id)
            r2 = svc.create_fit_report(ctx, job_id, profile_id, force=True)

        assert r2["status"] == "created"
        assert llm.call.call_count == 2

    def test_job_not_found_raises(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        ws = WorkspacePaths(data_root, ctx.workspace_id)
        ws.ensure_dirs()
        (ws.db_dir / "jobs.jsonl").write_text("", encoding="utf-8")
        (ws.db_dir / "job_index.json").write_text('{"by_job_id": {}, "total_jobs": 0}', encoding="utf-8")
        MetadataStore.from_data_root(data_root).init_schema()

        with _patches(data_root, llm_client=MagicMock()):
            with pytest.raises(ValueError, match="Job not found"):
                svc.create_fit_report(ctx, "job_missing00", "prof_any")

    def test_profile_not_found_raises(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        job_id = "job_abcd4444"
        _write_job(data_root, ctx.workspace_id, job_id)
        MetadataStore.from_data_root(data_root).init_schema()

        with _patches(data_root, llm_client=MagicMock()):
            with pytest.raises(ValueError, match="Candidate profile not found"):
                svc.create_fit_report(ctx, job_id, "prof_doesnotexist")

    def test_no_job_report_raises(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        job_id = "job_abcd5555"
        _write_job(data_root, ctx.workspace_id, job_id)
        # No job report inserted
        MetadataStore.from_data_root(data_root).init_schema()
        profile = _write_profile(data_root, ctx.workspace_id)

        with _patches(data_root, llm_client=MagicMock()):
            with pytest.raises(ValueError, match="No Job Intelligence Report"):
                svc.create_fit_report(ctx, job_id, profile["candidate_profile_id"])

    def test_no_llm_client_raises(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        job_id = "job_abcd6666"
        _write_job(data_root, ctx.workspace_id, job_id)
        _write_job_report(data_root, job_id)
        profile = _write_profile(data_root, ctx.workspace_id)

        with _patches(data_root, llm_none=True):
            with pytest.raises(RuntimeError, match="No LLM API key"):
                svc.create_fit_report(ctx, job_id, profile["candidate_profile_id"])

    def test_metadata_store_updated_after_creation(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """After creation, MetadataStore has a fit_report row with matching ID."""
        job_id = "job_abcd7777"
        _write_job(data_root, ctx.workspace_id, job_id)
        job_report_id = _write_job_report(data_root, job_id)
        profile = _write_profile(data_root, ctx.workspace_id)
        profile_id = profile["candidate_profile_id"]

        llm = _make_fake_llm(data_root, job_id, job_report_id, ctx.workspace_id, profile_id)

        with _patches(data_root, llm_client=llm):
            result = svc.create_fit_report(ctx, job_id, profile_id)

        store = MetadataStore.from_data_root(data_root)
        row = store.get_fit_report(result["fit_report_id"])
        assert row is not None
        assert row["job_id"] == job_id
        assert row["candidate_profile_id"] == profile_id
        assert row["prompt_version"] == FIT_PROMPT_VERSION
