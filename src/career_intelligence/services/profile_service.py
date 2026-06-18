"""
ProfileService — create and query workspace-scoped Candidate Profiles.

Profiles are created manually (no resume upload required).  Each profile is
persisted as a JSON file on the filesystem and indexed in MetadataStore.

Artifact layout:
    data/workspaces/<workspace_id>/profiles/<candidate_profile_id>.json

Design:
  - profile_version is injected at creation time so profile_hash naturally
    includes it.  Bumping FIT_PROFILE_VERSION invalidates all cached Fit
    Reports that were generated with an older version.
  - Schema validation uses jsonschema against candidate_profile.schema.json.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import (
    get_data_root,
    get_workspace_paths,
)

# Bump this when the prompt interpretation of profile fields changes — doing so
# will cause profile_hash to change, automatically invalidating all Fit Report
# cache entries generated with the old version.
FIT_PROFILE_VERSION = "0.1.0"

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "schemas" / "candidate_profile.schema.json"
)


def _load_schema() -> dict[str, Any]:
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _store() -> MetadataStore:
    store = MetadataStore.from_data_root(get_data_root())
    store.init_schema()
    return store


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_manual_profile(
    ctx: RequestContext,
    profile_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Validate and persist a manually-entered candidate profile.

    Injects candidate_profile_id, workspace_id, created_at, and
    profile_version before validation, so callers only need to supply
    the content fields.

    Returns the saved profile dict.

    Raises:
        ValueError — if profile_data fails schema validation.
    """
    data_root = get_data_root()
    ws_paths = get_workspace_paths(ctx.workspace_id, data_root)

    candidate_profile_id = "prof_" + uuid.uuid4().hex[:10]
    now = datetime.now(timezone.utc).isoformat()

    profile = dict(profile_data)
    profile["candidate_profile_id"] = candidate_profile_id
    profile["workspace_id"] = ctx.workspace_id
    profile["created_at"] = now
    profile["profile_version"] = FIT_PROFILE_VERSION

    # Validate against schema
    schema = _load_schema()
    try:
        jsonschema.validate(instance=profile, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"Profile validation failed: {exc.message}") from exc

    # Write to filesystem
    ws_paths.profiles_dir.mkdir(parents=True, exist_ok=True)
    profile_path = ws_paths.candidate_profile_path(candidate_profile_id)
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

    # Index in MetadataStore
    store = MetadataStore.from_data_root(data_root)
    store.init_schema()
    store.insert_candidate_profile(
        workspace_id=ctx.workspace_id,
        profile_path=str(profile_path),
        candidate_profile_id=candidate_profile_id,
    )

    return profile


def get_profile(
    ctx: RequestContext,
    profile_id: str,
) -> dict[str, Any] | None:
    """
    Load and return a candidate profile JSON from the filesystem.

    Returns None if the profile does not exist in MetadataStore or the
    file is missing.
    """
    data_root = get_data_root()
    store = MetadataStore.from_data_root(data_root)
    store.init_schema()

    row = store.get_candidate_profile(profile_id)
    if row is None:
        return None

    profile_path = Path(row["profile_path"])
    if not profile_path.exists():
        return None

    return json.loads(profile_path.read_text(encoding="utf-8"))


def update_profile(
    ctx: RequestContext,
    profile_id: str,
    profile_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing candidate profile in-place.

    Merges the supplied fields onto the persisted profile, preserving
    candidate_profile_id, workspace_id, and created_at.  profile_version is
    refreshed to FIT_PROFILE_VERSION so that stale Fit Report caches are
    automatically invalidated after an edit.

    Returns the updated profile dict.

    Raises:
        ValueError — if profile_id does not exist, belongs to a different
            workspace, or the merged data fails schema validation.
    """
    data_root = get_data_root()
    store = MetadataStore.from_data_root(data_root)
    store.init_schema()

    row = store.get_candidate_profile(profile_id)
    if row is None:
        raise ValueError(f"Profile not found: {profile_id}")

    profile_path = Path(row["profile_path"])
    if not profile_path.exists():
        raise ValueError(f"Profile file missing on disk: {profile_id}")

    existing = json.loads(profile_path.read_text(encoding="utf-8"))
    if existing.get("workspace_id") != ctx.workspace_id:
        raise ValueError(f"Profile not found: {profile_id}")

    # Merge: start from existing, overlay incoming fields, lock immutable keys.
    merged = {**existing, **profile_data}
    merged["candidate_profile_id"] = existing["candidate_profile_id"]
    merged["workspace_id"] = existing["workspace_id"]
    merged["created_at"] = existing["created_at"]
    merged["profile_version"] = FIT_PROFILE_VERSION

    schema = _load_schema()
    try:
        jsonschema.validate(instance=merged, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"Profile validation failed: {exc.message}") from exc

    profile_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def list_profiles(
    ctx: RequestContext,
) -> list[dict[str, Any]]:
    """
    List all candidate profiles for this workspace, newest first.

    Profiles that exist in MetadataStore but whose files are missing on disk
    are silently excluded.
    """
    data_root = get_data_root()
    store = MetadataStore.from_data_root(data_root)
    store.init_schema()

    rows = store.list_candidate_profiles(ctx.workspace_id)
    profiles = []
    for row in rows:
        path = Path(row["profile_path"])
        if path.exists():
            try:
                profiles.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
    return profiles
