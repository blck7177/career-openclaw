"""
Golden tests for the Intent Translator service.

Strategy:
  - Post-processing functions (normalize_budget_share, copy_global_constraints_to_lanes,
    scrub_private_query_terms, validate_schema) are tested directly — no LLM needed.
  - End-to-end translate() tests patch call_llm_structured_output to return
    controlled JSON payloads, then verify schema validity and constraint handling.

The 10 golden cases correspond to the test scenarios from proj_plan_0616_prompt.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from career_intelligence.services.intent_translator import (
    IntentTranslatorError,
    _extract_json,
    build_input_envelope,
    copy_global_constraints_to_lanes,
    normalize_budget_share,
    persist_artifacts,
    scrub_private_query_terms,
    translate,
    validate_schema,
)


# ---------------------------------------------------------------------------
# Shared test data helpers
# ---------------------------------------------------------------------------

def _base_profile(**kwargs) -> dict[str, Any]:
    """Minimal valid candidate profile for testing."""
    return {
        "candidate_profile_id": "prof_test001",
        "workspace_id": "test_ws",
        "created_at": "2026-06-16T00:00:00+00:00",
        "profile_version": "0.1.0",
        "years_experience": 3,
        "current_background": (
            "Risk analyst with 3 years at a regional bank. Focus on market risk, "
            "VaR monitoring, stress testing, and scenario analysis."
        ),
        "domain_experience": ["Market Risk", "Valuation Control", "Stress Testing"],
        "technical_skills": ["Python", "SQL", "Bloomberg"],
        "analytical_methods": ["VaR", "Greeks", "Scenario Analysis", "Stress Testing"],
        "finance_domains": ["Fixed Income", "Equities", "Derivatives"],
        "tools": ["Excel", "Tableau"],
        "representative_projects": [
            {
                "title": "Daily VaR Reporting",
                "description": "Built daily VaR monitoring pipeline across equity and credit portfolios.",
                "skills_used": ["Python", "SQL", "VaR"],
                "quantified_impact": "Reduced manual reporting time by 60%.",
            }
        ],
        **kwargs,
    }


def _base_intent(
    intent_kind: str = "directed_discovery",
    num_lanes: int = 1,
    hard_constraints: list[str] | None = None,
) -> dict[str, Any]:
    """Minimal valid DiscoveryIntent for testing."""
    lanes = []
    for i in range(num_lanes):
        lane_id = f"lane_{i+1}"
        lanes.append({
            "lane_id": lane_id,
            "hypothesis": f"Test hypothesis for {lane_id}.",
            "evidence_from_profile": ["VaR experience"],
            "user_signal": "",
            "strategy_signal": "",
            "query_seeds": [f"market risk analyst {lane_id}"],
            "budget_share": round(1.0 / num_lanes, 4),
        })
    return {
        "intent_kind": intent_kind,
        "raw_user_instruction": "test instruction",
        "global_constraints": {
            "hard_constraints": hard_constraints or [],
            "soft_preferences": [],
            "negative_preferences": [],
        },
        "search_lanes": lanes,
        "source_strategy": {
            "prefer_sources": [],
            "avoid_sources": [],
        },
        "translator_notes": {
            "assumptions": [],
            "missing_information": [],
            "translator_version": "1.0.0",
        },
    }


def _make_translate_call(
    llm_response: dict[str, Any],
    profile: dict[str, Any] | None = None,
    user_instruction: str = "",
    requested_mode: str = "auto",
    tmp_path: Path | None = None,
) -> dict[str, Any]:
    """
    Call translate() with a mocked LLM returning llm_response.
    Patches both make_client and call_llm_structured_output.
    """
    mock_client = MagicMock()
    repo_root = Path(__file__).resolve().parents[1]
    workspace_root = repo_root / "data" / "workspaces" / "dev_default"

    with (
        patch("career_intelligence.services.intent_translator.make_client", return_value=mock_client),
        patch(
            "career_intelligence.services.intent_translator.call_llm_structured_output",
            return_value=json.dumps(llm_response),
        ),
    ):
        return translate(
            profile=profile or _base_profile(),
            user_instruction=user_instruction,
            catalog_context={"existing_job_count": 50, "recent_companies": ["BlackRock"]},
            strategy_context={
                "coverage_gaps": ["market_risk_exposure"],
                "effective_sources": ["greenhouse.io/blackrock"],
                "avoid_sources": ["swissre.com — 403"],
                "effective_query_patterns": [],
                "avoid_query_patterns": [],
                "key_learnings": [],
                "recommended_next_searches": [],
            },
            workspace_root=workspace_root,
            repo_root=repo_root,
            requested_mode=requested_mode,
            session_root=tmp_path,
        )


# ---------------------------------------------------------------------------
# Unit tests: post-processing functions (no LLM)
# ---------------------------------------------------------------------------


class TestNormalizeBudgetShare:
    def test_equal_shares_assigned_when_missing(self) -> None:
        intent = _base_intent(num_lanes=4)
        for lane in intent["search_lanes"]:
            del lane["budget_share"]
        normalize_budget_share(intent)
        shares = [lane["budget_share"] for lane in intent["search_lanes"]]
        assert abs(sum(shares) - 1.0) < 0.01
        for s in shares:
            assert s == pytest.approx(0.25, abs=0.01)

    def test_rescales_shares_that_dont_sum_to_one(self) -> None:
        intent = _base_intent(num_lanes=2)
        intent["search_lanes"][0]["budget_share"] = 0.6
        intent["search_lanes"][1]["budget_share"] = 0.6  # total = 1.2
        normalize_budget_share(intent)
        shares = [lane["budget_share"] for lane in intent["search_lanes"]]
        assert abs(sum(shares) - 1.0) < 0.01

    def test_valid_shares_unchanged(self) -> None:
        intent = _base_intent(num_lanes=2)
        intent["search_lanes"][0]["budget_share"] = 0.7
        intent["search_lanes"][1]["budget_share"] = 0.3
        normalize_budget_share(intent)
        shares = [lane["budget_share"] for lane in intent["search_lanes"]]
        assert abs(sum(shares) - 1.0) < 0.001

    def test_no_lanes_no_error(self) -> None:
        intent = _base_intent()
        intent["search_lanes"] = []
        normalize_budget_share(intent)  # should not raise


class TestCopyGlobalConstraintsToLanes:
    def test_hard_constraints_copied_to_all_lanes(self) -> None:
        intent = _base_intent(num_lanes=3, hard_constraints=["max_years_experience: 3", "location: NYC only"])
        copy_global_constraints_to_lanes(intent)
        for lane in intent["search_lanes"]:
            assert "max_years_experience: 3" in lane["inherited_hard_constraints"]
            assert "location: NYC only" in lane["inherited_hard_constraints"]

    def test_no_duplication_when_already_present(self) -> None:
        intent = _base_intent(num_lanes=1, hard_constraints=["location: NYC only"])
        intent["search_lanes"][0]["inherited_hard_constraints"] = ["location: NYC only"]
        copy_global_constraints_to_lanes(intent)
        count = intent["search_lanes"][0]["inherited_hard_constraints"].count("location: NYC only")
        assert count == 1

    def test_empty_hard_constraints_no_op(self) -> None:
        intent = _base_intent(num_lanes=2, hard_constraints=[])
        copy_global_constraints_to_lanes(intent)
        for lane in intent["search_lanes"]:
            assert lane.get("inherited_hard_constraints", []) == []


class TestScrubPrivateQueryTerms:
    def test_removes_sensitive_keywords(self) -> None:
        intent = _base_intent(num_lanes=1)
        intent["search_lanes"][0]["query_seeds"] = [
            "market risk analyst NYC",
            "compensation market risk 150k",
            "H1B visa sponsorship risk analyst",
        ]
        scrub_private_query_terms(intent)
        seeds = intent["search_lanes"][0]["query_seeds"]
        assert "market risk analyst NYC" in seeds
        assert not any("compensation" in s.lower() for s in seeds)
        assert not any("H1B" in s or "visa" in s.lower() for s in seeds)

    def test_clean_seeds_pass_through(self) -> None:
        intent = _base_intent(num_lanes=1)
        clean_seeds = ["exposure management analyst NYC", "market risk associate bank"]
        intent["search_lanes"][0]["query_seeds"] = clean_seeds
        scrub_private_query_terms(intent)
        assert intent["search_lanes"][0]["query_seeds"] == clean_seeds


class TestValidateSchema:
    def test_valid_intent_passes(self) -> None:
        intent = _base_intent()
        errors = validate_schema(intent)
        assert errors == []

    def test_missing_required_field_fails(self) -> None:
        intent = _base_intent()
        del intent["global_constraints"]
        errors = validate_schema(intent)
        assert len(errors) > 0

    def test_invalid_intent_kind_fails(self) -> None:
        intent = _base_intent()
        intent["intent_kind"] = "invalid_mode"
        errors = validate_schema(intent)
        assert len(errors) > 0

    def test_budget_share_out_of_range_fails(self) -> None:
        intent = _base_intent(num_lanes=1)
        intent["search_lanes"][0]["budget_share"] = 1.5
        errors = validate_schema(intent)
        assert len(errors) > 0

    def test_empty_query_seeds_fails(self) -> None:
        intent = _base_intent(num_lanes=1)
        intent["search_lanes"][0]["query_seeds"] = []
        errors = validate_schema(intent)
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# Golden tests: end-to-end translate() with mock LLM
# ---------------------------------------------------------------------------


class TestGoldenCase1_DirectedWithConstraints:
    """'多找中型银行、保险公司、asset management，经验3年以下'
    Expected: directed_discovery; max_years=3 in hard_constraints; mid-size company types."""

    def test_directed_discovery_with_experience_constraint(self, tmp_path: Path) -> None:
        llm_response = _base_intent(intent_kind="directed_discovery", num_lanes=1)
        llm_response["raw_user_instruction"] = "多找中型银行、保险公司、asset management，经验3年以下"
        llm_response["global_constraints"]["hard_constraints"] = ["max_years_experience: 3"]
        llm_response["global_constraints"]["soft_preferences"] = ["prefer mid-size firms"]
        llm_response["search_lanes"][0].update({
            "lane_id": "mid_size_market_risk",
            "query_seeds": ["market risk analyst regional bank NYC", "risk analytics associate insurance"],
            "target_company_types": ["regional_bank", "insurance_carrier", "asset_manager"],
        })

        result = _make_translate_call(
            llm_response,
            user_instruction="多找中型银行、保险公司、asset management，经验3年以下",
            tmp_path=tmp_path,
        )

        assert result["intent_kind"] == "directed_discovery"
        hard = result["global_constraints"]["hard_constraints"]
        assert any("3" in c for c in hard), "Hard constraint for max_years_experience not found"
        # translator artifacts should have been persisted
        assert (tmp_path / "discovery_intent.json").exists()
        assert (tmp_path / "translator_input.json").exists()


class TestGoldenCase2_ProfileBasedExploration:
    """'我不确定自己适合什么，帮我探索'
    Expected: profile_based_exploration; 3-5 lanes; each lane has evidence_from_profile."""

    def test_produces_3_to_5_lanes_with_profile_evidence(self, tmp_path: Path) -> None:
        llm_response = _base_intent(intent_kind="profile_based_exploration", num_lanes=4)
        llm_response["raw_user_instruction"] = "我不确定自己适合什么，帮我探索"
        lane_ids = ["exposure_management", "portfolio_analytics", "valuation_control", "structured_credit"]
        evidences = [
            ["VaR monitoring experience", "stress testing scenarios"],
            ["scenario analysis", "portfolio risk diagnostics"],
            ["pricing model monitoring", "PnL explain workflows"],
            ["credit exposure", "structured product risk"],
        ]
        for i, lane in enumerate(llm_response["search_lanes"]):
            lane["lane_id"] = lane_ids[i]
            lane["evidence_from_profile"] = evidences[i]

        result = _make_translate_call(
            llm_response,
            user_instruction="我不确定自己适合什么，帮我探索",
            tmp_path=tmp_path,
        )

        assert result["intent_kind"] == "profile_based_exploration"
        assert 3 <= len(result["search_lanes"]) <= 5
        for lane in result["search_lanes"]:
            assert len(lane.get("evidence_from_profile", [])) > 0, (
                f"Lane {lane['lane_id']} missing evidence_from_profile"
            )


class TestGoldenCase3_NegationConstraint:
    """'不要 model validation'
    Expected: negative_preferences contains model validation; exclude_role_keywords set."""

    def test_model_validation_in_negative_preferences(self, tmp_path: Path) -> None:
        llm_response = _base_intent(intent_kind="directed_discovery", num_lanes=1)
        llm_response["raw_user_instruction"] = "不要 model validation"
        llm_response["global_constraints"]["negative_preferences"] = [
            "do not prioritise pure model validation roles"
        ]
        llm_response["search_lanes"][0].update({
            "query_seeds": ["market risk analyst NYC", "exposure management analyst"],
            "exclude_role_keywords": ["model validation", "model risk validation"],
        })

        result = _make_translate_call(
            llm_response,
            user_instruction="不要 model validation",
            tmp_path=tmp_path,
        )

        neg_prefs = result["global_constraints"]["negative_preferences"]
        assert any("model validation" in p.lower() for p in neg_prefs)
        for lane in result["search_lanes"]:
            for seed in lane.get("query_seeds", []):
                assert "model validation" not in seed.lower(), (
                    f"model validation should not be a primary seed: {seed}"
                )


class TestGoldenCase4_ExposureManagementDirected:
    """'多找 exposure management'
    Expected: directed_discovery; main lane is exposure/trading risk;
    profile supplements VaR/stress/scenario keywords."""

    def test_exposure_management_as_main_lane(self, tmp_path: Path) -> None:
        llm_response = _base_intent(intent_kind="directed_discovery", num_lanes=1)
        llm_response["raw_user_instruction"] = "多找 exposure management"
        llm_response["search_lanes"][0].update({
            "lane_id": "exposure_management",
            "workstream_id": "market_risk_exposure",
            "hypothesis": "User explicitly asked for exposure management; profile has VaR/stress evidence.",
            "user_signal": "多找 exposure management",
            "evidence_from_profile": ["VaR monitoring", "stress testing scenarios"],
            "query_seeds": [
                "exposure management analyst NYC",
                "trading risk analytics associate",
                "market risk exposure analyst bank",
            ],
        })

        result = _make_translate_call(
            llm_response,
            user_instruction="多找 exposure management",
            tmp_path=tmp_path,
        )

        assert result["intent_kind"] == "directed_discovery"
        lane_ids = [l["lane_id"] for l in result["search_lanes"]]
        assert "exposure_management" in lane_ids
        # Main lane should reference exposure in query seeds
        main_lane = next(l for l in result["search_lanes"] if l["lane_id"] == "exposure_management")
        assert any("exposure" in s.lower() for s in main_lane["query_seeds"])


class TestGoldenCase5_LocationSeniorityHardConstraints:
    """'只要 NYC analyst/associate'
    Expected: location hard constraint; seniority hard constraint; all lanes inherit them."""

    def test_location_and_seniority_constraints_propagated_to_lanes(self, tmp_path: Path) -> None:
        llm_response = _base_intent(intent_kind="directed_discovery", num_lanes=2)
        llm_response["raw_user_instruction"] = "只要 NYC analyst/associate"
        llm_response["global_constraints"]["hard_constraints"] = [
            "location: New York City only",
            "seniority: analyst or associate only",
        ]
        llm_response["global_constraints"]["seniority_constraints"] = {
            "target_levels": ["analyst", "associate"],
            "exclude_levels": ["vp", "director", "managing_director"],
        }
        llm_response["global_constraints"]["location_constraints"] = {
            "preferred_locations": ["New York", "NYC"],
            "remote_policy": "no_remote",
        }

        result = _make_translate_call(
            llm_response,
            user_instruction="只要 NYC analyst/associate",
            tmp_path=tmp_path,
        )

        hard = result["global_constraints"]["hard_constraints"]
        assert any("New York" in c or "NYC" in c for c in hard)
        assert any("analyst" in c.lower() or "associate" in c.lower() for c in hard)
        # Hard constraints must be propagated to all lanes
        for lane in result["search_lanes"]:
            inherited = lane.get("inherited_hard_constraints", [])
            assert any("New York" in c or "NYC" in c for c in inherited), (
                f"Lane {lane['lane_id']} missing location hard constraint in inherited"
            )


class TestGoldenCase6_EmptyInstructionRichProfile:
    """Empty user_instruction + rich profile.
    Expected: profile_based_exploration; not empty career advice."""

    def test_empty_instruction_triggers_exploration(self, tmp_path: Path) -> None:
        llm_response = _base_intent(intent_kind="profile_based_exploration", num_lanes=3)
        llm_response["raw_user_instruction"] = ""
        for i, lane in enumerate(llm_response["search_lanes"]):
            lane.update({
                "evidence_from_profile": ["VaR / stress testing experience"],
                "user_signal": "",
                "strategy_signal": "coverage_gaps: market_risk_exposure",
            })

        profile = _base_profile(
            target_workstreams=["market_risk_exposure", "valuation_control_ipv"],
            target_roles=["Risk Analyst", "Quantitative Risk"],
        )

        result = _make_translate_call(
            llm_response,
            profile=profile,
            user_instruction="",
            tmp_path=tmp_path,
        )

        assert result["intent_kind"] == "profile_based_exploration"
        assert len(result["search_lanes"]) >= 3
        # Should not be empty
        for lane in result["search_lanes"]:
            assert len(lane.get("query_seeds", [])) > 0


class TestGoldenCase7_RemoteOnly:
    """'remote only'
    Expected: remote_policy hard constraint propagated."""

    def test_remote_policy_as_hard_constraint(self, tmp_path: Path) -> None:
        llm_response = _base_intent(intent_kind="directed_discovery", num_lanes=1)
        llm_response["raw_user_instruction"] = "remote only"
        llm_response["global_constraints"]["hard_constraints"] = ["remote_policy: remote_only"]
        llm_response["global_constraints"]["location_constraints"] = {
            "preferred_locations": [],
            "remote_policy": "remote_only",
        }

        result = _make_translate_call(
            llm_response,
            user_instruction="remote only",
            tmp_path=tmp_path,
        )

        loc = result["global_constraints"].get("location_constraints", {})
        assert loc.get("remote_policy") == "remote_only"
        hard = result["global_constraints"]["hard_constraints"]
        assert any("remote" in c.lower() for c in hard)


class TestGoldenCase8_StrategyAvoidSourcePropagation:
    """strategy_context says avoid Workday.
    Expected: source_strategy.avoid_sources includes Workday domain; user targets not affected."""

    def test_avoid_source_from_strategy_context(self, tmp_path: Path) -> None:
        llm_response = _base_intent(intent_kind="directed_discovery", num_lanes=1)
        llm_response["source_strategy"] = {
            "prefer_sources": ["greenhouse.io", "lever.co"],
            "avoid_sources": ["workday.com — repeated 403", "swissre.com — bot-blocked"],
        }

        result = _make_translate_call(
            llm_response,
            user_instruction="找 market risk 岗位",
            tmp_path=tmp_path,
        )

        avoid = result.get("source_strategy", {}).get("avoid_sources", [])
        assert any("workday" in s.lower() for s in avoid)
        # User's target (market risk) should still appear in query seeds
        all_seeds = [s for lane in result["search_lanes"] for s in lane.get("query_seeds", [])]
        assert len(all_seeds) > 0


class TestGoldenCase9_GapFillDiscovery:
    """'帮我补 portfolio analytics coverage'
    Expected: gap_fill or directed; portfolio analytics main lane; no generic data analyst."""

    def test_portfolio_analytics_main_lane(self, tmp_path: Path) -> None:
        llm_response = _base_intent(intent_kind="gap_fill_discovery", num_lanes=2)
        llm_response["raw_user_instruction"] = "帮我补 portfolio analytics coverage"
        llm_response["search_lanes"][0].update({
            "lane_id": "portfolio_analytics",
            "workstream_id": "risk_analytics_automation",
            "hypothesis": "User wants to fill portfolio analytics coverage gap.",
            "query_seeds": [
                "portfolio analytics analyst NYC",
                "portfolio risk analytics associate",
                "fixed income portfolio analytics",
            ],
            "exclude_role_keywords": ["data analyst", "business analyst", "BI analyst"],
            "budget_share": 0.7,
        })
        llm_response["search_lanes"][1].update({
            "lane_id": "portfolio_risk_secondary",
            "query_seeds": ["portfolio risk management associate"],
            "budget_share": 0.3,
        })

        result = _make_translate_call(
            llm_response,
            user_instruction="帮我补 portfolio analytics coverage",
            tmp_path=tmp_path,
        )

        lane_ids = [l["lane_id"] for l in result["search_lanes"]]
        assert "portfolio_analytics" in lane_ids
        pa_lane = next(l for l in result["search_lanes"] if l["lane_id"] == "portfolio_analytics")
        # Should not default to generic data analyst queries
        for seed in pa_lane["query_seeds"]:
            assert "data analyst" not in seed.lower()
        # Exclude keywords should mention data analyst
        assert any("data analyst" in kw.lower() for kw in pa_lane.get("exclude_role_keywords", []))


class TestGoldenCase10_InsuranceInvestmentRisk:
    """'找 insurance investment risk，3年以下'
    Expected: insurance + investment/risk analytics; must not auto-expand to banking."""

    def test_insurance_investment_risk_constrained(self, tmp_path: Path) -> None:
        llm_response = _base_intent(intent_kind="directed_discovery", num_lanes=1)
        llm_response["raw_user_instruction"] = "找 insurance investment risk，3年以下"
        llm_response["global_constraints"]["hard_constraints"] = [
            "max_years_experience: 3",
            "company_type: insurance_carrier or insurance_investment",
        ]
        llm_response["search_lanes"][0].update({
            "lane_id": "insurance_investment_risk",
            "hypothesis": "User explicitly targets insurance investment risk.",
            "query_seeds": [
                "investment risk analyst insurance NYC",
                "insurance investment risk associate",
                "risk analytics insurance asset management",
            ],
            "target_company_types": ["insurance_carrier", "insurance_asset_manager"],
            "exclude_role_keywords": ["banking", "investment banking", "broker dealer"],
        })

        result = _make_translate_call(
            llm_response,
            user_instruction="找 insurance investment risk，3年以下",
            tmp_path=tmp_path,
        )

        hard = result["global_constraints"]["hard_constraints"]
        assert any("3" in c for c in hard), "max_years constraint missing"
        assert any("insurance" in c.lower() for c in hard), "insurance constraint missing"
        lane = result["search_lanes"][0]
        assert all("insurance" in s.lower() or "risk" in s.lower() for s in lane["query_seeds"])


# ---------------------------------------------------------------------------
# Error path tests
# ---------------------------------------------------------------------------


class TestTranslatorErrorHandling:
    def test_raises_when_no_llm_client(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        workspace_root = repo_root / "data" / "workspaces" / "dev_default"

        with patch("career_intelligence.services.intent_translator.make_client", return_value=None):
            with pytest.raises(IntentTranslatorError, match="No LLM API key"):
                translate(
                    profile=_base_profile(),
                    user_instruction="test",
                    catalog_context={},
                    strategy_context={},
                    workspace_root=workspace_root,
                    repo_root=repo_root,
                )

    def test_raises_on_unparseable_llm_response(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        workspace_root = repo_root / "data" / "workspaces" / "dev_default"
        mock_client = MagicMock()

        with (
            patch("career_intelligence.services.intent_translator.make_client", return_value=mock_client),
            patch(
                "career_intelligence.services.intent_translator.call_llm_structured_output",
                return_value="this is not json at all",
            ),
        ):
            with pytest.raises(IntentTranslatorError, match="Could not parse"):
                translate(
                    profile=_base_profile(),
                    user_instruction="test",
                    catalog_context={},
                    strategy_context={},
                    workspace_root=workspace_root,
                    repo_root=repo_root,
                )

    def test_persists_artifacts_to_session_root(self, tmp_path: Path) -> None:
        llm_response = _base_intent()
        _make_translate_call(llm_response, tmp_path=tmp_path)
        assert (tmp_path / "translator_input.json").exists()
        assert (tmp_path / "discovery_intent.json").exists()
        # Verify the persisted intent is valid JSON
        saved = json.loads((tmp_path / "discovery_intent.json").read_text())
        assert saved["intent_kind"] == llm_response["intent_kind"]


# ---------------------------------------------------------------------------
# Schema round-trip test
# ---------------------------------------------------------------------------


class TestSchemaRoundTrip:
    def test_all_three_intent_kinds_pass_schema(self) -> None:
        for kind in ("directed_discovery", "profile_based_exploration", "gap_fill_discovery"):
            intent = _base_intent(intent_kind=kind, num_lanes=2)
            errors = validate_schema(intent)
            assert errors == [], f"Schema errors for {kind}: {errors}"

    def test_full_featured_intent_passes_schema(self) -> None:
        intent = _base_intent(
            intent_kind="profile_based_exploration",
            num_lanes=3,
            hard_constraints=["max_years_experience: 3", "location: NYC only"],
        )
        intent["global_constraints"]["soft_preferences"] = ["prefer mid-size firms"]
        intent["global_constraints"]["negative_preferences"] = ["avoid pure model validation"]
        intent["global_constraints"]["location_constraints"] = {
            "preferred_locations": ["New York", "Jersey City"],
            "remote_policy": "allow_if_finance_relevant",
        }
        intent["global_constraints"]["seniority_constraints"] = {
            "target_levels": ["analyst", "associate"],
            "exclude_levels": ["vp", "director"],
            "max_years_experience": 3,
        }
        for i, lane in enumerate(intent["search_lanes"]):
            lane.update({
                "workstream_id": "market_risk_exposure",
                "user_signal": "user wants market risk",
                "strategy_signal": "coverage gap: market_risk_exposure",
                "target_company_types": ["bank", "asset_manager"],
                "exclude_role_keywords": ["model validation"],
                "risk_of_false_positive": "May surface generic data analyst roles.",
                "success_criteria": "3+ postings with VaR or stress testing language.",
                "inherited_hard_constraints": ["max_years_experience: 3"],
            })
        intent["source_strategy"] = {
            "prefer_sources": ["greenhouse.io"],
            "avoid_sources": ["workday.com — 403"],
        }
        intent["translator_notes"]["assumptions"] = ["Assumed NYC unless specified."]
        intent["translator_notes"]["missing_information"] = ["No seniority preference stated."]

        errors = validate_schema(intent)
        assert errors == [], f"Schema errors on full-featured intent: {errors}"


# ---------------------------------------------------------------------------
# Fix 2: profile_id deterministic stamp must override placeholder values
# ---------------------------------------------------------------------------


class TestProfileIdStamp:
    """Verify that the deterministic stamp overwrites LLM-emitted placeholder
    profile_id values ('unknown', '', 'none', 'null') with the real profile id
    from the profile dict."""

    def _call_with_profile_id(self, llm_profile_id: str | None) -> dict:
        intent = _base_intent()
        if llm_profile_id is not None:
            intent["profile_id"] = llm_profile_id
        profile = _base_profile()  # candidate_profile_id = "prof_test001"
        return _make_translate_call(intent, profile=profile)

    def test_unknown_is_overwritten_with_real_id(self) -> None:
        result = self._call_with_profile_id("unknown")
        assert result["profile_id"] == "prof_test001"

    def test_empty_string_is_overwritten_with_real_id(self) -> None:
        result = self._call_with_profile_id("")
        assert result["profile_id"] == "prof_test001"

    def test_none_value_is_overwritten_with_real_id(self) -> None:
        # LLM omits profile_id entirely (key absent)
        result = self._call_with_profile_id(None)
        assert result["profile_id"] == "prof_test001"

    def test_null_string_is_overwritten_with_real_id(self) -> None:
        result = self._call_with_profile_id("null")
        assert result["profile_id"] == "prof_test001"

    def test_none_string_is_overwritten_with_real_id(self) -> None:
        result = self._call_with_profile_id("none")
        assert result["profile_id"] == "prof_test001"

    def test_real_profile_id_is_preserved(self) -> None:
        """If the LLM correctly emits the real profile id, it must not be clobbered."""
        result = self._call_with_profile_id("prof_test001")
        assert result["profile_id"] == "prof_test001"

    def test_different_valid_id_is_preserved(self) -> None:
        """A non-placeholder id emitted by the LLM is kept as-is (the LLM may
        legitimately supply an id that differs from the profile's own id — the
        stamp only fills in missing/placeholder values)."""
        result = self._call_with_profile_id("prof_other_123")
        assert result["profile_id"] == "prof_other_123"
