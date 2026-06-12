"""
Tests for profile_service.

Strategy:
  - Patch get_data_root() at its usage site in profile_service.
  - Use tmp_path for filesystem isolation.
  - No module reload — patches applied to name bindings in profile_service's namespace.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import career_intelligence.services.profile_service as svc
from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import WorkspacePaths
from career_intelligence.services.profile_service import FIT_PROFILE_VERSION


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
def store(data_root: Path) -> MetadataStore:
    s = MetadataStore.from_data_root(data_root)
    s.init_schema()
    return s


def _minimal_profile() -> dict:
    """Minimal valid profile payload (no id/workspace/timestamps — injected server-side)."""
    return {
        "years_experience": 4,
        "current_background": "Risk analyst at a bulge bracket bank, focused on market risk.",
        "domain_experience": ["Market Risk", "Valuation Control"],
        "technical_skills": ["Python", "SQL"],
        "analytical_methods": ["VaR", "Stress Testing"],
        "finance_domains": ["Equities", "Fixed Income"],
        "tools": ["Excel", "Bloomberg"],
        "representative_projects": [
            {
                "title": "VaR Model Overhaul",
                "description": "Rebuilt historical VaR calculation pipeline in Python.",
                "skills_used": ["Python", "VaR"],
                "quantified_impact": "Reduced run time by 60%.",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCreateManualProfile:

    def test_creates_profile_writes_file_and_indexes(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """Happy path: profile is saved to disk and MetadataStore."""
        with patch("career_intelligence.services.profile_service.get_data_root", return_value=data_root):
            result = svc.create_manual_profile(ctx, _minimal_profile())

        assert result["candidate_profile_id"].startswith("prof_")
        assert result["workspace_id"] == ctx.workspace_id
        assert result["profile_version"] == FIT_PROFILE_VERSION
        assert "created_at" in result

        # File exists on disk
        ws = WorkspacePaths(data_root, ctx.workspace_id)
        profile_path = ws.candidate_profile_path(result["candidate_profile_id"])
        assert profile_path.exists(), "profile JSON not written to disk"

        saved = json.loads(profile_path.read_text())
        assert saved["years_experience"] == 4

        # MetadataStore row exists
        store = MetadataStore.from_data_root(data_root)
        row = store.get_candidate_profile(result["candidate_profile_id"])
        assert row is not None
        assert row["workspace_id"] == ctx.workspace_id

    def test_injects_profile_version(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """profile_version is always injected regardless of caller input."""
        payload = _minimal_profile()
        payload["profile_version"] = "99.0.0"  # should be overwritten

        with patch("career_intelligence.services.profile_service.get_data_root", return_value=data_root):
            result = svc.create_manual_profile(ctx, payload)

        assert result["profile_version"] == FIT_PROFILE_VERSION

    def test_missing_required_field_raises_value_error(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """Missing required field causes ValidationError wrapped as ValueError."""
        payload = _minimal_profile()
        del payload["years_experience"]

        with patch("career_intelligence.services.profile_service.get_data_root", return_value=data_root):
            with pytest.raises(ValueError, match="Profile validation failed"):
                svc.create_manual_profile(ctx, payload)

    def test_missing_representative_projects_raises(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """representative_projects is required."""
        payload = _minimal_profile()
        del payload["representative_projects"]

        with patch("career_intelligence.services.profile_service.get_data_root", return_value=data_root):
            with pytest.raises(ValueError, match="Profile validation failed"):
                svc.create_manual_profile(ctx, payload)


class TestGetProfile:

    def test_returns_profile_dict(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """get_profile returns the full profile after creation."""
        with patch("career_intelligence.services.profile_service.get_data_root", return_value=data_root):
            created = svc.create_manual_profile(ctx, _minimal_profile())
            result = svc.get_profile(ctx, created["candidate_profile_id"])

        assert result is not None
        assert result["candidate_profile_id"] == created["candidate_profile_id"]
        assert result["years_experience"] == 4

    def test_returns_none_for_missing_id(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """get_profile returns None when the profile_id does not exist."""
        # Ensure MetadataStore is initialised
        MetadataStore.from_data_root(data_root).init_schema()

        with patch("career_intelligence.services.profile_service.get_data_root", return_value=data_root):
            result = svc.get_profile(ctx, "prof_doesnotexist")

        assert result is None


class TestListProfiles:

    def test_returns_profiles_newest_first(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """list_profiles returns all profiles for the workspace, newest first."""
        payload1 = _minimal_profile()
        payload1["display_name"] = "Profile A"
        payload2 = _minimal_profile()
        payload2["display_name"] = "Profile B"

        with patch("career_intelligence.services.profile_service.get_data_root", return_value=data_root):
            p1 = svc.create_manual_profile(ctx, payload1)
            p2 = svc.create_manual_profile(ctx, payload2)
            profiles = svc.list_profiles(ctx)

        assert len(profiles) == 2
        ids = [p["candidate_profile_id"] for p in profiles]
        # Newest first: p2 was created after p1
        assert ids[0] == p2["candidate_profile_id"]
        assert ids[1] == p1["candidate_profile_id"]

    def test_empty_workspace_returns_empty_list(
        self, data_root: Path, ctx: RequestContext
    ) -> None:
        """list_profiles returns [] when no profiles exist."""
        MetadataStore.from_data_root(data_root).init_schema()

        with patch("career_intelligence.services.profile_service.get_data_root", return_value=data_root):
            result = svc.list_profiles(ctx)

        assert result == []
