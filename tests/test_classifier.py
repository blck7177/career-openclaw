"""Tests for workstream classifier."""
from pathlib import Path

import pytest

from career_intelligence.classifier import classify_workstream

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


def test_market_risk_high_confidence():
    jd = "Daily VaR reporting, Greeks monitoring, P&L explain to desk. Exposure analytics."
    result = classify_workstream(jd, {}, WORKSPACE_ROOT)
    assert "Market Risk" in result.primary_workstream
    assert result.classification_confidence in ("high", "medium")
    assert len(result.classification_evidence) > 0


def test_valuation_control():
    jd = "Independent price verification (IPV), fair value mark validation, P&L reserve calculation."
    result = classify_workstream(jd, {}, WORKSPACE_ROOT)
    assert "Valuation Control" in result.primary_workstream or "IPV" in str(result.classification_evidence)


def test_unknown_domain():
    jd = "General administrative role. Filing and reception duties."
    result = classify_workstream(jd, {}, WORKSPACE_ROOT)
    assert result.classification_confidence == "low"
    assert result.uncertainty_notes is not None


def test_structured_credit():
    jd = "CLO portfolio analysis, structured credit risk, CDO valuation, ABS spread analysis."
    result = classify_workstream(jd, {}, WORKSPACE_ROOT)
    assert "Structured Credit" in result.primary_workstream
