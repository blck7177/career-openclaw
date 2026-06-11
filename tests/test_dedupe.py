"""Tests for JSONL deduplication."""
import json
import tempfile
from pathlib import Path

import pytest

from career_intelligence.storage_jsonl import upsert_job, query_jobs


def _make_record(url: str, title: str = "Market Risk Analyst", company: str = "Goldman") -> dict:
    import hashlib
    job_id = "job_" + hashlib.md5(url.encode()).hexdigest()[:8]
    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": "New York, NY",
        "source_url": url,
        "source_type": "company_career_page",
        "date_found": "2026-06-07",
        "fetch_status": "success",
        "raw_jd_path": f"runs/test/raw_jds/{job_id}.txt",
        "primary_workstream": "Market Risk / Exposure Monitoring",
        "secondary_workstreams": [],
        "classification_confidence": "high",
        "classification_evidence": ["VaR"],
        "uncertainty_notes": None,
        "possible_duplicate": False,
        "validation_status": "passed",
        "validation_errors": [],
        "run_id": "test_run",
        "schema_version": "1.0.0",
        "responsibilities": [],
        "required_skills": [],
        "preferred_skills": [],
        "tools_mentioned": [],
        "finance_domains": [],
        "seniority_inferred": "analyst",
        "likely_tasks": [],
        "likely_stakeholders": [],
        "inferred_team_context": "",
        "evidence_from_jd": {},
    }


def test_insert_and_query():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_dir = Path(tmpdir)
        rec = _make_record("https://example.com/job/1")
        result = upsert_job(rec, db_dir)
        assert result["action"] == "inserted"

        results = query_jobs(db_dir)
        assert len(results) == 1
        assert results[0]["source_url"] == "https://example.com/job/1"


def test_same_url_is_upsert():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_dir = Path(tmpdir)
        rec = _make_record("https://example.com/job/1")
        upsert_job(rec, db_dir)

        rec2 = _make_record("https://example.com/job/1")
        rec2["title"] = "Senior Market Risk Analyst"
        result = upsert_job(rec2, db_dir)
        assert result["action"] == "updated"

        results = query_jobs(db_dir)
        assert len(results) == 1
        assert results[0]["title"] == "Senior Market Risk Analyst"


def test_different_urls_same_role_flagged_duplicate():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_dir = Path(tmpdir)
        rec1 = _make_record("https://site1.com/job/1")
        rec2 = _make_record("https://site2.com/job/1")  # same title+company+loc, different URL

        upsert_job(rec1, db_dir)
        upsert_job(rec2, db_dir)

        results = query_jobs(db_dir)
        assert len(results) == 2
        assert any(r.get("possible_duplicate") for r in results)


def test_query_filter_by_workstream():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_dir = Path(tmpdir)
        rec1 = _make_record("https://example.com/1")
        rec2 = _make_record("https://example.com/2", title="Credit Analyst")
        rec2["primary_workstream"] = "Structured Credit / Credit Analytics"

        upsert_job(rec1, db_dir)
        upsert_job(rec2, db_dir)

        results = query_jobs(db_dir, workstream="Market Risk")
        assert len(results) == 1
        assert results[0]["source_url"] == "https://example.com/1"
