"""
End-to-end smoke tests for the POST /api/discovery-runs → Intent Translator → agent pipeline.

Layer A — API layer (FastAPI TestClient):
    POST /api/discovery-runs with valid profile  → 202, task_id returned
    POST /api/discovery-runs with unknown profile → 404
    POST /api/discovery-runs with invalid mode   → 422
    GET  /api/discovery-runs/{task_id} (valid)   → 200, task dict
    GET  /api/discovery-runs/{task_id} (unknown) → 404

Layer B — Worker handler (_handle_new_path):
    translate_intent called with profile + instruction
    run_discovery_session receives the discovery_intent from the translator
    translator artifacts (translator_input.json, discovery_intent.json) persisted to session dir
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Force DEV_MODE before importing the app
os.environ.setdefault("DEV_MODE", "1")

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.worker.handlers.search_run import _handle_new_path
from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.services.profile_service import create_manual_profile

_DEV_HEADERS = {"X-Dev-Context": "dev"}


# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

def _minimal_profile_data() -> dict[str, Any]:
    return {
        "years_experience": 3,
        "current_background": "Risk analyst with VaR and stress testing focus.",
        "domain_experience": ["Market Risk", "Valuation Control"],
        "technical_skills": ["Python", "SQL"],
        "analytical_methods": ["VaR", "Stress Testing"],
        "finance_domains": ["Fixed Income", "Equities"],
        "tools": ["Excel", "Bloomberg"],
        "representative_projects": [
            {
                "title": "Daily VaR Pipeline",
                "description": "Automated daily VaR reporting across equity and credit books.",
                "skills_used": ["Python", "SQL"],
                "quantified_impact": "Saved 2 hours/day of manual work.",
            }
        ],
    }


def _minimal_discovery_intent(intent_kind: str = "directed_discovery") -> dict[str, Any]:
    return {
        "intent_kind": intent_kind,
        "raw_user_instruction": "find market risk roles at mid-size banks",
        "profile_id": "prof_test001",
        "global_constraints": {
            "hard_constraints": ["max_years_experience: 3"],
            "soft_preferences": ["prefer mid-size firms"],
            "negative_preferences": [],
        },
        "search_lanes": [
            {
                "lane_id": "market_risk_banking",
                "hypothesis": "Profile's VaR/stress experience maps to market risk at banks.",
                "evidence_from_profile": ["VaR monitoring", "stress testing workflow"],
                "user_signal": "find market risk roles at mid-size banks",
                "strategy_signal": "",
                "query_seeds": ["market risk analyst bank", "VaR risk analytics associate"],
                "budget_share": 1.0,
            }
        ],
        "source_strategy": {
            "prefer_sources": [],
            "avoid_sources": [],
        },
        "translator_notes": {
            "assumptions": [],
            "missing_information": [],
            "translator_version": "1.0.0",
        },
    }


# ---------------------------------------------------------------------------
# Layer A — API layer
# ---------------------------------------------------------------------------

class TestDiscoveryRunsAPI:
    """FastAPI-level smoke tests for /api/discovery-runs."""

    @pytest.fixture()
    def data_root(self, tmp_path: Path) -> Path:
        return tmp_path / "data"

    @pytest.fixture()
    def client(self, data_root: Path, monkeypatch) -> TestClient:
        """TestClient with data root redirected to tmp_path."""
        monkeypatch.setattr(
            "career_intelligence.app_state.workspace_paths.get_data_root",
            lambda: data_root,
        )
        store = MetadataStore.from_data_root(data_root)
        store.init_schema()
        store.bootstrap_dev_workspace()
        return TestClient(app, raise_server_exceptions=True)

    @pytest.fixture()
    def profile_id(self, data_root: Path, monkeypatch) -> str:
        """Create a profile in the dev_default workspace and return its ID."""
        monkeypatch.setattr(
            "career_intelligence.services.profile_service.get_data_root",
            lambda: data_root,
        )
        monkeypatch.setattr(
            "career_intelligence.app_state.workspace_paths.get_data_root",
            lambda: data_root,
        )
        store = MetadataStore.from_data_root(data_root)
        store.init_schema()
        store.bootstrap_dev_workspace()
        ctx = RequestContext(workspace_id="dev_default", user_id="dev_user")
        profile = create_manual_profile(ctx, _minimal_profile_data())
        return profile["candidate_profile_id"]

    def test_enqueue_with_valid_profile_returns_202(
        self, client: TestClient, profile_id: str
    ) -> None:
        r = client.post(
            "/api/discovery-runs",
            json={
                "profile_id": profile_id,
                "user_instruction": "find market risk roles at mid-size banks",
                "requested_mode": "directed_discovery",
            },
            headers=_DEV_HEADERS,
        )
        assert r.status_code == 202, r.text
        body = r.json()
        assert "task_id" in body
        assert body["requested_mode"] == "directed_discovery"

    def test_enqueue_with_unknown_profile_returns_404(self, client: TestClient) -> None:
        r = client.post(
            "/api/discovery-runs",
            json={"profile_id": "prof_doesnotexist999"},
            headers=_DEV_HEADERS,
        )
        assert r.status_code == 404

    def test_enqueue_with_invalid_mode_returns_422(
        self, client: TestClient, profile_id: str
    ) -> None:
        r = client.post(
            "/api/discovery-runs",
            json={"profile_id": profile_id, "requested_mode": "bad_mode"},
            headers=_DEV_HEADERS,
        )
        assert r.status_code == 422

    def test_get_task_after_enqueue_returns_200(
        self, client: TestClient, profile_id: str
    ) -> None:
        enqueue_resp = client.post(
            "/api/discovery-runs",
            json={"profile_id": profile_id, "user_instruction": "test"},
            headers=_DEV_HEADERS,
        )
        assert enqueue_resp.status_code == 202
        task_id = enqueue_resp.json()["task_id"]

        get_resp = client.get(f"/api/discovery-runs/{task_id}", headers=_DEV_HEADERS)
        assert get_resp.status_code == 200
        task = get_resp.json()
        assert task["task_id"] == task_id
        assert task["status"] == "pending"

    def test_get_unknown_task_returns_404(self, client: TestClient) -> None:
        r = client.get("/api/discovery-runs/task_doesnotexist", headers=_DEV_HEADERS)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Layer B — Worker handler
# ---------------------------------------------------------------------------

class TestHandleNewPath:
    """Direct unit tests for apps.worker.handlers.search_run._handle_new_path."""

    CATALOG_ID = "dev"
    TASK_ID = "task_smoke_001"
    SESSION_ID = "2026-06-17_120000"

    @pytest.fixture()
    def data_root(self, tmp_path: Path) -> Path:
        return tmp_path / "data"

    @pytest.fixture()
    def workspace_root(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        return ws

    @pytest.fixture()
    def profile_id(self, data_root: Path) -> str:
        """Create a profile in the catalog workspace."""
        with patch(
            "career_intelligence.services.profile_service.get_data_root",
            return_value=data_root,
        ):
            store = MetadataStore.from_data_root(data_root)
            store.init_schema()
            ctx = RequestContext(workspace_id=self.CATALOG_ID, user_id="worker")
            profile = create_manual_profile(ctx, _minimal_profile_data())
        return profile["candidate_profile_id"]

    def _make_patches(
        self,
        data_root: Path,
        workspace_root: Path,
        mock_translate: Any,
        mock_rds: Any,
    ) -> list:
        """Return a list of patch context managers for _handle_new_path."""
        return [
            patch(
                "career_intelligence.services.profile_service.get_data_root",
                return_value=data_root,
            ),
            patch(
                "apps.worker.handlers.search_run.get_catalog_workspace_id",
                return_value=self.CATALOG_ID,
            ),
            patch(
                "apps.worker.handlers.search_run.get_workspace_paths",
                return_value=SimpleNamespace(root=workspace_root),
            ),
            patch(
                "apps.worker.handlers.search_run.get_repo_root",
                return_value=workspace_root,
            ),
            patch(
                "apps.worker.handlers.search_run.translate_intent",
                mock_translate,
            ),
            patch(
                "apps.worker.handlers.search_run.run_discovery_session",
                mock_rds,
            ),
        ]

    def _run_handler(
        self,
        profile_id: str,
        data_root: Path,
        workspace_root: Path,
        user_instruction: str = "find risk roles",
        requested_mode: str = "auto",
        mock_translate: Any = None,
        mock_rds: Any = None,
    ) -> dict[str, Any]:
        """Run _handle_new_path with all dependencies patched."""
        intent = _minimal_discovery_intent()
        if mock_translate is None:
            mock_translate = MagicMock(return_value=intent)

        # Pre-create the session dir so persist_artifacts can write into it.
        session_run_dir = workspace_root / "runs" / self.SESSION_ID
        session_run_dir.mkdir(parents=True, exist_ok=True)

        if mock_rds is None:
            mock_rds = MagicMock(return_value={
                "session_id": self.SESSION_ID,
                "jobs_saved": 2,
                "queries_run": 5,
                "search_complete": True,
                "candidates_captured": 3,
            })

        patches = self._make_patches(data_root, workspace_root, mock_translate, mock_rds)
        for p in patches:
            p.start()
        try:
            return _handle_new_path(
                self.TASK_ID,
                {
                    "profile_id": profile_id,
                    "user_instruction": user_instruction,
                    "requested_mode": requested_mode,
                    "max_queries": 20,
                    "max_pages": 30,
                },
            )
        finally:
            for p in reversed(patches):
                p.stop()

    def test_translate_intent_called_with_profile_and_instruction(
        self, profile_id: str, data_root: Path, workspace_root: Path
    ) -> None:
        """translate_intent receives the resolved profile + instruction + mode."""
        mock_translate = MagicMock(return_value=_minimal_discovery_intent())

        self._run_handler(
            profile_id, data_root, workspace_root,
            user_instruction="find mid-size bank roles",
            requested_mode="directed_discovery",
            mock_translate=mock_translate,
        )

        mock_translate.assert_called_once()
        kwargs = mock_translate.call_args.kwargs
        assert kwargs["user_instruction"] == "find mid-size bank roles"
        assert kwargs["requested_mode"] == "directed_discovery"
        # profile is resolved from DB — check it contains the profile_id
        assert kwargs["profile"]["candidate_profile_id"] == profile_id

    def test_run_discovery_session_receives_discovery_intent(
        self, profile_id: str, data_root: Path, workspace_root: Path
    ) -> None:
        """run_discovery_session is called with the DiscoveryIntent from translate_intent."""
        fixed_intent = _minimal_discovery_intent("profile_based_exploration")
        mock_translate = MagicMock(return_value=fixed_intent)
        mock_rds = MagicMock(return_value={
            "session_id": self.SESSION_ID,
            "jobs_saved": 1,
            "queries_run": 3,
            "search_complete": True,
            "candidates_captured": 1,
        })

        self._run_handler(
            profile_id, data_root, workspace_root,
            mock_translate=mock_translate,
            mock_rds=mock_rds,
        )

        mock_rds.assert_called_once()
        kwargs = mock_rds.call_args.kwargs
        assert kwargs["discovery_intent"] == fixed_intent
        assert kwargs["discovery_intent"]["intent_kind"] == "profile_based_exploration"

    def test_translator_artifacts_persisted_to_session_dir(
        self, profile_id: str, data_root: Path, workspace_root: Path
    ) -> None:
        """translator_input.json and discovery_intent.json are written to the session dir."""
        result = self._run_handler(profile_id, data_root, workspace_root)

        assert result["session_id"] == self.SESSION_ID
        assert result["jobs_saved"] == 2

        session_root = workspace_root / "runs" / self.SESSION_ID
        input_file = session_root / "translator_input.json"
        intent_file = session_root / "discovery_intent.json"

        assert input_file.exists(), "translator_input.json was not persisted"
        assert intent_file.exists(), "discovery_intent.json was not persisted"

        saved_intent = json.loads(intent_file.read_text())
        assert saved_intent["intent_kind"] == "directed_discovery"
        assert "search_lanes" in saved_intent
