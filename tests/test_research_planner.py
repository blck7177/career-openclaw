"""Tests for research_planner.build_research_plan() and helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from career_intelligence.research_planner import (
    _clean_title_keywords,
    build_research_plan,
)


def test_clean_title_keywords_drops_noise():
    kw = _clean_title_keywords("Senior Risk Analyst, Market Risk")
    assert "senior" not in kw
    assert "analyst" not in kw
    assert "risk" in kw
    assert "market" in kw


def test_high_priority_query_from_explicit_division():
    job = {
        "company": "Flex",
        "title": "Risk Engineer",
        "division_or_business_line": "Risk Platform team",
        "finance_domains": ["credit risk"],
    }
    plan = build_research_plan(job, llm_client=None)
    assert plan.org_name == "Risk Platform team"
    assert plan.org_name_source == "division_or_business_line"
    high = [q for q in plan.queries if q["priority"] == "high"]
    assert high and "Risk Platform team" in high[0]["query"]


def test_llm_fallback_when_division_empty():
    job = {
        "company": "Flex",
        "title": "Risk Engineer",
        "division_or_business_line": "",
        "inferred_team_context": "Appears to sit in the central risk analytics group.",
    }
    llm = MagicMock()
    llm.call.return_value = "Central Risk Analytics"
    plan = build_research_plan(job, llm_client=llm)
    assert plan.org_name == "Central Risk Analytics"
    assert plan.org_name_source == "inferred_team_context_llm"
    llm.call.assert_called_once()


def test_no_llm_call_when_division_present():
    job = {"company": "Flex", "title": "X", "division_or_business_line": "Markets"}
    llm = MagicMock()
    build_research_plan(job, llm_client=llm)
    llm.call.assert_not_called()


def test_low_priority_title_fallback_always_present():
    job = {"company": "Flex", "title": "Quant Developer", "finance_domains": []}
    plan = build_research_plan(job, llm_client=None)
    low = [q for q in plan.queries if q["priority"] == "low"]
    assert low, "title-keyword fallback query should always be present"


def test_context_gaps_for_missing_division():
    job = {"company": "Flex", "title": "X", "division_or_business_line": ""}
    plan = build_research_plan(job, llm_client=None)
    assert any("division" in g.lower() for g in plan.context_gaps)
