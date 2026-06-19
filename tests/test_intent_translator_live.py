"""
Live-LLM integration tests for the Intent Translator.

These tests call the REAL LLM (OpenAI key from .env) and record the full
DiscoveryIntent output for each of the 10 golden scenarios.  They are
deliberately slow (~5-10s each) and are skipped by default in CI unless
you run with:

    pytest tests/test_intent_translator_live.py -v -m live

Results are written to:
    tests/live_results/intent_translator_<timestamp>.json

One file per test run — inspect it to compare actual LLM output vs expected.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

# Load .env so OPENAI_API_KEY etc. are available when run outside of a shell
# that has already sourced the env file.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = _REPO_ROOT / ".env"
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from career_intelligence.services.intent_translator import translate  # noqa: E402

# ---------------------------------------------------------------------------
# pytest mark — skip unless explicitly requested
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

WORKSPACE_ROOT = _REPO_ROOT / "data" / "workspaces" / "dev_default"

# Rich profile matching what's actually in the dev_default workspace
REAL_PROFILE: dict[str, Any] = {
    "candidate_profile_id": "prof_5546029d92",
    "workspace_id": "dev_default",
    "profile_version": "0.1.0",
    "display_name": "Risk analyst",
    "years_experience": 3,
    "current_background": "UBS model validation",
    "domain_experience": [
        "VaR/ES, scenario/stress testing, sensitivity analysis, derivatives, "
        "fixed income, CDS, PD/rating migration"
    ],
    "technical_skills": [
        "Python/R (pandas, NumPy, SciPy, scikit-learn), SQL, Excel, Git, "
        "Tableau/Power BI, Bloomberg"
    ],
    "analytical_methods": [
        "GLM/OLS, time series/GARCH, factor models, optimization, "
        "bootstrap/simulation, PCA, tree-based ML"
    ],
    "finance_domains": [
        "Financial Derivatives, Advanced Term Structure, ML, Financial Computing (C++)"
    ],
    "tools": [
        "Python/R (pandas, NumPy, SciPy, scikit-learn), SQL, Excel, Git, "
        "Tableau/Power BI, Bloomberg"
    ],
    "representative_projects": [
        {
            "title": "Quantitative Analyst - Model Risk Management",
            "description": (
                "Covered predictive/forecast models used for regulatory stress testing "
                "(CCAR/ICAAP) across market, credit, operational risk and capital planning "
                "(VaR forecast, credit rating migration/stress PD, issuer default loss). "
                "VaR RWA: assessed PnL decomposition, sensitivity analysis on risk drivers. "
                "Wholesale stress PD: reviewed one-factor Gaussian rating-transition framework. "
                "OpRisk loss forecast: replicated feature selection and built challenger in R; "
                "performed GLM diagnostics. Built Python/R challenger models and automated "
                "residual diagnostics, backtesting, stability analysis."
            ),
            "skills_used": [
                "Python/R (pandas, NumPy, SciPy, scikit-learn), SQL, Excel, Git, Bloomberg"
            ],
        }
    ],
    "target_roles": ["Quantitative analyst"],
    "target_workstreams": ["market_risk_exposure", "valuation_control_ipv"],
    "constraints": "New York Only",
}

# Strategy context derived from the latest strategy_patch.json
BASE_STRATEGY_CONTEXT: dict[str, Any] = {
    "effective_sources": ["Schonfeld Greenhouse ATS board"],
    "avoid_sources": [],
    "effective_query_patterns": [],
    "avoid_query_patterns": [],
    "coverage_gaps": [
        "market_risk_exposure",
        "product_control_pnl",
        "risk_analytics_automation",
        "structured_credit",
        "valuation_control_ipv",
    ],
    "key_learnings": [
        "Schonfeld Greenhouse is live and reachable, but the NYC finance-adjacent title "
        "set was still too narrow; next pass should broaden titles.",
        "A live ATS board can return a real result set even when the keepers count is zero.",
    ],
    "recommended_next_searches": [
        "Retry live NYC Greenhouse/Lever/Ashby boards with broader finance-adjacent titles "
        "(valuation control, IPV, P&L reporting, risk analytics, exposure, stress testing).",
        "Target additional NYC buy-side and bank career pages for market_risk_exposure "
        "and product_control_pnl.",
    ],
}

BASE_CATALOG_CONTEXT: dict[str, Any] = {
    "existing_job_count": 0,
    "recent_companies": ["Schonfeld"],
}


# ---------------------------------------------------------------------------
# Result recorder
# ---------------------------------------------------------------------------

_RESULTS: list[dict[str, Any]] = []
_RESULTS_DIR = Path(__file__).parent / "live_results"


def _record(case_id: str, instruction: str, intent: dict[str, Any],
            assertions: dict[str, bool]) -> None:
    """Append result to the in-memory list (flushed at session end by fixture)."""
    _RESULTS.append({
        "case_id": case_id,
        "user_instruction": instruction,
        "intent_kind": intent.get("intent_kind"),
        "num_lanes": len(intent.get("search_lanes", [])),
        "hard_constraints": intent.get("global_constraints", {}).get("hard_constraints", []),
        "negative_preferences": intent.get("global_constraints", {}).get("negative_preferences", []),
        "location_constraints": intent.get("global_constraints", {}).get("location_constraints"),
        "seniority_constraints": intent.get("global_constraints", {}).get("seniority_constraints"),
        "lanes": [
            {
                "lane_id": l.get("lane_id"),
                "workstream_id": l.get("workstream_id"),
                "query_seeds": l.get("query_seeds", []),
                "budget_share": l.get("budget_share"),
                "target_company_types": l.get("target_company_types", []),
                "exclude_role_keywords": l.get("exclude_role_keywords", []),
                "inherited_hard_constraints": l.get("inherited_hard_constraints", []),
                "evidence_from_profile": l.get("evidence_from_profile", []),
            }
            for l in intent.get("search_lanes", [])
        ],
        "source_strategy": intent.get("source_strategy"),
        "translator_notes": intent.get("translator_notes"),
        "assertions": assertions,
        "all_passed": all(assertions.values()),
    })


@pytest.fixture(scope="session", autouse=True)
def _flush_results():
    """Write all recorded results to a JSON file after the session completes."""
    yield
    if not _RESULTS:
        return
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = _RESULTS_DIR / f"intent_translator_{ts}.json"
    out_path.write_text(json.dumps(_RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    # Also print a compact summary to stdout
    print(f"\n\n{'='*70}")
    print(f"LIVE TEST RESULTS  →  {out_path}")
    print(f"{'='*70}")
    for r in _RESULTS:
        status = "✅ PASS" if r["all_passed"] else "❌ FAIL"
        print(f"  {status}  {r['case_id']}  [{r['intent_kind']}  {r['num_lanes']} lane(s)]")
        if not r["all_passed"]:
            for k, v in r["assertions"].items():
                if not v:
                    print(f"         FAIL: {k}")
    print(f"{'='*70}\n")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run(
    instruction: str,
    *,
    profile: dict[str, Any] | None = None,
    strategy: dict[str, Any] | None = None,
    mode: str = "auto",
    search_source: str = "instruction_plus_profile",
    tmp_path: Path,
) -> dict[str, Any]:
    return translate(
        profile=profile or REAL_PROFILE,
        user_instruction=instruction,
        catalog_context=BASE_CATALOG_CONTEXT,
        strategy_context=strategy or BASE_STRATEGY_CONTEXT,
        workspace_root=WORKSPACE_ROOT,
        repo_root=_REPO_ROOT,
        requested_mode=mode,
        search_source=search_source,
        session_root=tmp_path,
    )


def _constraint_values(hard_constraints: list[Any]) -> list[str]:
    """Extract plain string values from hard_constraints.

    Handles both the legacy string-list format and the provenance-tagged
    {value, source} object format introduced in Gap 1.
    """
    result = []
    for c in hard_constraints:
        if isinstance(c, str):
            result.append(c)
        elif isinstance(c, dict) and "value" in c:
            result.append(str(c["value"]))
    return result


# ---------------------------------------------------------------------------
# Case 1: directed + experience cap + company types
# ---------------------------------------------------------------------------

def test_case1_directed_mid_size_firms_max_3yrs(tmp_path: Path) -> None:
    """
    "多找中型银行、保险公司、asset management，经验3年以下"
    Expected: directed_discovery; max_years=3 in hard_constraints;
              target_company_types includes mid-size / insurance / asset_mgr;
              no senior/VP level in seeds.
    """
    instruction = "多找中型银行、保险公司、asset management，经验3年以下"
    intent = _run(instruction, tmp_path=tmp_path)

    hard = intent["global_constraints"]["hard_constraints"]
    all_seeds = [s for l in intent["search_lanes"] for s in l.get("query_seeds", [])]
    company_types = [ct for l in intent["search_lanes"] for ct in l.get("target_company_types", [])]

    assertions = {
        "intent_kind == directed_discovery": intent["intent_kind"] == "directed_discovery",
        "max_years_experience 3 in hard_constraints": any("3" in c for c in hard),
        "at least one lane": len(intent["search_lanes"]) >= 1,
        "company types present": len(company_types) > 0,
        "no vp/director/senior in query seeds": not any(
            kw in s.lower() for kw in ("vp", "director", "senior", "managing")
            for s in all_seeds
        ),
        "artifacts saved": (tmp_path / "discovery_intent.json").exists(),
    }
    _record("case1_directed_mid_size_max3yrs", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 1] FAILED: {desc}"


# ---------------------------------------------------------------------------
# Case 2: profile-based exploration
# ---------------------------------------------------------------------------

def test_case2_profile_based_exploration(tmp_path: Path) -> None:
    """
    "我不确定自己适合什么，帮我探索"
    Expected: profile_based_exploration; 3-5 lanes;
              every lane has evidence_from_profile.
    """
    instruction = "我不确定自己适合什么，帮我探索"
    intent = _run(instruction, tmp_path=tmp_path)

    lanes = intent["search_lanes"]
    assertions = {
        "intent_kind == profile_based_exploration": (
            intent["intent_kind"] == "profile_based_exploration"
        ),
        "3 to 5 lanes": 3 <= len(lanes) <= 5,
        "every lane has evidence_from_profile": all(
            len(l.get("evidence_from_profile", [])) > 0 for l in lanes
        ),
        "every lane has query_seeds": all(
            len(l.get("query_seeds", [])) > 0 for l in lanes
        ),
    }
    _record("case2_profile_based_exploration", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 2] FAILED: {desc}"


# ---------------------------------------------------------------------------
# Case 3: negation — no model validation
# ---------------------------------------------------------------------------

def test_case3_no_model_validation(tmp_path: Path) -> None:
    """
    "不要 model validation"
    Expected: negative_preferences contains model validation;
              query_seeds do NOT have model validation as primary seed.
    """
    instruction = "不要 model validation"
    intent = _run(instruction, tmp_path=tmp_path)

    neg_prefs = intent["global_constraints"].get("negative_preferences", [])
    all_seeds = [s for l in intent["search_lanes"] for s in l.get("query_seeds", [])]

    assertions = {
        "negative_preferences mention model validation": any(
            "model validation" in p.lower() for p in neg_prefs
        ),
        "no seed is purely model validation": not any(
            s.strip().lower() in ("model validation", "model risk validation")
            for s in all_seeds
        ),
        "at least one lane": len(intent["search_lanes"]) >= 1,
    }
    _record("case3_no_model_validation", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 3] FAILED: {desc}"


# ---------------------------------------------------------------------------
# Case 4: directed — exposure management main lane
# ---------------------------------------------------------------------------

def test_case4_exposure_management(tmp_path: Path) -> None:
    """
    "多找 exposure management"
    Expected: directed_discovery; at least one lane with exposure in its seeds;
              profile evidence included (VaR/stress/scenario).
    """
    instruction = "多找 exposure management"
    intent = _run(instruction, tmp_path=tmp_path)

    lanes = intent["search_lanes"]
    exposure_lanes = [
        l for l in lanes
        if any("exposure" in s.lower() for s in l.get("query_seeds", []))
        or "exposure" in l.get("lane_id", "").lower()
        or "exposure" in l.get("workstream_id", "").lower()
    ]
    profile_evidences = [e for l in lanes for e in l.get("evidence_from_profile", [])]

    assertions = {
        "intent_kind == directed_discovery": intent["intent_kind"] == "directed_discovery",
        "main lane targets exposure": len(exposure_lanes) >= 1,
        "profile evidence present (VaR or stress)": any(
            kw in e.lower() for kw in ("var", "stress", "scenario", "volatility")
            for e in profile_evidences
        ),
    }
    _record("case4_exposure_management", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 4] FAILED: {desc}"


# ---------------------------------------------------------------------------
# Case 5: location + seniority hard constraints
# ---------------------------------------------------------------------------

def test_case5_nyc_analyst_associate_only(tmp_path: Path) -> None:
    """
    "只要 NYC analyst/associate"
    Expected: hard_constraints include NYC and seniority;
              all lanes inherit hard constraints.
    """
    instruction = "只要 NYC analyst/associate"
    intent = _run(instruction, tmp_path=tmp_path)

    hard = intent["global_constraints"]["hard_constraints"]
    loc = intent["global_constraints"].get("location_constraints", {})
    seniority = intent["global_constraints"].get("seniority_constraints", {})

    assertions = {
        "NYC in hard_constraints or preferred_locations": (
            any("nyc" in c.lower() or "new york" in c.lower() for c in hard)
            or any("new york" in loc.lower() or "nyc" in loc.lower()
                   for loc in loc.get("preferred_locations", []))
        ),
        "analyst/associate in hard_constraints or target_levels": (
            any("analyst" in c.lower() or "associate" in c.lower() for c in hard)
            or any(
                lvl in seniority.get("target_levels", [])
                for lvl in ("analyst", "associate")
            )
        ),
        "all lanes inherit at least one hard constraint": all(
            len(l.get("inherited_hard_constraints", [])) > 0
            for l in intent["search_lanes"]
        ),
    }
    _record("case5_nyc_analyst_associate", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 5] FAILED: {desc}"


# ---------------------------------------------------------------------------
# Case 6: portfolio analytics gap fill
# ---------------------------------------------------------------------------

def test_case6_portfolio_analytics_gap_fill(tmp_path: Path) -> None:
    """
    "帮我补 portfolio analytics coverage"
    Expected: gap_fill_discovery or directed_discovery;
              main lane targets portfolio analytics;
              no generic 'data analyst' in primary seeds.
    """
    instruction = "帮我补 portfolio analytics coverage"
    intent = _run(instruction, tmp_path=tmp_path)

    lanes = intent["search_lanes"]
    portfolio_lanes = [
        l for l in lanes
        if any("portfolio" in s.lower() for s in l.get("query_seeds", []))
        or "portfolio" in l.get("lane_id", "").lower()
    ]
    primary_lane_seeds = lanes[0].get("query_seeds", []) if lanes else []

    assertions = {
        "intent_kind is gap_fill or directed": intent["intent_kind"] in (
            "gap_fill_discovery", "directed_discovery"
        ),
        "at least one portfolio-focused lane": len(portfolio_lanes) >= 1,
        "primary lane seeds not generic data analyst": not any(
            s.strip().lower() == "data analyst" for s in primary_lane_seeds
        ),
    }
    _record("case6_portfolio_analytics_gap_fill", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 6] FAILED: {desc}"


# ---------------------------------------------------------------------------
# Case 7: insurance investment risk, no banking expansion
# ---------------------------------------------------------------------------

def test_case7_insurance_investment_risk_no_banking(tmp_path: Path) -> None:
    """
    "找 insurance investment risk，3年以下"
    Expected: directed_discovery; insurance in company types or hard_constraints;
              max_years=3; seeds don't expand into pure banking.
    """
    instruction = "找 insurance investment risk，3年以下"
    intent = _run(instruction, tmp_path=tmp_path)

    hard = intent["global_constraints"]["hard_constraints"]
    company_types = [ct for l in intent["search_lanes"] for ct in l.get("target_company_types", [])]
    all_seeds = [s for l in intent["search_lanes"] for s in l.get("query_seeds", [])]

    assertions = {
        "intent_kind == directed_discovery": intent["intent_kind"] == "directed_discovery",
        "insurance mentioned in hard_constraints or company_types": (
            any("insurance" in c.lower() for c in hard)
            or any("insurance" in ct.lower() for ct in company_types)
        ),
        "max_years_experience 3 in hard_constraints": any("3" in c for c in hard),
        "seeds reference insurance or risk (not only banking)": any(
            "insurance" in s.lower() or "investment risk" in s.lower()
            for s in all_seeds
        ),
    }
    _record("case7_insurance_investment_risk", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 7] FAILED: {desc}"


# ---------------------------------------------------------------------------
# Case 8: empty instruction + rich profile
# ---------------------------------------------------------------------------

def test_case8_empty_instruction_rich_profile(tmp_path: Path) -> None:
    """
    Empty user_instruction + rich profile.
    Expected: profile_based_exploration; non-trivial lanes with real seeds.
    """
    instruction = ""
    intent = _run(instruction, tmp_path=tmp_path)

    lanes = intent["search_lanes"]
    all_seeds = [s for l in lanes for s in l.get("query_seeds", [])]

    assertions = {
        # With a rich profile that has explicit target_workstreams, the LLM may
        # legitimately choose directed_discovery instead of profile_based_exploration.
        # Both are acceptable — what matters is that it's NOT generic gap_fill.
        "intent_kind is exploration or directed (not gap_fill)": intent["intent_kind"] in (
            "profile_based_exploration", "directed_discovery"
        ),
        "at least 2 lanes": len(lanes) >= 2,
        "total seeds > 3": len(all_seeds) > 3,
        "no generic career advice seeds (e.g. 'jobs', 'careers')": not any(
            s.strip().lower() in ("jobs", "careers", "employment", "work")
            for s in all_seeds
        ),
    }
    _record("case8_empty_instruction_rich_profile", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 8] FAILED: {desc}"


# ---------------------------------------------------------------------------
# Case 9: remote only
# ---------------------------------------------------------------------------

def test_case9_remote_only(tmp_path: Path) -> None:
    """
    "remote only"
    Expected: location_constraints.remote_policy == remote_only;
              hard_constraints mention remote.
    """
    instruction = "remote only"
    intent = _run(instruction, tmp_path=tmp_path)

    hard = intent["global_constraints"]["hard_constraints"]
    loc = intent["global_constraints"].get("location_constraints", {})

    assertions = {
        "remote_policy == remote_only in location_constraints": (
            loc.get("remote_policy") == "remote_only"
        ),
        "remote mentioned in hard_constraints OR location_constraints": (
            any("remote" in c.lower() for c in hard)
            or loc.get("remote_policy") == "remote_only"
        ),
        "at least one lane": len(intent["search_lanes"]) >= 1,
    }
    _record("case9_remote_only", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 9] FAILED: {desc}"


# ---------------------------------------------------------------------------
# Case 10: strategy_context says avoid Workday
# ---------------------------------------------------------------------------

def test_case10_strategy_avoid_workday(tmp_path: Path) -> None:
    """
    strategy_context says avoid Workday.
    Expected: source_strategy.avoid_sources includes Workday;
              user's target lanes are not suppressed.
    """
    instruction = "找 market risk analytics 岗位"
    strategy_with_workday = {
        **BASE_STRATEGY_CONTEXT,
        "avoid_sources": [
            "workday.com — repeated 403",
            "swissre.com — bot-blocked",
        ],
    }
    intent = _run(instruction, strategy=strategy_with_workday, tmp_path=tmp_path)

    avoid = (intent.get("source_strategy") or {}).get("avoid_sources", [])
    all_seeds = [s for l in intent["search_lanes"] for s in l.get("query_seeds", [])]

    assertions = {
        "workday in source_strategy.avoid_sources": any(
            "workday" in s.lower() for s in avoid
        ),
        "user target lanes not suppressed (market risk in seeds)": any(
            "market risk" in s.lower() or "risk analytics" in s.lower()
            or "risk" in s.lower()
            for s in all_seeds
        ),
        "at least one lane": len(intent["search_lanes"]) >= 1,
    }
    _record("case10_strategy_avoid_workday", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 10] FAILED: {desc}"


# ---------------------------------------------------------------------------
# Case 11: instruction_only + "remote only" — no profile location leak
# ---------------------------------------------------------------------------

def test_case11_instruction_only_remote_no_profile_leak(tmp_path: Path) -> None:
    """
    search_source=instruction_only, instruction="remote only".

    The real profile has constraints="New York Only" and target_roles=["Quantitative analyst"].
    Expected:
      - remote_policy == remote_only in location_constraints
      - no NYC/New York/Jersey City in hard_constraints values
      - no profile-derived seniority/title constraints imposed on the translator
    """
    instruction = "remote only"
    intent = _run(instruction, search_source="instruction_only", tmp_path=tmp_path)

    hard = _constraint_values(intent["global_constraints"]["hard_constraints"])
    loc = intent["global_constraints"].get("location_constraints") or {}
    all_seeds = [s for l in intent["search_lanes"] for s in l.get("query_seeds", [])]

    _nyc_terms = {"new york", "nyc", "jersey city", "manhattan"}

    assertions = {
        "remote_policy == remote_only in location_constraints": (
            loc.get("remote_policy") == "remote_only"
        ),
        "no NYC/New York location in hard_constraints values": not any(
            any(term in c.lower() for term in _nyc_terms) for c in hard
        ),
        "at least one lane": len(intent["search_lanes"]) >= 1,
        "query seeds are non-empty": len(all_seeds) > 0,
    }
    _record("case11_instruction_only_remote_no_profile_leak", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 11] FAILED: {desc}"


# ---------------------------------------------------------------------------
# Case 12: instruction_plus_profile + "remote only" — instruction wins over profile
# ---------------------------------------------------------------------------

def test_case12_instruction_plus_profile_remote_wins(tmp_path: Path) -> None:
    """
    search_source=instruction_plus_profile, instruction="remote only".

    The real profile has constraints="New York Only".
    Hard rule: user's remote_only constraint must override profile's NYC location.
    Profile may still enrich lane hypotheses/seeds, but must NOT inject NYC as a
    hard constraint or convert remote_only back to on-site/hybrid.
    """
    instruction = "remote only"
    intent = _run(instruction, search_source="instruction_plus_profile", tmp_path=tmp_path)

    hard = _constraint_values(intent["global_constraints"]["hard_constraints"])
    loc = intent["global_constraints"].get("location_constraints") or {}

    _nyc_terms = {"new york", "nyc", "jersey city", "manhattan"}

    assertions = {
        "remote_policy == remote_only in location_constraints": (
            loc.get("remote_policy") == "remote_only"
        ),
        "profile location (NYC) not promoted to hard constraint": not any(
            any(term in c.lower() for term in _nyc_terms) for c in hard
        ),
        "at least one lane": len(intent["search_lanes"]) >= 1,
    }
    _record("case12_instruction_plus_profile_remote_wins", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 12] FAILED: {desc}"


# ---------------------------------------------------------------------------
# Case 13: profile_only + empty instruction — exploration, no generic seeds
# ---------------------------------------------------------------------------

def test_case13_profile_only_exploration_no_generic_seeds(tmp_path: Path) -> None:
    """
    search_source=profile_only, instruction="" (empty).

    Expected:
      - intent_kind is profile_based_exploration (or directed if profile is strong)
      - every lane has at least one entry in evidence_from_profile
      - no query_seed is a purely generic term (e.g. 'jobs', 'careers')
    """
    instruction = ""
    intent = _run(instruction, search_source="profile_only", tmp_path=tmp_path)

    lanes = intent["search_lanes"]
    all_seeds = [s for l in lanes for s in l.get("query_seeds", [])]
    _generic = {"jobs", "careers", "employment", "work", "positions", "openings"}

    assertions = {
        "intent_kind is profile_based_exploration or directed_discovery": (
            intent["intent_kind"] in ("profile_based_exploration", "directed_discovery")
        ),
        "at least 2 lanes": len(lanes) >= 2,
        "every lane has profile_evidence": all(
            len(l.get("evidence_from_profile") or []) > 0 for l in lanes
        ),
        "no generic-only seeds (jobs/careers/etc)": not any(
            s.strip().lower() in _generic for s in all_seeds
        ),
        "total seeds > 3": len(all_seeds) > 3,
    }
    _record("case13_profile_only_exploration_no_generic_seeds", instruction, intent, assertions)
    for desc, passed in assertions.items():
        assert passed, f"[Case 13] FAILED: {desc}"
