"""
RequestContext — the minimal identity envelope passed through the service layer.

Rules:
- Core analyzers (role_analyzer, extractor, classifier, etc.) do NOT receive ctx.
- Service functions (job_service, run_service, report_service, etc.) take ctx
  as their first argument.
- Storage/path helpers derive filesystem paths from ctx.workspace_id.
- CLI tools default to DEV_CTX when no HTTP session is available.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RequestContext:
    """
    Immutable identity context for a single request or CLI invocation.

    workspace_id : the data isolation unit (e.g. "dev_default", "workspace_abc123")
    user_id      : the user within the workspace (e.g. "dev_user", "user_7f3a")
    session_id   : optional browser/API session token reference (not the raw token)
    """

    workspace_id: str
    user_id: str
    session_id: str | None = field(default=None)

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("workspace_id must not be empty")
        if not self.user_id:
            raise ValueError("user_id must not be empty")


# Default context for local development and CLI usage.
# All wrappers and CLI tools use this when running outside an HTTP request.
DEV_CTX = RequestContext(workspace_id="dev_default", user_id="dev_user")
