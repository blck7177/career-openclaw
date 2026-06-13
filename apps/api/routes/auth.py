"""
Auth routes.

POST /auth/invite   — validate invite code, create workspace+user, set session cookie
GET  /auth/me       — return current workspace/user from session cookie
DELETE /auth/logout — clear session cookie

Invite code flow:
  1. Client POSTs {"code": "<raw invite code>"}.
  2. Server SHA-256 hashes the code, looks it up in invite_codes table.
  3. On match: create workspace + user if new, create session, set cookie.
  4. Response: {"workspace_id": ..., "user_id": ...}

Auth is intentionally minimal — no JWT, no OAuth.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from apps.api.deps import CtxDep, StoreDep, get_store
from career_intelligence.app_state.metadata_store import MetadataStore

router = APIRouter(prefix="/auth", tags=["auth"])

_SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "30"))
_COOKIE_NAME = "sid"
# Secure cookies default ON in production (HTTPS), OFF otherwise (local http dev),
# and remain explicitly overridable via COOKIE_SECURE.
_IS_PRODUCTION = os.getenv("ENV", "development").lower() == "production"
_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1" if _IS_PRODUCTION else "0") == "1"


class InviteRequest(BaseModel):
    code: str


class AuthResponse(BaseModel):
    workspace_id: str
    user_id: str


@router.post("/invite", response_model=AuthResponse)
def redeem_invite(
    body: InviteRequest,
    response: Response,
    store: StoreDep,
) -> dict[str, Any]:
    """
    Validate an invite code and create a session.

    Returns workspace/user info and sets a session cookie.
    """
    code_hash = hashlib.sha256(body.code.encode()).hexdigest()

    with store._conn() as conn:
        row = conn.execute(
            """
            SELECT id, workspace_id, max_uses, used_count, expires_at, status
            FROM invite_codes
            WHERE code_hash = ?
            """,
            (code_hash,),
        ).fetchone()

    if row is None or row["status"] != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid invite code")

    if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc).isoformat():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invite code expired")

    if row["used_count"] >= row["max_uses"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invite code exhausted")

    workspace_id = row["workspace_id"]
    store.get_or_create_workspace(workspace_id)

    user_id = "user_" + uuid.uuid4().hex[:8]
    store.get_or_create_user(user_id, workspace_id)

    with store._conn() as conn:
        new_count = row["used_count"] + 1
        new_status = "exhausted" if new_count >= row["max_uses"] else "active"
        conn.execute(
            "UPDATE invite_codes SET used_count = ?, status = ? WHERE id = ?",
            (new_count, new_status, row["id"]),
        )

    session_token = secrets.token_urlsafe(32)
    session_id = "sess_" + uuid.uuid4().hex[:10]
    token_hash = hashlib.sha256(session_token.encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=_SESSION_TTL_DAYS)).isoformat()

    with store._conn() as conn:
        conn.execute(
            """
            INSERT INTO browser_sessions
                (session_id, user_id, workspace_id, session_token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, workspace_id, token_hash, expires_at,
             datetime.now(timezone.utc).isoformat()),
        )

    response.set_cookie(
        key=_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        max_age=_SESSION_TTL_DAYS * 86400,
    )
    return {"workspace_id": workspace_id, "user_id": user_id}


@router.get("/me", response_model=AuthResponse)
def get_me(ctx: CtxDep) -> dict[str, Any]:
    """Return the currently authenticated workspace and user."""
    return {"workspace_id": ctx.workspace_id, "user_id": ctx.user_id}


@router.delete("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(key=_COOKIE_NAME)
