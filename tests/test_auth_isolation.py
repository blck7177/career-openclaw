"""
Multi-tenant auth & isolation tests — Sprint 5 PR A (security hardening).

These tests lock in the cross-workspace authorization guarantees that an
externally-facing multi-user MVP requires:

  1. The X-Dev-Context auth bypass is OFF unless DEV_MODE is explicitly enabled.
  2. A task is only visible to its owning workspace (no IDOR on task results).
  3. A fit report is only readable by its owning workspace (private candidate
     data must not leak across tenants).
  4. The per-job fit-report list is workspace-scoped.

Strategy: redirect get_data_root() to a tmp SQLite DB, seed two workspaces with
real browser sessions, then assert that tenant B cannot read tenant A's data.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from career_intelligence.app_state.metadata_store import MetadataStore


def _seed_session(store: MetadataStore, workspace_id: str, user_id: str) -> str:
    """Create a workspace + user + browser session; return the raw session token."""
    store.get_or_create_workspace(workspace_id, name=workspace_id)
    store.get_or_create_user(user_id, workspace_id, display_name=user_id)

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    with store._conn() as conn:
        conn.execute(
            """
            INSERT INTO browser_sessions
                (session_id, user_id, workspace_id, session_token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "sess_" + secrets.token_hex(5),
                user_id,
                workspace_id,
                token_hash,
                expires_at,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return token


@pytest.fixture
def tenants(tmp_path: Path, monkeypatch):
    """
    Two isolated tenants (A, B) sharing one tmp-backed metadata store.

    Returns (client, store, token_a, token_b).
    """
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)

    # Point every get_data_root() consumer at the tmp DB.
    for module_path in (
        "apps.api.deps.get_data_root",
        "career_intelligence.services.task_service.get_data_root",
        "apps.api.routes.fit_reports.get_data_root",
    ):
        monkeypatch.setattr(module_path, lambda: data_root)

    store = MetadataStore.from_data_root(data_root)
    store.init_schema()

    token_a = _seed_session(store, "ws_a", "user_a")
    token_b = _seed_session(store, "ws_b", "user_b")

    client = TestClient(app, raise_server_exceptions=True)
    return client, store, token_a, token_b


# ---------------------------------------------------------------------------
# 1. DEV_MODE bypass is disabled unless explicitly enabled
# ---------------------------------------------------------------------------

def test_dev_context_rejected_when_dev_mode_off(tenants, monkeypatch) -> None:
    client, _store, _ta, _tb = tenants
    monkeypatch.setattr("apps.api.deps._DEV_MODE", False)

    r = client.get("/auth/me", headers={"X-Dev-Context": "dev"})
    assert r.status_code == 401


def test_dev_context_accepted_when_dev_mode_on(tenants, monkeypatch) -> None:
    client, _store, _ta, _tb = tenants
    monkeypatch.setattr("apps.api.deps._DEV_MODE", True)

    r = client.get("/auth/me", headers={"X-Dev-Context": "dev"})
    assert r.status_code == 200
    assert r.json()["workspace_id"] == "dev_default"


# ---------------------------------------------------------------------------
# 2. Task isolation — no cross-workspace IDOR
# ---------------------------------------------------------------------------

def test_task_visible_to_owning_workspace(tenants) -> None:
    client, store, token_a, _tb = tenants
    task_id = store.create_task(
        workspace_id="ws_a",
        task_type="job_report",
        payload={"job_id": "job_x"},
    )
    r = client.get(f"/api/tasks/{task_id}", headers={"Cookie": f"sid={token_a}"})
    assert r.status_code == 200
    assert r.json()["task_id"] == task_id


def test_task_hidden_from_other_workspace(tenants) -> None:
    client, store, _ta, token_b = tenants
    task_id = store.create_task(
        workspace_id="ws_a",
        task_type="job_report",
        payload={"job_id": "job_x"},
    )
    # Tenant B must not be able to read tenant A's task — 404, not 403.
    r = client.get(f"/api/tasks/{task_id}", headers={"Cookie": f"sid={token_b}"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 3. Fit report isolation — private candidate data must not leak
# ---------------------------------------------------------------------------

def _seed_fit_report(store: MetadataStore, workspace_id: str, job_id: str) -> str:
    return store.insert_fit_report(
        workspace_id=workspace_id,
        job_id=job_id,
        job_report_id="rpt_x",
        candidate_profile_id="cp_x",
        profile_hash="hash_x",
        prompt_version="0.1.0",
        report_path=None,
        structured_path=None,
    )


def test_fit_report_visible_to_owning_workspace(tenants) -> None:
    client, store, token_a, _tb = tenants
    fit_id = _seed_fit_report(store, "ws_a", "job_x")
    r = client.get(f"/api/fit-reports/{fit_id}", headers={"Cookie": f"sid={token_a}"})
    assert r.status_code == 200


def test_fit_report_hidden_from_other_workspace(tenants) -> None:
    client, store, _ta, token_b = tenants
    fit_id = _seed_fit_report(store, "ws_a", "job_x")
    r = client.get(f"/api/fit-reports/{fit_id}", headers={"Cookie": f"sid={token_b}"})
    assert r.status_code == 404


def test_job_fit_report_list_is_workspace_scoped(tenants) -> None:
    client, store, token_a, token_b = tenants
    _seed_fit_report(store, "ws_a", "job_x")

    # Owner sees the report.
    r_a = client.get("/api/jobs/job_x/fit-reports", headers={"Cookie": f"sid={token_a}"})
    assert r_a.status_code == 200
    assert len(r_a.json()) == 1

    # Other tenant sees nothing for the same job_id.
    r_b = client.get("/api/jobs/job_x/fit-reports", headers={"Cookie": f"sid={token_b}"})
    assert r_b.status_code == 200
    assert r_b.json() == []


# ---------------------------------------------------------------------------
# 4. Unauthenticated access is rejected
# ---------------------------------------------------------------------------

def test_unauthenticated_request_rejected(tenants) -> None:
    client, _store, _ta, _tb = tenants
    r = client.get("/api/tasks/task_anything")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 5. Logout revokes the server-side session
# ---------------------------------------------------------------------------

def test_logout_deletes_server_session(tenants) -> None:
    """After logout, the same sid cookie must no longer authenticate."""
    client, _store, token_a, _tb = tenants

    # Cookie is valid before logout.
    r = client.get("/auth/me", headers={"Cookie": f"sid={token_a}"})
    assert r.status_code == 200

    # Logout with the same cookie.
    r = client.delete("/auth/logout", headers={"Cookie": f"sid={token_a}"})
    assert r.status_code == 204

    # Same raw token must now be rejected — server-side row is gone.
    r = client.get("/auth/me", headers={"Cookie": f"sid={token_a}"})
    assert r.status_code == 401


def test_logout_without_cookie_is_safe(tenants) -> None:
    """DELETE /auth/logout with no cookie must not crash (returns 204)."""
    client, _store, _ta, _tb = tenants
    r = client.delete("/auth/logout")
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# 6. Task dedupe & concurrency limits (API layer)
# ---------------------------------------------------------------------------

def test_job_report_dedupe_returns_same_task_id(tenants) -> None:
    """POST /api/jobs/{id}/analyze twice (force=False) returns the same task_id."""
    client, _store, token_a, _tb = tenants
    headers = {"Cookie": f"sid={token_a}"}

    r1 = client.post("/api/jobs/job_001/analyze", headers=headers)
    assert r1.status_code == 202
    task_id_1 = r1.json()["task_id"]

    r2 = client.post("/api/jobs/job_001/analyze", headers=headers)
    assert r2.status_code == 202
    task_id_2 = r2.json()["task_id"]

    assert task_id_1 == task_id_2, "Duplicate submission should return the existing task_id"


def test_job_report_force_creates_new_task(tenants) -> None:
    """POST /api/jobs/{id}/analyze?force=true always creates a fresh task."""
    client, _store, token_a, _tb = tenants
    headers = {"Cookie": f"sid={token_a}"}

    r1 = client.post("/api/jobs/job_002/analyze", headers=headers)
    assert r1.status_code == 202
    task_id_1 = r1.json()["task_id"]

    r2 = client.post("/api/jobs/job_002/analyze?force=true", headers=headers)
    assert r2.status_code == 202
    task_id_2 = r2.json()["task_id"]

    assert task_id_1 != task_id_2, "force=True must bypass dedupe and create a new task"


def test_fit_report_dedupe_returns_same_task_id(tenants) -> None:
    """POST /api/jobs/{id}/fit twice (force=False) returns the same task_id."""
    client, _store, token_a, _tb = tenants
    headers = {"Cookie": f"sid={token_a}"}
    body = {"profile_id": "prof_xyz", "force": False}

    r1 = client.post("/api/jobs/job_003/fit", json=body, headers=headers)
    assert r1.status_code == 202
    task_id_1 = r1.json()["task_id"]

    r2 = client.post("/api/jobs/job_003/fit", json=body, headers=headers)
    assert r2.status_code == 202
    task_id_2 = r2.json()["task_id"]

    assert task_id_1 == task_id_2
