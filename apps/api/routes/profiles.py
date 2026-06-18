"""
Profile routes — Sprint 4-lite.

POST /api/profiles              — create a manual candidate profile
GET  /api/profiles              — list profiles for the workspace
GET  /api/profiles/{profile_id} — profile detail
PUT  /api/profiles/{profile_id} — update an existing profile (in-place edit)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from apps.api.deps import CtxDep
from career_intelligence.services import profile_service

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_profile(body: dict[str, Any], ctx: CtxDep) -> dict[str, Any]:
    """
    Create a manual candidate profile.

    Supply content fields only — candidate_profile_id, workspace_id,
    created_at, and profile_version are injected server-side.

    Returns the full saved profile dict.
    """
    try:
        return profile_service.create_manual_profile(ctx, body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("")
def list_profiles(ctx: CtxDep) -> list[dict[str, Any]]:
    """List all candidate profiles for the current workspace, newest first."""
    return profile_service.list_profiles(ctx)


@router.get("/{profile_id}")
def get_profile(profile_id: str, ctx: CtxDep) -> dict[str, Any]:
    """Return a single candidate profile."""
    profile = profile_service.get_profile(ctx, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile not found: {profile_id}",
        )
    return profile


@router.put("/{profile_id}")
def update_profile(profile_id: str, body: dict[str, Any], ctx: CtxDep) -> dict[str, Any]:
    """
    Update an existing candidate profile.

    Supply only the fields you want to change — they are merged onto the
    persisted profile.  candidate_profile_id, workspace_id, and created_at
    are always preserved.  profile_version is refreshed, which invalidates
    any cached Fit Reports generated against the old profile data.

    Returns the full updated profile dict.
    """
    try:
        return profile_service.update_profile(ctx, profile_id, body)
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
