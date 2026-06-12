"""
app_state — workspace context, path resolution, and metadata storage.

Public surface:
    RequestContext   — carries workspace_id, user_id, session_id
    DEV_CTX          — default context for local CLI / dev usage
    WorkspacePaths   — all workspace-scoped filesystem paths
    GlobalPaths      — all global (cross-workspace) filesystem paths
    MetadataStore    — SQLite metadata CRUD
    get_data_root()  — repo-relative data/ directory
    get_repo_root()  — repo root Path
"""

from career_intelligence.app_state.context import DEV_CTX, RequestContext
from career_intelligence.app_state.workspace_paths import GlobalPaths, WorkspacePaths
from career_intelligence.app_state.metadata_store import MetadataStore

__all__ = [
    "RequestContext",
    "DEV_CTX",
    "WorkspacePaths",
    "GlobalPaths",
    "MetadataStore",
]
