"""
API smoke tests — Sprint 1 read-only endpoints.

Uses FastAPI TestClient (sync) with monkeypatching to redirect filesystem
paths to tmp_path, so tests are fully isolated from real workspace data.

Auth: all requests use the X-Dev-Context: dev header which bypasses cookie
auth in DEV_MODE (the default).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

# Force DEV_MODE before importing the app so the env var is visible
os.environ.setdefault("DEV_MODE", "1")

from apps.api.main import app
from career_intelligence.app_state.workspace_paths import WorkspacePaths


_DEV_HEADERS = {"X-Dev-Context": "dev"}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jobs(db_dir: Path, records: list[dict[str, Any]]) -> None:
    db_dir.mkdir(parents=True, exist_ok=True)
    jobs_path = db_dir / "jobs.jsonl"
    index: dict = {"by_url_hash": {}, "by_job_id": {}, "by_dedup_key": {}, "total_jobs": 0}
    with open(jobs_path, "w", encoding="utf-8") as f:
        for i, rec in enumerate(records):
            f.write(json.dumps(rec) + "\n")
            if jid := rec.get("job_id"):
                index["by_job_id"][jid] = {"line": i, "url_hash": ""}
    index["total_jobs"] = len(records)
    (db_dir / "job_index.json").write_text(json.dumps(index), encoding="utf-8")


def _write_run(runs_root: Path, run_id: str, cfg: dict, summary: dict | None = None, md: str | None = None) -> None:
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "run_config.yaml", "w") as f:
        yaml.dump(cfg, f)
    if summary is not None:
        (run_dir / "run_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    if md is not None:
        (run_dir / "run_summary.md").write_text(md, encoding="utf-8")


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------

def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Auth — /auth/me (uses DEV_MODE bypass)
# ---------------------------------------------------------------------------

def test_auth_me_dev(client: TestClient) -> None:
    r = client.get("/auth/me", headers=_DEV_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["workspace_id"] == "dev_default"
    assert data["user_id"] == "dev_user"


def test_auth_me_unauthenticated(client: TestClient) -> None:
    r = client.get("/auth/me")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Jobs — GET /api/jobs
# ---------------------------------------------------------------------------

class TestJobsEndpoints:
    def test_list_jobs_empty(self, client: TestClient, tmp_path: Path, monkeypatch) -> None:
        paths = WorkspacePaths(tmp_path / "data", "dev_default")
        paths.ensure_dirs()
        monkeypatch.setattr(
            "career_intelligence.services.job_service.get_workspace_paths",
            lambda wid: WorkspacePaths(tmp_path / "data", wid),
        )
        r = client.get("/api/jobs", headers=_DEV_HEADERS)
        assert r.status_code == 200
        assert r.json() == []

    def test_list_jobs_returns_data(self, client: TestClient, tmp_path: Path, monkeypatch) -> None:
        paths = WorkspacePaths(tmp_path / "data", "dev_default")
        paths.ensure_dirs()
        records = [
            {"job_id": "job_aaa", "title": "Risk Analyst", "company": "Acme",
             "primary_workstream": "Market Risk", "secondary_workstreams": [], "date_found": "2026-06-01"},
        ]
        _write_jobs(paths.db_dir, records)
        monkeypatch.setattr(
            "career_intelligence.services.job_service.get_workspace_paths",
            lambda wid: WorkspacePaths(tmp_path / "data", wid),
        )
        r = client.get("/api/jobs", headers=_DEV_HEADERS)
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["job_id"] == "job_aaa"

    def test_get_job_found(self, client: TestClient, tmp_path: Path, monkeypatch) -> None:
        paths = WorkspacePaths(tmp_path / "data", "dev_default")
        paths.ensure_dirs()
        records = [{"job_id": "job_xyz", "title": "Quant Analyst", "company": "HF"}]
        _write_jobs(paths.db_dir, records)
        monkeypatch.setattr(
            "career_intelligence.services.job_service.get_workspace_paths",
            lambda wid: WorkspacePaths(tmp_path / "data", wid),
        )
        r = client.get("/api/jobs/job_xyz", headers=_DEV_HEADERS)
        assert r.status_code == 200
        assert r.json()["title"] == "Quant Analyst"

    def test_get_job_not_found(self, client: TestClient, tmp_path: Path, monkeypatch) -> None:
        paths = WorkspacePaths(tmp_path / "data", "dev_default")
        paths.ensure_dirs()
        monkeypatch.setattr(
            "career_intelligence.services.job_service.get_workspace_paths",
            lambda wid: WorkspacePaths(tmp_path / "data", wid),
        )
        r = client.get("/api/jobs/job_missing", headers=_DEV_HEADERS)
        assert r.status_code == 404

    def test_job_report_not_found(self, client: TestClient, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "career_intelligence.services.report_service.get_data_root",
            lambda: tmp_path / "data",
        )
        r = client.get("/api/jobs/job_noreport/job-report", headers=_DEV_HEADERS)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Runs — GET /api/runs
# ---------------------------------------------------------------------------

class TestRunsEndpoints:
    def test_list_runs_empty(self, client: TestClient, tmp_path: Path, monkeypatch) -> None:
        paths = WorkspacePaths(tmp_path / "data", "dev_default")
        paths.ensure_dirs()
        monkeypatch.setattr(
            "career_intelligence.services.run_service.get_workspace_paths",
            lambda wid: WorkspacePaths(tmp_path / "data", wid),
        )
        r = client.get("/api/runs", headers=_DEV_HEADERS)
        assert r.status_code == 200
        assert r.json() == []

    def test_list_runs_returns_data(self, client: TestClient, tmp_path: Path, monkeypatch) -> None:
        paths = WorkspacePaths(tmp_path / "data", "dev_default")
        paths.ensure_dirs()
        cfg = {"profile_name": "nyc", "mode": "exploratory", "status": "search_complete",
               "final_stats": {"candidates_captured": 4}}
        _write_run(paths.runs_root, "2026-06-01_100000", cfg)
        monkeypatch.setattr(
            "career_intelligence.services.run_service.get_workspace_paths",
            lambda wid: WorkspacePaths(tmp_path / "data", wid),
        )
        r = client.get("/api/runs", headers=_DEV_HEADERS)
        assert r.status_code == 200
        runs = r.json()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "2026-06-01_100000"
        assert runs[0]["candidates_captured"] == 4

    def test_get_run_detail(self, client: TestClient, tmp_path: Path, monkeypatch) -> None:
        paths = WorkspacePaths(tmp_path / "data", "dev_default")
        paths.ensure_dirs()
        cfg = {"profile_name": "nyc", "mode": "exploratory", "status": "complete",
               "final_stats": {"candidates_captured": 2}}
        summary = {"run_id": "2026-06-01_100000", "jobs_saved": 2}
        _write_run(paths.runs_root, "2026-06-01_100000", cfg, summary=summary)
        monkeypatch.setattr(
            "career_intelligence.services.run_service.get_workspace_paths",
            lambda wid: WorkspacePaths(tmp_path / "data", wid),
        )
        r = client.get("/api/runs/2026-06-01_100000", headers=_DEV_HEADERS)
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == "2026-06-01_100000"
        assert data["summary"]["jobs_saved"] == 2

    def test_get_run_not_found(self, client: TestClient, tmp_path: Path, monkeypatch) -> None:
        paths = WorkspacePaths(tmp_path / "data", "dev_default")
        paths.ensure_dirs()
        monkeypatch.setattr(
            "career_intelligence.services.run_service.get_workspace_paths",
            lambda wid: WorkspacePaths(tmp_path / "data", wid),
        )
        r = client.get("/api/runs/9999-99-99_999999", headers=_DEV_HEADERS)
        assert r.status_code == 404

    def test_get_run_summary_md(self, client: TestClient, tmp_path: Path, monkeypatch) -> None:
        paths = WorkspacePaths(tmp_path / "data", "dev_default")
        paths.ensure_dirs()
        cfg = {"profile_name": "nyc", "mode": "exploratory", "status": "complete", "final_stats": {}}
        _write_run(paths.runs_root, "2026-06-01_100000", cfg, md="# Summary\nJobs: 3")
        monkeypatch.setattr(
            "career_intelligence.services.run_service.get_workspace_paths",
            lambda wid: WorkspacePaths(tmp_path / "data", wid),
        )
        r = client.get("/api/runs/2026-06-01_100000/summary", headers=_DEV_HEADERS)
        assert r.status_code == 200
        assert "Jobs: 3" in r.text

    def test_get_run_summary_missing(self, client: TestClient, tmp_path: Path, monkeypatch) -> None:
        paths = WorkspacePaths(tmp_path / "data", "dev_default")
        paths.ensure_dirs()
        cfg = {"profile_name": "nyc", "mode": "exploratory", "status": "complete", "final_stats": {}}
        _write_run(paths.runs_root, "2026-06-01_100000", cfg)
        monkeypatch.setattr(
            "career_intelligence.services.run_service.get_workspace_paths",
            lambda wid: WorkspacePaths(tmp_path / "data", wid),
        )
        r = client.get("/api/runs/2026-06-01_100000/summary", headers=_DEV_HEADERS)
        assert r.status_code == 404
