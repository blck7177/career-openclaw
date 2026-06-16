"""
Canonical enums for persisted JobRecord fields — the single source of truth.

Why this module exists
----------------------
``source_type`` and ``fetch_status`` were defined in three independent places
that silently drifted apart:

  * the connector layer (``connectors/base.py``, the ATS connectors) — what is
    actually *produced*;
  * ``runner.py`` — what is *written* into the record; and
  * ``schemas/job_record.schema.json`` — what is *allowed* into the catalog.

The drift was not theoretical: connectors emit ``fetch_status="partial_success"``
(a fetch that succeeded but yielded a thin JD) and ``source_type="html"`` (the
HTML fallback), neither of which was in the schema enum. Such records failed
``validate_record`` purely on an enum mismatch and were dropped at the
Process → DB boundary — a definitional bug, not a quality decision.

This module centralizes those enums. ``schemas/job_record.schema.json`` must
stay aligned with the values here; ``tests/test_record_enum_contracts.py`` locks
that alignment so the schema can never drift from the producers again.

Note: the candidate-pool fetch lifecycle (``pending/success/failed/skipped`` in
``candidate_pool_entry.schema.json``) is a *different* state machine — it tracks
whether a candidate URL has been fetched yet, not the outcome of a JobRecord
fetch — and is intentionally not unified here.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# fetch_status — outcome of fetching a single JD for a persisted JobRecord
# ---------------------------------------------------------------------------

FETCH_STATUS_SUCCESS = "success"
FETCH_STATUS_PARTIAL = "partial_success"
FETCH_STATUS_FAILED = "failed"
FETCH_STATUS_MANUAL = "manual"

#: Every fetch_status a persisted JobRecord may carry (== schema enum).
JOB_RECORD_FETCH_STATUSES: tuple[str, ...] = (
    FETCH_STATUS_SUCCESS,
    FETCH_STATUS_PARTIAL,
    FETCH_STATUS_FAILED,
    FETCH_STATUS_MANUAL,
)

#: Subset the connector layer can emit (``base.NormalizedJob.to_fetch_result``
#: and the ATS connectors). MUST be a subset of JOB_RECORD_FETCH_STATUSES —
#: that invariant is exactly the bug this module guards.
CONNECTOR_EMITTED_FETCH_STATUSES: tuple[str, ...] = (
    FETCH_STATUS_SUCCESS,
    FETCH_STATUS_PARTIAL,
    FETCH_STATUS_FAILED,
)

# ---------------------------------------------------------------------------
# source_type — origin/connector that produced a persisted JobRecord
# ---------------------------------------------------------------------------

# Active producers: the connector that successfully fetched the JD.
SOURCE_TYPE_GREENHOUSE = "greenhouse"
SOURCE_TYPE_LEVER = "lever"
SOURCE_TYPE_ASHBY = "ashby"
SOURCE_TYPE_WORKDAY = "workday"
SOURCE_TYPE_HTML = "html"

# Manual entry (records added outside the pipeline).
SOURCE_TYPE_MANUAL = "manual"

# Pre-fetch placeholder. Used by runner.py / fetcher before a connector resolves
# the real source; it is always overwritten before a record is persisted, so it
# is deliberately NOT a valid persisted value (kept out of JOB_RECORD_SOURCE_TYPES).
SOURCE_TYPE_UNKNOWN = "unknown"

# Legacy values present in historical jobs.jsonl written before the connector
# taxonomy existed. Kept valid so re-validating old records does not fail.
_LEGACY_SOURCE_TYPES: tuple[str, ...] = (
    "company_career_page",
    "linkedin",
    "indeed",
    "glassdoor",
    "google_search",
)

#: Every source_type a persisted JobRecord may carry (== schema enum).
JOB_RECORD_SOURCE_TYPES: tuple[str, ...] = (
    SOURCE_TYPE_GREENHOUSE,
    SOURCE_TYPE_LEVER,
    SOURCE_TYPE_ASHBY,
    SOURCE_TYPE_WORKDAY,
    SOURCE_TYPE_HTML,
    SOURCE_TYPE_MANUAL,
    *_LEGACY_SOURCE_TYPES,
)

#: Subset the connector layer assigns to a *successful* fetch (i.e. what can
#: land in a saved record via the pipeline). MUST be a subset of
#: JOB_RECORD_SOURCE_TYPES. Excludes SOURCE_TYPE_UNKNOWN (never persisted) and
#: SOURCE_TYPE_MANUAL (not produced by connectors).
CONNECTOR_EMITTED_SOURCE_TYPES: tuple[str, ...] = (
    SOURCE_TYPE_GREENHOUSE,
    SOURCE_TYPE_LEVER,
    SOURCE_TYPE_ASHBY,
    SOURCE_TYPE_WORKDAY,
    SOURCE_TYPE_HTML,
)
