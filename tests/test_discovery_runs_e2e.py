"""
End-to-end smoke tests for the POST /api/discovery-runs → Intent Translator → ObjectiveController pipeline.

Layer A — API layer (FastAPI TestClient):
    POST /api/discovery-runs with valid profile  → 202, task_id returned
    POST /api/discovery-runs with valid profile + structured params → 202
    POST /api/discovery-runs with unknown profile → 404
    POST /api/discovery-runs with invalid mode   → 422
    GET  /api/discovery-runs/{task_id} (valid)   → 200, task dict
    GET  /api/discovery-runs/{task_id} (unknown) → 404

Layer B — Worker handler (_handle_new_path):
    translate_intent called with profile + instruction
    ObjectiveController.run receives the discovery_intent from the translator
    source_workspace_id is passed in task payload and used for profile lookup
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
from career_intelligence.objective_controller import SearchObjective
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
            "hard_constraints": [{"value": "max_years_experience: 3", "source": "user_explicit"}],
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
        # task_service imports get_data_root directly, so it must be patched
        # separately to ensure count_active_tasks / create_task use the test DB.
        monkeypatch.setattr(
            "career_intelligence.services.task_service.get_data_root",
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
        assert "run_id" in body
        assert body["run_id"].startswith("run_")
        assert body["requested_mode"] == "directed_discovery"

    def test_enqueue_with_structured_params_returns_202(
        self, client: TestClient, profile_id: str
    ) -> None:
        """New v2 fields (search_params, target_new_jobs, search_depth) are accepted."""
        r = client.post(
            "/api/discovery-runs",
            json={
                "profile_id": profile_id,
                "search_mode": "directed_discovery",
                "search_params": {
                    "location": ["NYC", "Jersey City"],
                    "seniority": ["Analyst", "Associate"],
                    "max_years_experience": 3,
                    "workstreams": ["Market Risk"],
                    "exclusions": ["model_validation"],
                },
                "target_new_jobs": 10,
                "search_depth": "balanced",
                "additional_instruction": "Prefer direct company postings.",
            },
            headers=_DEV_HEADERS,
        )
        assert r.status_code == 202, r.text
        body = r.json()
        assert "task_id" in body

    def test_task_payload_contains_source_workspace_id(
        self, client: TestClient, profile_id: str, data_root: Path
    ) -> None:
        """source_workspace_id must be in the task payload so workers can load profiles."""
        from career_intelligence.app_state.metadata_store import MetadataStore
        from career_intelligence.services.task_service import get_task

        r = client.post(
            "/api/discovery-runs",
            json={"profile_id": profile_id},
            headers=_DEV_HEADERS,
        )
        assert r.status_code == 202, r.text
        task_id = r.json()["task_id"]

        # Use monkeypatched data_root to resolve the task
        with patch(
            "career_intelligence.services.task_service.get_data_root",
            return_value=data_root,
        ):
            task = get_task(task_id)

        assert task is not None
        assert "source_workspace_id" in task["payload"]
        assert task["payload"]["source_workspace_id"] == "dev_default"

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

    def test_second_enqueue_returns_409(
        self, client: TestClient, profile_id: str
    ) -> None:
        """A second discovery run for the same workspace is rejected with 409."""
        payload = {
            "profile_id": profile_id,
            "user_instruction": "find risk roles",
            "requested_mode": "directed_discovery",
        }

        r1 = client.post("/api/discovery-runs", json=payload, headers=_DEV_HEADERS)
        assert r1.status_code == 202, r1.text

        r2 = client.post("/api/discovery-runs", json=payload, headers=_DEV_HEADERS)
        assert r2.status_code == 409, r2.text
        assert "already" in r2.json()["detail"].lower()

    def test_instruction_only_empty_returns_422(
        self, client: TestClient, profile_id: str, data_root: Path
    ) -> None:
        """instruction_only with no filters and no instruction must be rejected with 422.

        No task should be created — the guard fires before task_service.create_task().
        """
        from career_intelligence.services.task_service import list_tasks
        from career_intelligence.app_state.context import RequestContext as RC

        ctx = RC(workspace_id="dev_default", user_id="dev_user")

        with patch("career_intelligence.services.task_service.get_data_root", return_value=data_root):
            before = len(list_tasks(ctx))

        r = client.post(
            "/api/discovery-runs",
            json={
                "profile_id": profile_id,
                "search_source": "instruction_only",
                # All search_params fields omitted → defaults to empty
                # additional_instruction and user_instruction omitted → empty
            },
            headers=_DEV_HEADERS,
        )
        assert r.status_code == 422, r.text
        detail = r.json().get("detail", "")
        assert "instruction_only" in detail.lower() or "instruction" in detail.lower()

        # Verify no task was created by the failed request
        with patch("career_intelligence.services.task_service.get_data_root", return_value=data_root):
            after = len(list_tasks(ctx))
        assert after == before


# ---------------------------------------------------------------------------
# Unit tests for _compile_instruction helper
# ---------------------------------------------------------------------------


def test_compile_instruction_empty() -> None:
    """_compile_instruction with all-default SearchParams and empty text returns ''."""
    from apps.api.routes.discovery_runs import _compile_instruction, SearchParams

    assert _compile_instruction(SearchParams(), "") == ""


def test_compile_instruction_flexible_remote_not_included() -> None:
    """remote_policy='flexible' (the default) is not written into the instruction."""
    from apps.api.routes.discovery_runs import _compile_instruction, SearchParams

    result = _compile_instruction(SearchParams(remote_policy="flexible"), "")
    assert "flexible" not in result
    assert result == ""


def test_compile_instruction_non_flexible_remote_included() -> None:
    """Non-flexible remote_policy IS written into the instruction."""
    from apps.api.routes.discovery_runs import _compile_instruction, SearchParams

    result = _compile_instruction(SearchParams(remote_policy="remote"), "")
    assert "remote" in result.lower()


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

    def _make_final_result_dict(self) -> dict[str, Any]:
        """Fake FinalSearchResult.to_dict() return value."""
        return {
            "objective_id": self.TASK_ID,
            "target_new_jobs": 10,
            "attempts_run": 1,
            "objective_status": "met",
            "objective_reason": "Objective met: 10/10 new jobs inserted.",
            "new_jobs_inserted": 10,
            "existing_jobs_updated": 0,
            "possible_duplicates": 0,
            "jobs_failed": 0,
            "candidates_captured": 12,
            "queries_run": 15,
            "duration_seconds": 30.0,
            "attempt_summaries": [
                {
                    "attempt_number": 1,
                    "session_id": self.SESSION_ID,
                    "new_jobs_inserted": 10,
                    "existing_jobs_updated": 0,
                    "possible_duplicates": 0,
                    "jobs_failed": 0,
                    "candidates_captured": 12,
                    "queries_run": 15,
                    "duration_seconds": 30.0,
                }
            ],
            "jobs_saved": 10,
            "session_id": self.SESSION_ID,
            "run_id": self.SESSION_ID,
        }

    def _make_patches(
        self,
        data_root: Path,
        workspace_root: Path,
        mock_translate: Any,
        mock_controller_run: Any,
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
                "apps.worker.handlers.search_run.ObjectiveController.run",
                mock_controller_run,
            ),
            # LLM client returns None for unit tests (FollowupPlanner uses deterministic fallback)
            patch(
                "apps.worker.handlers.search_run.make_client",
                return_value=None,
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
        mock_controller_run: Any = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run _handle_new_path with all dependencies patched."""
        intent = _minimal_discovery_intent()
        if mock_translate is None:
            mock_translate = MagicMock(return_value=intent)

        # Pre-create the session dir so persist_artifacts can write into it.
        session_run_dir = workspace_root / "runs" / self.SESSION_ID
        session_run_dir.mkdir(parents=True, exist_ok=True)

        if mock_controller_run is None:
            fake_final = MagicMock()
            fake_final.to_dict.return_value = self._make_final_result_dict()
            fake_final.last_session_id = self.SESSION_ID
            mock_controller_run = MagicMock(return_value=fake_final)

        patches = self._make_patches(data_root, workspace_root, mock_translate, mock_controller_run)
        for p in patches:
            p.start()
        try:
            payload: dict[str, Any] = {
                "profile_id": profile_id,
                "source_workspace_id": self.CATALOG_ID,
                "user_instruction": user_instruction,
                "requested_mode": requested_mode,
                "max_queries": 20,
                "max_pages": 30,
            }
            if extra_payload:
                payload.update(extra_payload)
            return _handle_new_path(self.TASK_ID, payload)
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
        assert kwargs["profile"]["candidate_profile_id"] == profile_id

    def test_objective_controller_receives_discovery_intent(
        self, profile_id: str, data_root: Path, workspace_root: Path
    ) -> None:
        """ObjectiveController.run is called with the DiscoveryIntent from translate_intent."""
        fixed_intent = _minimal_discovery_intent("profile_based_exploration")
        mock_translate = MagicMock(return_value=fixed_intent)

        captured_calls: list[dict[str, Any]] = []

        def fake_controller_run(self_ref, **kwargs: Any):  # noqa: ANN001
            captured_calls.append(kwargs)
            fake = MagicMock()
            fake.to_dict.return_value = {
                **TestHandleNewPath()._make_final_result_dict(),
                "session_id": TestHandleNewPath.SESSION_ID,
            }
            fake.last_session_id = TestHandleNewPath.SESSION_ID
            return fake

        patches_base = [
            patch("career_intelligence.services.profile_service.get_data_root", return_value=data_root),
            patch("apps.worker.handlers.search_run.get_catalog_workspace_id", return_value=self.CATALOG_ID),
            patch("apps.worker.handlers.search_run.get_workspace_paths", return_value=SimpleNamespace(root=workspace_root)),
            patch("apps.worker.handlers.search_run.get_repo_root", return_value=workspace_root),
            patch("apps.worker.handlers.search_run.translate_intent", mock_translate),
            patch("apps.worker.handlers.search_run.make_client", return_value=None),
            patch("career_intelligence.objective_controller.ObjectiveController.run", fake_controller_run),
        ]
        session_run_dir = workspace_root / "runs" / self.SESSION_ID
        session_run_dir.mkdir(parents=True, exist_ok=True)

        for p in patches_base:
            p.start()
        try:
            _handle_new_path(
                self.TASK_ID,
                {
                    "profile_id": profile_id,
                    "source_workspace_id": self.CATALOG_ID,
                    "user_instruction": "test",
                    "requested_mode": "auto",
                    "max_queries": 20,
                    "max_pages": 30,
                },
            )
        finally:
            for p in reversed(patches_base):
                p.stop()

        assert len(captured_calls) == 1
        assert captured_calls[0]["discovery_intent"]["intent_kind"] == "profile_based_exploration"

    def test_translator_artifacts_persisted_to_session_dir(
        self, profile_id: str, data_root: Path, workspace_root: Path
    ) -> None:
        """translator_input.json and discovery_intent.json are written to the session dir."""
        result = self._run_handler(profile_id, data_root, workspace_root)

        assert result["session_id"] == self.SESSION_ID
        assert result["new_jobs_inserted"] == 10

        session_root = workspace_root / "runs" / self.SESSION_ID
        input_file = session_root / "translator_input.json"
        intent_file = session_root / "discovery_intent.json"

        assert input_file.exists(), "translator_input.json was not persisted"
        assert intent_file.exists(), "discovery_intent.json was not persisted"

        saved_intent = json.loads(intent_file.read_text())
        assert saved_intent["intent_kind"] == "directed_discovery"
        assert "search_lanes" in saved_intent

    def test_target_new_jobs_passed_to_objective(
        self, profile_id: str, data_root: Path, workspace_root: Path
    ) -> None:
        """target_new_jobs from payload reaches the SearchObjective."""
        created_objectives: list[SearchObjective] = []
        orig_from_intent = SearchObjective.from_intent_and_request

        def capture_objective(**kwargs):  # noqa: ANN001
            obj = orig_from_intent(**kwargs)
            created_objectives.append(obj)
            return obj

        with patch(
            "apps.worker.handlers.search_run.SearchObjective.from_intent_and_request",
            side_effect=capture_objective,
        ):
            self._run_handler(
                profile_id, data_root, workspace_root,
                extra_payload={"target_new_jobs": 15},
            )

        assert len(created_objectives) == 1
        assert created_objectives[0].target_new_jobs == 15
