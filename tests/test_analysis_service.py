"""
Tests for analysis_service.create_job_report().

Strategy:
- Patch make_client(), analyze_role(), and get_data_root() at their usage sites.
- Use tmp_path fixtures to isolate filesystem writes.
- No module reload — patches are applied to name bindings in analysis_service's namespace.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import career_intelligence.services.analysis_service as svc
from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import WorkspacePaths
from career_intelligence.role_analyzer import PROMPT_VERSION


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_REPORT_MD = "# Job Intelligence Report\n\nThis is a test report."
FAKE_STRUCTURED: dict[str, Any] = {
    "business_context": {
        "summary": "Test",
        "problem_solved": "",
        "evidence": [],
        "confidence": "low",
    },
    "primary_workstream": "unknown",
}

FAKE_LLM_MODEL = "gpt-4o-test"


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


def _write_job_with_jd(
    data_root: Path, workspace_id: str, job_id: str, jd_text: str
) -> dict:
    """Create a job record and write raw JD to the expected path under runs/."""
    ws = WorkspacePaths(data_root, workspace_id)
    ws.ensure_dirs()

    run_id = "run_test_001"
    raw_jd_dir = ws.runs_root / run_id / "raw_jds"
    raw_jd_dir.mkdir(parents=True, exist_ok=True)
    raw_jd_file = raw_jd_dir / f"{job_id}.txt"
    raw_jd_file.write_text(jd_text, encoding="utf-8")

    record = {
        "job_id": job_id,
        "title": "Test Role",
        "company": "Test Corp",
        "location": "Remote",
        "source_url": "https://example.com/jobs/123",
        "raw_jd_path": f"{run_id}/raw_jds/{job_id}.txt",
        "fetch_status": "success",
        "primary_workstream": "unknown",
    }

    db_dir = ws.db_dir
    db_dir.mkdir(parents=True, exist_ok=True)
    (db_dir / "jobs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    (db_dir / "job_index.json").write_text(
        json.dumps({"by_job_id": {job_id: {"line": 0, "url_hash": ""}}, "total_jobs": 1}),
        encoding="utf-8",
    )
    return record


def _make_fake_llm_client() -> MagicMock:
    client = MagicMock()
    client._default_model = FAKE_LLM_MODEL
    return client


@contextmanager
def _patches(data_root: Path, *, analyze_returns=None, llm_client=None, llm_none=False):
    """
    Apply all standard patches for analysis_service tests in one context manager.

    - Patches get_data_root in both analysis_service and workspace_paths modules.
    - Optionally mocks analyze_role and make_client.
    """
    fake_result = analyze_returns or (FAKE_REPORT_MD, FAKE_STRUCTURED, PROMPT_VERSION)
    fake_client = None if llm_none else (llm_client or _make_fake_llm_client())

    with patch("career_intelligence.services.analysis_service.get_data_root", return_value=data_root), \
         patch("career_intelligence.app_state.workspace_paths.get_data_root", return_value=data_root), \
         patch("career_intelligence.services.analysis_service.analyze_role", return_value=fake_result) as mock_analyze, \
         patch("career_intelligence.services.analysis_service.make_client", return_value=fake_client) as mock_make_client:
        yield mock_analyze, mock_make_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCreateJobReport:

    def test_creates_report_and_writes_artifacts(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """Happy path: new report is generated, artifacts written, MetadataStore updated."""
        job_id = "job_test001"
        _write_job_with_jd(data_root, ctx.workspace_id, job_id, "We need a risk analyst.")

        with _patches(data_root) as (mock_analyze, _):
            result = svc.create_job_report(ctx, job_id)

        assert result["status"] == "created"
        assert result["job_report_id"].startswith("rpt_")

        report_path = Path(result["report_path"])
        structured_path = Path(result["structured_path"])
        assert report_path.exists(), "report.md not written"
        assert structured_path.exists(), "structured.json not written"
        assert FAKE_REPORT_MD in report_path.read_text()

        structured = json.loads(structured_path.read_text())
        assert structured["primary_workstream"] == "unknown"

        mock_analyze.assert_called_once()

    def test_cache_hit_returns_existing_report(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """When an active report with matching cache key exists, return it without re-running."""
        job_id = "job_cached001"
        jd_text = "We need a quant."
        _write_job_with_jd(data_root, ctx.workspace_id, job_id, jd_text)

        # Pre-populate cache using the same data_root
        store = MetadataStore.from_data_root(data_root)
        store.init_schema()
        jd_hash = hashlib.md5(jd_text.encode()).hexdigest()[:16]
        cached_id = store.insert_job_report(
            job_id=job_id,
            jd_hash=jd_hash,
            prompt_version=PROMPT_VERSION,
            report_path="/fake/report.md",
            structured_path="/fake/structured.json",
        )

        with _patches(data_root) as (mock_analyze, _):
            result = svc.create_job_report(ctx, job_id)

        assert result["status"] == "cache_hit"
        assert result["job_report_id"] == cached_id
        mock_analyze.assert_not_called()

    def test_force_bypasses_cache(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """force=True regenerates the report even when a cache hit exists."""
        job_id = "job_force001"
        jd_text = "Senior data engineer."
        _write_job_with_jd(data_root, ctx.workspace_id, job_id, jd_text)

        store = MetadataStore.from_data_root(data_root)
        store.init_schema()
        jd_hash = hashlib.md5(jd_text.encode()).hexdigest()[:16]
        store.insert_job_report(
            job_id=job_id, jd_hash=jd_hash, prompt_version=PROMPT_VERSION,
            report_path="/old/report.md", structured_path="/old/structured.json",
        )

        with _patches(data_root) as (mock_analyze, _):
            result = svc.create_job_report(ctx, job_id, force=True)

        assert result["status"] == "created"
        mock_analyze.assert_called_once()

    def test_job_not_found_raises(self, data_root: Path, ctx: RequestContext) -> None:
        """Raises ValueError when job_id does not exist in the workspace."""
        ws = WorkspacePaths(data_root, ctx.workspace_id)
        ws.ensure_dirs()
        (ws.db_dir / "jobs.jsonl").write_text("", encoding="utf-8")
        (ws.db_dir / "job_index.json").write_text(
            '{"by_job_id": {}, "total_jobs": 0}', encoding="utf-8"
        )

        with _patches(data_root):
            with pytest.raises(ValueError, match="Job not found"):
                svc.create_job_report(ctx, "nonexistent_job")

    def test_missing_jd_text_raises(self, data_root: Path, ctx: RequestContext) -> None:
        """Raises ValueError when job record has no raw_jd_path and no inline jd_text."""
        ws = WorkspacePaths(data_root, ctx.workspace_id)
        ws.ensure_dirs()

        record = {
            "job_id": "job_nojd",
            "title": "Ghost Role",
            "company": "Ghost Corp",
            "raw_jd_path": "",
            "fetch_status": "failed",
        }
        (ws.db_dir / "jobs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        (ws.db_dir / "job_index.json").write_text(
            json.dumps({"by_job_id": {"job_nojd": {"line": 0, "url_hash": ""}}, "total_jobs": 1}),
            encoding="utf-8",
        )

        with _patches(data_root):
            with pytest.raises(ValueError, match="No JD text available"):
                svc.create_job_report(ctx, "job_nojd")

    def test_no_llm_client_raises(self, data_root: Path, ctx: RequestContext) -> None:
        """Raises RuntimeError when no LLM API key is configured."""
        job_id = "job_nollm"
        _write_job_with_jd(data_root, ctx.workspace_id, job_id, "Analyst role.")

        with _patches(data_root, llm_none=True):
            with pytest.raises(RuntimeError, match="No LLM API key"):
                svc.create_job_report(ctx, job_id)

    def test_metadata_store_updated_after_creation(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """After creation, MetadataStore has an active report with matching job_report_id."""
        job_id = "job_meta001"
        jd_text = "Portfolio manager role."
        _write_job_with_jd(data_root, ctx.workspace_id, job_id, jd_text)

        with _patches(data_root):
            result = svc.create_job_report(ctx, job_id)

        # Verify using a fresh store instance pointing at same data_root
        check_store = MetadataStore.from_data_root(data_root)
        jd_hash = hashlib.md5(jd_text.encode()).hexdigest()[:16]
        cached = check_store.get_active_job_report(job_id, jd_hash, PROMPT_VERSION)
        assert cached is not None
        assert cached["job_report_id"] == result["job_report_id"]
        assert cached["status"] == "active"
