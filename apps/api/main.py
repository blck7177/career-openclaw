"""
Career OpenClaw API — FastAPI application entry point.

Start with:
    uvicorn apps.api.main:app --reload --port 8000

Or from the repo root:
    .venv/bin/uvicorn apps.api.main:app --reload
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes import auth, jobs, reports, runs
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import get_data_root

_CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    On startup: initialise SQLite schema and bootstrap the dev workspace.
    On shutdown: nothing (SQLite connections are per-request).
    """
    store = MetadataStore.from_data_root(get_data_root())
    store.init_schema()
    store.bootstrap_dev_workspace()
    yield


app = FastAPI(
    title="Career OpenClaw API",
    description="Job intelligence backend — read-only in Sprint 1",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(runs.router)
app.include_router(reports.router)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}
