"""
Output Validator — validates a job record against the JSON schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)


def _load_schema(workspace_root: Path) -> dict[str, Any]:
    schema_path = workspace_root / "schemas" / "job_record.schema.json"
    import json
    with open(schema_path) as f:
        return json.load(f)


_SCHEMA_CACHE: dict[str, dict] = {}


def validate_record(record: dict[str, Any], workspace_root: Path) -> ValidationResult:
    """
    Validate a job record against job_record.schema.json.
    Returns ValidationResult with passed=True/False and list of errors.
    """
    cache_key = str(workspace_root)
    if cache_key not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[cache_key] = _load_schema(workspace_root)
    schema = _SCHEMA_CACHE[cache_key]

    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(record), key=lambda e: e.path)

    if not errors:
        return _extra_checks(record)

    error_msgs = [f"{'.'.join(str(p) for p in e.path) or 'root'}: {e.message}" for e in errors]
    return ValidationResult(passed=False, errors=error_msgs)


def _extra_checks(record: dict[str, Any]) -> ValidationResult:
    """Domain-specific checks beyond JSON Schema."""
    errors = []

    if record.get("classification_confidence") == "low" and not record.get("uncertainty_notes"):
        errors.append("uncertainty_notes is required when classification_confidence is 'low'")

    if record.get("fetch_status") == "success" and not record.get("raw_jd_path"):
        errors.append("raw_jd_path must be set when fetch_status is 'success'")

    evidence = record.get("evidence_from_jd", {})
    if isinstance(evidence, dict) and "_extraction_error" in evidence:
        errors.append(f"Extraction failed: {evidence['_extraction_error']}")

    workstream = record.get("primary_workstream", "")
    if workstream == "unknown":
        errors.append("primary_workstream is 'unknown' — record requires manual workstream assignment")

    if errors:
        return ValidationResult(passed=False, errors=errors)
    return ValidationResult(passed=True, errors=[])
