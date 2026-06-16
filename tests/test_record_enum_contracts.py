"""
Lock the JobRecord enum single-source-of-truth.

These tests fail if ``schemas/job_record.schema.json`` ever drifts from
``career_intelligence.contracts``, or if the connector layer can emit a
``source_type`` / ``fetch_status`` the schema would reject. The latter is the
exact bug that silently dropped successfully-fetched JDs at the Process → DB
boundary (``fetch_status="partial_success"`` / ``source_type="html"`` were not
in the schema enum).
"""

import json
from pathlib import Path

from career_intelligence import contracts
from career_intelligence.connectors.base import NormalizedJob
from career_intelligence.validator import validate_record

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = WORKSPACE_ROOT / "schemas" / "job_record.schema.json"


def _schema_enum(field: str) -> set[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return set(schema["properties"][field]["enum"])


# --- schema <-> canonical alignment -----------------------------------------


def test_source_type_schema_matches_canonical():
    assert _schema_enum("source_type") == set(contracts.JOB_RECORD_SOURCE_TYPES)


def test_fetch_status_schema_matches_canonical():
    assert _schema_enum("fetch_status") == set(contracts.JOB_RECORD_FETCH_STATUSES)


# --- producers stay within the persisted enum -------------------------------


def test_connector_source_types_are_persistable():
    missing = set(contracts.CONNECTOR_EMITTED_SOURCE_TYPES) - set(contracts.JOB_RECORD_SOURCE_TYPES)
    assert not missing, f"connectors emit source_type values the schema rejects: {missing}"


def test_connector_fetch_statuses_are_persistable():
    missing = set(contracts.CONNECTOR_EMITTED_FETCH_STATUSES) - set(contracts.JOB_RECORD_FETCH_STATUSES)
    assert not missing, f"connectors emit fetch_status values the schema rejects: {missing}"


def test_unknown_source_type_is_not_persistable():
    # 'unknown' is a pre-fetch placeholder, always resolved before save.
    assert contracts.SOURCE_TYPE_UNKNOWN not in contracts.JOB_RECORD_SOURCE_TYPES


# --- regression: the records that used to be dropped ------------------------


def _base_record() -> dict:
    return {
        "job_id": "job_a1b2c3d4",
        "title": "Market Risk Analyst",
        "company": "Goldman Sachs",
        "location": "New York, NY",
        "source_url": "https://example.com/careers/job/123",
        "source_type": contracts.SOURCE_TYPE_HTML,
        "date_found": "2026-06-07",
        "fetch_status": contracts.FETCH_STATUS_PARTIAL,
        "raw_jd_path": "runs/2026-06-07_000000/raw_jds/job_a1b2c3d4.txt",
        "primary_workstream": "Market Risk / Exposure Monitoring",
        "classification_confidence": "high",
        "classification_evidence": ["VaR mentioned"],
        "validation_status": "passed",
        "validation_errors": [],
        "run_id": "2026-06-07_000000",
        "schema_version": "1.0.0",
    }


def test_partial_success_html_record_validates():
    # Previously failed schema validation purely on the enum mismatch and was
    # dropped despite being a real, successfully-fetched posting.
    result = validate_record(_base_record(), WORKSPACE_ROOT)
    assert result.passed, f"expected pass, got: {result.errors}"


def test_normalized_job_thin_jd_is_partial_success_and_persistable():
    job = NormalizedJob(url="https://example.com/j/1", title="x", company="y", description_text="")
    fetch_result = job.to_fetch_result()
    assert fetch_result.status == contracts.FETCH_STATUS_PARTIAL
    assert fetch_result.status in contracts.JOB_RECORD_FETCH_STATUSES
    assert fetch_result.source_type in contracts.JOB_RECORD_SOURCE_TYPES
