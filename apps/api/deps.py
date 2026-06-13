"""
FastAPI dependencies — injected into route handlers.

Session cookie → RequestContext flow:
  1. Browser sends session cookie "sid" on every request.
  2. get_ctx() looks up sid hash in browser_sessions table.
  3. Returns a RequestContext(workspace_id, user_id, session_id).
  4. Unauthenticated requests get HTTP 401.

Dev / CLI override:
  When the X-Dev-Context header is present and the server is NOT in
  production mode (checked via DEV_MODE env var), the dependency accepts
  a dev context directly — useful for curl testing without a browser session.
"""

from __future__ import annotations

import hashlib
import os
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status

from career_intelligence.app_state.context import DEV_CTX, RequestContext
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import get_data_root

# Secure by default: the X-Dev-Context auth bypass is OFF unless DEV_MODE=1 is
# explicitly set, and it is ALWAYS disabled when ENV=production — so a forgotten
# DEV_MODE=1 in a prod deploy can never open an auth hole.
_IS_PRODUCTION = os.getenv("ENV", "development").lower() == "production"
_DEV_MODE = os.getenv("DEV_MODE", "0") == "1" and not _IS_PRODUCTION


def get_store() -> MetadataStore:
    store = MetadataStore.from_data_root(get_data_root())
    store.init_schema()
    return store


def get_ctx(
    sid: Annotated[str | None, Cookie()] = None,
    x_dev_context: Annotated[str | None, Header()] = None,
    store: MetadataStore = Depends(get_store),
) -> RequestContext:
    """
    Resolve a RequestContext from the session cookie.

    In DEV_MODE, passing the header X-Dev-Context: dev skips auth and
    returns DEV_CTX — safe for local curl testing.
    """
    if _DEV_MODE and x_dev_context == "dev":
        store.bootstrap_dev_workspace()
        return DEV_CTX

    if not sid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    sid_hash = hashlib.sha256(sid.encode()).hexdigest()
    with store._conn() as conn:
        row = conn.execute(
            """
            SELECT workspace_id, user_id, session_id, expires_at
            FROM browser_sessions
            WHERE session_token_hash = ?
            """,
            (sid_hash,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    from datetime import datetime, timezone
    if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc).isoformat():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    return RequestContext(
        workspace_id=row["workspace_id"],
        user_id=row["user_id"],
        session_id=row["session_id"],
    )


CtxDep = Annotated[RequestContext, Depends(get_ctx)]
StoreDep = Annotated[MetadataStore, Depends(get_store)]
