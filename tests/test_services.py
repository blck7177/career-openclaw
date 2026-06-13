"""
Tests for the Sprint 1 service layer.

Uses tmp_path fixtures to avoid touching real workspace data.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import yaml

from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import WorkspacePaths, GlobalPaths


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture()
def ctx() -> RequestContext:
    return RequestContext(workspace_id="test_ws", user_id="test_user")


@pytest.fixture()
def ws_paths(data_root: Path, ctx: RequestContext) -> WorkspacePaths:
    paths = WorkspacePaths(data_root, ctx.workspace_id)
    paths.ensure_dirs()
    return paths


@pytest.fixture()
def store(data_root: Path) -> MetadataStore:
    s = MetadataStore.from_data_root(data_root)
    s.init_schema()
    return s


def _write_jobs(db_dir: Path, records: list[dict]) -> None:
    """Write records to jobs.jsonl and build job_index.json."""
    db_dir.mkdir(parents=True, exist_ok=True)
    jobs_path = db_dir / "jobs.jsonl"
    index: dict = {"by_url_hash": {}, "by_job_id": {}, "by_dedup_key": {}, "total_jobs": 0}
    with open(jobs_path, "w", encoding="utf-8") as f:
        for i, rec in enumerate(records):
            f.write(json.dumps(rec) + "\n")
            jid = rec.get("job_id", "")
            if jid:
                index["by_job_id"][jid] = {"line": i, "url_hash": ""}
    index["total_jobs"] = len(records)
    with open(db_dir / "job_index.json", "w", encoding="utf-8") as f:
        json.dump(index, f)


def _write_run(runs_root: Path, run_id: str, config: dict, summary: dict | None = None, md: str | None = None) -> None:
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "run_config.yaml", "w") as f:
        yaml.dump(config, f)
    if summary is not None:
        with open(run_dir / "run_summary.json", "w") as f:
            json.dump(summary, f)
    if md is not None:
        (run_dir / "run_summary.md").write_text(md, encoding="utf-8")


# ---------------------------------------------------------------------------
# job_service tests
# ---------------------------------------------------------------------------

class TestJobService:
    @pytest.fixture(autouse=True)
    def _catalog_is_test_ws(self, monkeypatch):
        """Jobs read from the shared catalog; point the catalog at the test workspace."""
        monkeypatch.setattr(
            "career_intelligence.services.job_service.get_catalog_workspace_id",
            lambda: "test_ws",
        )

    def test_list_jobs_empty(self, ctx: RequestContext, ws_paths: WorkspacePaths, monkeypatch, data_root):
        monkeypatch.setattr(
            "career_intelligence.services.job_service.get_workspace_paths",
            lambda wid: WorkspacePaths(data_root, wid),
        )
        from career_intelligence.services import job_service
        result = job_service.list_jobs(ctx)
        assert result == []

    def test_list_jobs_returns_records(self, ctx, ws_paths, monkeypatch, data_root):
        records = [
            {"job_id": "job_aaa", "title": "Risk Analyst", "company": "Acme", "primary_workstream": "Market Risk / Exposure Monitoring", "date_found": "2026-06-01"},
            {"job_id": "job_bbb", "title": "P&L Analyst", "company": "Beta", "primary_workstream": "Product Control / P&L Reporting", "date_found": "2026-06-02"},
        ]
        _write_jobs(ws_paths.db_dir, records)
        monkeypatch.setattr(
            "career_intelligence.services.job_service.get_workspace_paths",
            lambda wid: WorkspacePaths(data_root, wid),
        )
        from career_intelligence.services import job_service
        result = job_service.list_jobs(ctx)
        assert len(result) == 2

    def test_list_jobs_workstream_filter(self, ctx, ws_paths, monkeypatch, data_root):
        records = [
            {"job_id": "job_aaa", "title": "Risk Analyst", "company": "Acme", "primary_workstream": "Market Risk / Exposure Monitoring", "secondary_workstreams": [], "date_found": "2026-06-01"},
            {"job_id": "job_bbb", "title": "P&L Analyst", "company": "Beta", "primary_workstream": "Product Control / P&L Reporting", "secondary_workstreams": [], "date_found": "2026-06-02"},
        ]
        _write_jobs(ws_paths.db_dir, records)
        monkeypatch.setattr(
            "career_intelligence.services.job_service.get_workspace_paths",
            lambda wid: WorkspacePaths(data_root, wid),
        )
        from career_intelligence.services import job_service
        result = job_service.list_jobs(ctx, workstream="Market Risk")
        assert len(result) == 1
        assert result[0]["job_id"] == "job_aaa"

    def test_get_job_by_id(self, ctx, ws_paths, monkeypatch, data_root):
        records = [
            {"job_id": "job_aaa", "title": "Risk Analyst", "company": "Acme"},
            {"job_id": "job_bbb", "title": "P&L Analyst", "company": "Beta"},
        ]
        _write_jobs(ws_paths.db_dir, records)
        monkeypatch.setattr(
            "career_intelligence.services.job_service.get_workspace_paths",
            lambda wid: WorkspacePaths(data_root, wid),
        )
        from career_intelligence.services import job_service
        result = job_service.get_job(ctx, "job_bbb")
        assert result is not None
        assert result["title"] == "P&L Analyst"

    def test_get_job_not_found(self, ctx, ws_paths, monkeypatch, data_root):
        _write_jobs(ws_paths.db_dir, [{"job_id": "job_aaa", "title": "Risk Analyst"}])
        monkeypatch.setattr(
            "career_intelligence.services.job_service.get_workspace_paths",
            lambda wid: WorkspacePaths(data_root, wid),
        )
        from career_intelligence.services import job_service
        result = job_service.get_job(ctx, "job_zzz")
        assert result is None

    def test_catalog_is_shared_across_workspaces(self, ws_paths, monkeypatch, data_root):
        """Jobs written to the catalog are visible from any workspace, not just the writer's."""
        records = [{"job_id": "job_shared", "title": "Risk Analyst", "company": "Acme"}]
        _write_jobs(ws_paths.db_dir, records)  # ws_paths == catalog workspace (test_ws)
        monkeypatch.setattr(
            "career_intelligence.services.job_service.get_workspace_paths",
            lambda wid: WorkspacePaths(data_root, wid),
        )
        from career_intelligence.services import job_service

        # A brand-new, different workspace still sees the shared catalog.
        other_ctx = RequestContext(workspace_id="freshly_invited_ws", user_id="newcomer")
        listed = job_service.list_jobs(other_ctx)
        assert [j["job_id"] for j in listed] == ["job_shared"]
        assert job_service.get_job(other_ctx, "job_shared") is not None


# ---------------------------------------------------------------------------
# run_service tests
# ---------------------------------------------------------------------------

class TestRunService:
    def test_list_runs_empty(self, ctx, ws_paths, monkeypatch, data_root):
        monkeypatch.setattr(
            "career_intelligence.services.run_service.get_workspace_paths",
            lambda wid: WorkspacePaths(data_root, wid),
        )
        from career_intelligence.services import run_service
        assert run_service.list_runs(ctx) == []

    def test_list_runs_returns_sorted(self, ctx, ws_paths, monkeypatch, data_root):
        cfg_a = {"profile_name": "alpha", "mode": "exploratory", "status": "search_complete", "final_stats": {"candidates_captured": 5}}
        cfg_b = {"profile_name": "beta", "mode": "exploratory", "status": "search_complete", "final_stats": {"candidates_captured": 2}}
        _write_run(ws_paths.runs_root, "2026-06-01_100000", cfg_a)
        _write_run(ws_paths.runs_root, "2026-06-02_100000", cfg_b)
        monkeypatch.setattr(
            "career_intelligence.services.run_service.get_workspace_paths",
            lambda wid: WorkspacePaths(data_root, wid),
        )
        from career_intelligence.services import run_service
        runs = run_service.list_runs(ctx)
        assert len(runs) == 2
        assert runs[0]["run_id"] == "2026-06-02_100000"

    def test_get_run_with_summary(self, ctx, ws_paths, monkeypatch, data_root):
        cfg = {"profile_name": "nyc", "mode": "exploratory", "status": "complete", "final_stats": {"candidates_captured": 3}}
        summary = {"run_id": "2026-06-01_100000", "jobs_saved": 3}
        md = "# Summary\nAll good."
        _write_run(ws_paths.runs_root, "2026-06-01_100000", cfg, summary=summary, md=md)
        monkeypatch.setattr(
            "career_intelligence.services.run_service.get_workspace_paths",
            lambda wid: WorkspacePaths(data_root, wid),
        )
        from career_intelligence.services import run_service
        run = run_service.get_run(ctx, "2026-06-01_100000")
        assert run is not None
        assert run["profile_name"] == "nyc"
        assert run["summary"]["jobs_saved"] == 3
        assert run["has_summary_md"] is True

    def test_get_run_not_found(self, ctx, ws_paths, monkeypatch, data_root):
        monkeypatch.setattr(
            "career_intelligence.services.run_service.get_workspace_paths",
            lambda wid: WorkspacePaths(data_root, wid),
        )
        from career_intelligence.services import run_service
        assert run_service.get_run(ctx, "2099-01-01_999999") is None

    def test_get_run_summary_content(self, ctx, ws_paths, monkeypatch, data_root):
        cfg = {"profile_name": "nyc", "mode": "exploratory", "status": "complete", "final_stats": {}}
        md = textwrap.dedent("""\
            # Run Summary
            Jobs saved: 7
        """)
        _write_run(ws_paths.runs_root, "2026-06-01_100000", cfg, md=md)
        monkeypatch.setattr(
            "career_intelligence.services.run_service.get_workspace_paths",
            lambda wid: WorkspacePaths(data_root, wid),
        )
        from career_intelligence.services import run_service
        content = run_service.get_run_summary(ctx, "2026-06-01_100000")
        assert content is not None
        assert "Jobs saved: 7" in content

    def test_get_run_summary_missing(self, ctx, ws_paths, monkeypatch, data_root):
        cfg = {"profile_name": "nyc", "mode": "exploratory", "status": "complete", "final_stats": {}}
        _write_run(ws_paths.runs_root, "2026-06-01_100000", cfg)
        monkeypatch.setattr(
            "career_intelligence.services.run_service.get_workspace_paths",
            lambda wid: WorkspacePaths(data_root, wid),
        )
        from career_intelligence.services import run_service
        assert run_service.get_run_summary(ctx, "2026-06-01_100000") is None


# ---------------------------------------------------------------------------
# task_service tests
# ---------------------------------------------------------------------------

class TestTaskService:
    def test_create_and_get_task(self, ctx, monkeypatch, data_root):
        monkeypatch.setattr(
            "career_intelligence.services.task_service.get_data_root",
            lambda: data_root,
        )
        from career_intelligence.services import task_service
        task_id = task_service.create_task(ctx, "job_report", {"job_id": "job_abc"})
        assert task_id.startswith("task_")

        task = task_service.get_task(task_id)
        assert task is not None
        assert task["task_type"] == "job_report"
        assert task["status"] == "pending"
        assert task["payload"]["job_id"] == "job_abc"

    def test_poll_pending_claims_task(self, ctx, monkeypatch, data_root):
        monkeypatch.setattr(
            "career_intelligence.services.task_service.get_data_root",
            lambda: data_root,
        )
        from career_intelligence.services import task_service
        task_id = task_service.create_task(ctx, "job_report", {"job_id": "job_xyz"})
        claimed = task_service.poll_pending_tasks()
        assert claimed is not None
        assert claimed["task_id"] == task_id
        assert claimed["status"] == "running"

    def test_poll_empty_queue_returns_none(self, ctx, monkeypatch, data_root):
        monkeypatch.setattr(
            "career_intelligence.services.task_service.get_data_root",
            lambda: data_root,
        )
        from career_intelligence.services import task_service
        assert task_service.poll_pending_tasks() is None

    def test_complete_task(self, ctx, monkeypatch, data_root):
        monkeypatch.setattr(
            "career_intelligence.services.task_service.get_data_root",
            lambda: data_root,
        )
        from career_intelligence.services import task_service
        task_id = task_service.create_task(ctx, "job_report", {"job_id": "job_done"})
        task_service.poll_pending_tasks()
        task_service.complete_task(task_id, result={"job_report_id": "rpt_123"})
        task = task_service.get_task(task_id)
        assert task["status"] == "completed"
        assert task["result"]["job_report_id"] == "rpt_123"

    def test_list_tasks(self, ctx, monkeypatch, data_root):
        monkeypatch.setattr(
            "career_intelligence.services.task_service.get_data_root",
            lambda: data_root,
        )
        from career_intelligence.services import task_service
        task_service.create_task(ctx, "job_report", {"job_id": "j1"})
        task_service.create_task(ctx, "fit_report", {"job_id": "j2"})
        all_tasks = task_service.list_tasks(ctx)
        assert len(all_tasks) == 2
        job_report_tasks = task_service.list_tasks(ctx, task_type="job_report")
        assert len(job_report_tasks) == 1

    def test_claim_increments_attempts(self, ctx, monkeypatch, data_root):
        """attempts starts at 0 and becomes 1 the first time a task is claimed."""
        monkeypatch.setattr(
            "career_intelligence.services.task_service.get_data_root",
            lambda: data_root,
        )
        from career_intelligence.services import task_service
        task_id = task_service.create_task(ctx, "job_report", {"job_id": "job_a"})
        assert task_service.get_task(task_id)["attempts"] == 0

        claimed = task_service.poll_pending_tasks()
        assert claimed["attempts"] == 1
        assert task_service.get_task(task_id)["attempts"] == 1


# ---------------------------------------------------------------------------
# Worker crash-recovery tests (PR-B-lite)
# ---------------------------------------------------------------------------

class TestWorkerRecovery:
    def _insert_running_task(self, store, *, attempts: int) -> str:
        """Insert a task already stuck in 'running' with a given attempts count."""
        task_id = store.create_task("test_ws", "job_report", {"job_id": "j"})
        with store._conn() as conn:
            conn.execute(
                "UPDATE task_queue SET status = 'running', started_at = ?, "
                "attempts = ? WHERE task_id = ?",
                ("2026-01-01T00:00:00+00:00", attempts, task_id),
            )
        return task_id

    def test_recovery_requeues_under_cap(self, store, monkeypatch):
        from apps.worker import worker
        monkeypatch.setattr(worker, "MAX_ATTEMPTS", 3)
        task_id = self._insert_running_task(store, attempts=2)

        worker._recover_stale_tasks(store)

        task = store.get_task(task_id)
        assert task["status"] == "pending"
        assert task["started_at"] is None

    def test_recovery_fails_over_cap(self, store, monkeypatch):
        from apps.worker import worker
        monkeypatch.setattr(worker, "MAX_ATTEMPTS", 3)
        task_id = self._insert_running_task(store, attempts=3)

        worker._recover_stale_tasks(store)

        task = store.get_task(task_id)
        assert task["status"] == "failed"
        assert task["finished_at"] is not None
        assert "exceeded max attempts" in (task["error_message"] or "")
