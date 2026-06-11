"""Tests for schema validation."""
import json
from pathlib import Path

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]

from career_intelligence.validator import validate_record


def _base_record() -> dict:
    return {
        "job_id": "job_a1b2c3d4",
        "title": "Market Risk Analyst",
        "company": "Goldman Sachs",
        "location": "New York, NY",
        "source_url": "https://goldmansachs.com/careers/job/123",
        "source_type": "company_career_page",
        "date_found": "2026-06-07",
        "fetch_status": "success",
        "raw_jd_path": "runs/2026-06-07_000000/raw_jds/job_a1b2c3d4.txt",
        "responsibilities": ["Daily P&L explain", "VaR monitoring"],
        "required_skills": ["Python", "VaR", "Greek risk"],
        "preferred_skills": [],
        "tools_mentioned": ["Python", "Bloomberg"],
        "finance_domains": ["derivatives", "market risk"],
        "seniority_inferred": "analyst",
        "primary_workstream": "Market Risk / Exposure Monitoring",
        "secondary_workstreams": [],
        "classification_confidence": "high",
        "classification_evidence": ["VaR mentioned", "sensitivities mentioned"],
        "uncertainty_notes": None,
        "likely_tasks": ["Risk reporting"],
        "likely_stakeholders": ["Front desk"],
        "inferred_team_context": "Market risk team",
        "evidence_from_jd": {"likely_tasks": "daily VaR reporting"},
        "possible_duplicate": False,
        "validation_status": "passed",
        "validation_errors": [],
        "run_id": "2026-06-07_000000",
        "schema_version": "1.0.0",
    }


def test_valid_record_passes():
    record = _base_record()
    result = validate_record(record, WORKSPACE_ROOT)
    assert result.passed, f"Expected pass, got errors: {result.errors}"


def test_missing_required_field():
    record = _base_record()
    del record["title"]
    result = validate_record(record, WORKSPACE_ROOT)
    assert not result.passed
    assert any("title" in e for e in result.errors)


def test_invalid_source_type():
    record = _base_record()
    record["source_type"] = "telegram"
    result = validate_record(record, WORKSPACE_ROOT)
    assert not result.passed


def test_invalid_confidence_enum():
    record = _base_record()
    record["classification_confidence"] = "very_high"
    result = validate_record(record, WORKSPACE_ROOT)
    assert not result.passed


def test_low_confidence_requires_uncertainty_notes():
    record = _base_record()
    record["classification_confidence"] = "low"
    record["uncertainty_notes"] = None
    result = validate_record(record, WORKSPACE_ROOT)
    assert not result.passed
    assert any("uncertainty_notes" in e for e in result.errors)


def test_low_confidence_with_notes_passes():
    record = _base_record()
    record["classification_confidence"] = "low"
    record["uncertainty_notes"] = "Ambiguous between Market Risk and Product Control"
    result = validate_record(record, WORKSPACE_ROOT)
    assert result.passed


def test_empty_classification_evidence_fails():
    record = _base_record()
    record["classification_evidence"] = []
    result = validate_record(record, WORKSPACE_ROOT)
    assert not result.passed
