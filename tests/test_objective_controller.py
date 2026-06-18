"""
Unit tests for the Objective Controller layer.

Covers:
  - SearchObjective.from_intent_and_request (budget split)
  - evaluate_attempt (all failure types + met + give_up)
  - generate_followup_context (with mock LLM + fallback)
  - ObjectiveController.run (met in 1 attempt, retry and met in 2, not_met)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from career_intelligence.objective_controller import (
    AttemptResult,
    EvaluationResult,
    ObjectiveController,
    SearchObjective,
    _FAILURE_TYPE_BUDGET_EXHAUSTED,
    _FAILURE_TYPE_FETCH_FAILURES,
    _FAILURE_TYPE_HIGH_DUPLICATES,
    _FAILURE_TYPE_LOW_CANDIDATES,
    _STATUS_GIVE_UP,
    _STATUS_MET,
    _STATUS_RETRY,
    evaluate_attempt,
    generate_followup_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_objective(
    target: int = 10,
    max_attempts: int = 2,
    total_queries: int = 40,
    total_pages: int = 60,
) -> SearchObjective:
    return SearchObjective.from_intent_and_request(
        objective_id="test_obj_001",
        target_new_jobs=target,
        total_queries=total_queries,
        total_pages=total_pages,
        max_attempts=max_attempts,
    )


def _make_attempt(
    attempt_number: int = 1,
    new_jobs_inserted: int = 0,
    candidates_captured: int = 10,
    possible_duplicates: int = 0,
    jobs_failed: int = 0,
    queries_run: int = 15,
) -> AttemptResult:
    return AttemptResult(
        attempt_number=attempt_number,
        session_id=f"sess_{attempt_number}",
        queries_run=queries_run,
        candidates_captured=candidates_captured,
        jobs_fetched=candidates_captured,
        jobs_structured=candidates_captured,
        new_jobs_inserted=new_jobs_inserted,
        existing_jobs_updated=0,
        possible_duplicates=possible_duplicates,
        jobs_failed=jobs_failed,
        duration_seconds=10.0,
        search_complete=True,
    )


# ---------------------------------------------------------------------------
# SearchObjective — budget split
# ---------------------------------------------------------------------------


class TestSearchObjectiveBudgetSplit:
    def test_60_40_split_for_two_attempts(self) -> None:
        obj = _make_objective(total_queries=40, total_pages=60, max_attempts=2)
        assert obj.attempt_1_queries == 24  # round(40 * 0.6)
        assert obj.attempt_1_pages == 36    # round(60 * 0.6)
        assert obj.attempt_2_queries == 16  # 40 - 24
        assert obj.attempt_2_pages == 24    # 60 - 36

    def test_full_budget_for_one_attempt(self) -> None:
        obj = _make_objective(total_queries=30, total_pages=40, max_attempts=1)
        assert obj.attempt_1_queries == 30
        assert obj.attempt_1_pages == 40

    def test_per_attempt_budget_method(self) -> None:
        obj = _make_objective(total_queries=40, total_pages=60, max_attempts=2)
        q1, p1 = obj.per_attempt_budget(1)
        q2, p2 = obj.per_attempt_budget(2)
        assert q1 == obj.attempt_1_queries
        assert p1 == obj.attempt_1_pages
        assert q2 == obj.attempt_2_queries
        assert p2 == obj.attempt_2_pages

    def test_minimum_budget_is_1(self) -> None:
        obj = _make_objective(total_queries=1, total_pages=1, max_attempts=2)
        assert obj.attempt_1_queries >= 1
        assert obj.attempt_2_queries >= 1

    def test_hard_constraints_propagated_from_intent(self) -> None:
        intent = {
            "hard_constraints": {"location": ["NYC"], "seniority": ["Analyst"]},
            "soft_preferences": {"company_types": ["bank"]},
        }
        obj = SearchObjective.from_intent_and_request(
            objective_id="x",
            target_new_jobs=5,
            total_queries=20,
            total_pages=30,
            discovery_intent=intent,
        )
        assert obj.hard_constraints.get("location") == ["NYC"]
        assert obj.soft_preferences.get("company_types") == ["bank"]

    def test_explicit_constraints_override_intent(self) -> None:
        intent = {"hard_constraints": {"location": ["Boston"]}}
        obj = SearchObjective.from_intent_and_request(
            objective_id="x",
            target_new_jobs=5,
            total_queries=20,
            total_pages=30,
            discovery_intent=intent,
            hard_constraints={"location": ["NYC"]},
        )
        assert obj.hard_constraints["location"] == ["NYC"]


# ---------------------------------------------------------------------------
# evaluate_attempt
# ---------------------------------------------------------------------------


class TestEvaluateAttempt:
    def test_met_when_target_reached(self) -> None:
        obj = _make_objective(target=5)
        attempt = _make_attempt(attempt_number=1, new_jobs_inserted=5)
        result = evaluate_attempt(obj, attempt, cumulative_new_jobs=5)
        assert result.status == _STATUS_MET
        assert result.remaining_target == 0

    def test_met_when_cumulative_exceeds_target(self) -> None:
        obj = _make_objective(target=5)
        attempt = _make_attempt(attempt_number=1, new_jobs_inserted=7)
        result = evaluate_attempt(obj, attempt, cumulative_new_jobs=7)
        assert result.status == _STATUS_MET

    def test_give_up_when_final_attempt_and_not_met(self) -> None:
        obj = _make_objective(target=10, max_attempts=2)
        attempt = _make_attempt(attempt_number=2, new_jobs_inserted=3)
        result = evaluate_attempt(obj, attempt, cumulative_new_jobs=3)
        assert result.status == _STATUS_GIVE_UP
        assert result.failure_type == _FAILURE_TYPE_BUDGET_EXHAUSTED

    def test_retry_with_high_duplicates(self) -> None:
        obj = _make_objective(target=10, max_attempts=2)
        # 8 of 10 candidates are duplicates → dup_rate = 0.8 > threshold 0.7
        attempt = _make_attempt(
            attempt_number=1,
            new_jobs_inserted=2,
            candidates_captured=10,
            possible_duplicates=8,
        )
        result = evaluate_attempt(obj, attempt, cumulative_new_jobs=2)
        assert result.status == _STATUS_RETRY
        assert result.failure_type == _FAILURE_TYPE_HIGH_DUPLICATES

    def test_retry_with_low_candidates(self) -> None:
        obj = _make_objective(target=10, max_attempts=2)
        # Only 3 candidates, below min_candidate_count=5
        attempt = _make_attempt(
            attempt_number=1,
            new_jobs_inserted=1,
            candidates_captured=3,
            possible_duplicates=0,
        )
        result = evaluate_attempt(obj, attempt, cumulative_new_jobs=1)
        assert result.status == _STATUS_RETRY
        assert result.failure_type == _FAILURE_TYPE_LOW_CANDIDATES

    def test_retry_with_fetch_failures(self) -> None:
        obj = _make_objective(target=10, max_attempts=2)
        # candidates_captured=5 (equal to min threshold, not below), jobs_failed=9
        # total_discovered=14, fetch_failure_rate=9/14≈0.64 > threshold=0.6
        attempt = _make_attempt(
            attempt_number=1,
            new_jobs_inserted=1,
            candidates_captured=5,
            possible_duplicates=0,
            jobs_failed=9,
        )
        result = evaluate_attempt(obj, attempt, cumulative_new_jobs=1)
        assert result.status == _STATUS_RETRY
        assert result.failure_type == _FAILURE_TYPE_FETCH_FAILURES

    def test_retry_generic_when_no_specific_failure(self) -> None:
        obj = _make_objective(target=10, max_attempts=2)
        # Moderate results, no specific threshold crossed
        attempt = _make_attempt(
            attempt_number=1,
            new_jobs_inserted=3,
            candidates_captured=8,
            possible_duplicates=2,
            jobs_failed=1,
        )
        result = evaluate_attempt(obj, attempt, cumulative_new_jobs=3)
        assert result.status == _STATUS_RETRY
        assert result.failure_type == _FAILURE_TYPE_BUDGET_EXHAUSTED
        assert result.remaining_target == 7

    def test_remaining_target_is_correct(self) -> None:
        obj = _make_objective(target=10)
        attempt = _make_attempt(attempt_number=1, new_jobs_inserted=4)
        result = evaluate_attempt(obj, attempt, cumulative_new_jobs=4)
        assert result.remaining_target == 6

    def test_give_up_also_applies_to_single_attempt(self) -> None:
        obj = _make_objective(target=10, max_attempts=1)
        attempt = _make_attempt(attempt_number=1, new_jobs_inserted=3)
        result = evaluate_attempt(obj, attempt, cumulative_new_jobs=3)
        assert result.status == _STATUS_GIVE_UP


# ---------------------------------------------------------------------------
# generate_followup_context
# ---------------------------------------------------------------------------


class TestGenerateFollowupContext:
    def _eval(self, failure_type: str, remaining: int = 6) -> EvaluationResult:
        return EvaluationResult(
            attempt_number=1,
            status=_STATUS_RETRY,
            failure_type=failure_type,
            failure_reason="test reason",
            new_jobs_so_far=4,
            remaining_target=remaining,
        )

    def test_uses_llm_pivot_hint_when_available(self) -> None:
        mock_llm = MagicMock()
        mock_llm.call.return_value = "Focus on direct ATS boards for mid-size asset managers."

        obj = _make_objective(target=10)
        attempt = _make_attempt(attempt_number=1, new_jobs_inserted=4)
        eval_result = self._eval(_FAILURE_TYPE_HIGH_DUPLICATES)

        ctx = generate_followup_context(obj, attempt, eval_result, mock_llm)

        assert ctx["attempt_number"] == 2
        assert ctx["pivot_hint"] == "Focus on direct ATS boards for mid-size asset managers."
        mock_llm.call.assert_called_once()

    def test_falls_back_to_deterministic_when_llm_is_none(self) -> None:
        obj = _make_objective(target=10)
        attempt = _make_attempt(
            attempt_number=1, new_jobs_inserted=2,
            candidates_captured=10, possible_duplicates=8,
        )
        eval_result = self._eval(_FAILURE_TYPE_HIGH_DUPLICATES)

        ctx = generate_followup_context(obj, attempt, eval_result, llm_client=None)

        assert ctx["pivot_hint"] is not None
        assert len(ctx["pivot_hint"]) > 20
        assert ctx["attempt_number"] == 2

    def test_falls_back_when_llm_raises(self) -> None:
        mock_llm = MagicMock()
        mock_llm.call.side_effect = RuntimeError("LLM unavailable")

        obj = _make_objective(target=10)
        attempt = _make_attempt(attempt_number=1, new_jobs_inserted=2)
        eval_result = self._eval(_FAILURE_TYPE_LOW_CANDIDATES)

        ctx = generate_followup_context(obj, attempt, eval_result, mock_llm)

        # Should not raise; should return deterministic fallback
        assert ctx["pivot_hint"] is not None
        assert ctx["remaining_target"] == 6

    def test_context_contains_seen_companies_and_urls(self) -> None:
        obj = _make_objective(target=10)
        attempt = _make_attempt(attempt_number=1)
        attempt.seen_companies = ["JPMorgan", "Goldman Sachs"]
        attempt.seen_urls = ["https://example.com/job/1", "https://example.com/job/2"]
        eval_result = self._eval(_FAILURE_TYPE_BUDGET_EXHAUSTED)

        ctx = generate_followup_context(obj, attempt, eval_result, llm_client=None)

        assert ctx["seen_companies"] == ["JPMorgan", "Goldman Sachs"]
        assert ctx["seen_urls"] == ["https://example.com/job/1", "https://example.com/job/2"]

    def test_context_contains_previous_failure_summary(self) -> None:
        obj = _make_objective(target=10)
        attempt = _make_attempt(attempt_number=1)
        eval_result = EvaluationResult(
            attempt_number=1,
            status=_STATUS_RETRY,
            failure_type=_FAILURE_TYPE_FETCH_FAILURES,
            failure_reason="Fetch failure rate 70% exceeds threshold.",
            new_jobs_so_far=2,
            remaining_target=8,
        )

        ctx = generate_followup_context(obj, attempt, eval_result, llm_client=None)

        assert "Fetch failure rate" in ctx["previous_failure_summary"]


# ---------------------------------------------------------------------------
# ObjectiveController.run
# ---------------------------------------------------------------------------


class TestObjectiveController:
    """Integration tests for ObjectiveController using mocked run_discovery_session."""

    SESSION_1 = "2026-06-17_120000"
    SESSION_2 = "2026-06-17_130000"

    def _mock_session_result(
        self,
        session_id: str,
        new_inserted: int,
        candidates: int = 10,
        duplicates: int = 0,
        failed: int = 0,
    ) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "queries_run": 15,
            "candidates_captured": candidates,
            "jobs_fetched": candidates,
            "jobs_structured": candidates,
            "new_jobs_inserted": new_inserted,
            "existing_jobs_updated": 0,
            "possible_duplicates": duplicates,
            "jobs_failed": failed,
            "duration_seconds": 30.0,
            "search_complete": True,
        }

    def test_stops_after_attempt_1_if_met(self) -> None:
        obj = _make_objective(target=5)
        controller = ObjectiveController(obj, llm_client=None)

        with patch(
            "career_intelligence.objective_controller.ObjectiveController.run",
            wraps=controller.run,
        ):
            with patch(
                "career_intelligence.services.agent_service.run_discovery_session",
                return_value=self._mock_session_result(self.SESSION_1, new_inserted=5),
            ) as mock_rds:
                result = controller.run(
                    profile_name="test_profile",
                    search_brief="test brief",
                )

        assert result.status == "met"
        assert result.total_new_jobs_inserted == 5
        assert result.attempts_run == 1
        assert mock_rds.call_count == 1

    def test_runs_attempt_2_when_attempt_1_misses(self) -> None:
        obj = _make_objective(target=10)
        controller = ObjectiveController(obj, llm_client=None)

        side_effects = [
            self._mock_session_result(self.SESSION_1, new_inserted=3, candidates=8, duplicates=2),
            self._mock_session_result(self.SESSION_2, new_inserted=7),
        ]

        with patch(
            "career_intelligence.services.agent_service.run_discovery_session",
            side_effect=side_effects,
        ) as mock_rds:
            result = controller.run(
                profile_name="test_profile",
                search_brief="test brief",
            )

        assert result.attempts_run == 2
        assert result.total_new_jobs_inserted == 10
        assert result.status == "met"
        assert mock_rds.call_count == 2

    def test_attempt_2_receives_attempt_context(self) -> None:
        """The second call to run_discovery_session must include attempt_context."""
        obj = _make_objective(target=10)
        controller = ObjectiveController(obj, llm_client=None)

        calls_received: list[dict[str, Any]] = []

        def fake_rds(**kwargs: Any) -> dict[str, Any]:
            calls_received.append(kwargs)
            if len(calls_received) == 1:
                return self._mock_session_result(self.SESSION_1, new_inserted=3)
            return self._mock_session_result(self.SESSION_2, new_inserted=7)

        with patch(
            "career_intelligence.services.agent_service.run_discovery_session",
            side_effect=fake_rds,
        ):
            controller.run(profile_name="test", search_brief="brief")

        assert len(calls_received) == 2
        # First call: no attempt_context (or None)
        assert calls_received[0].get("attempt_context") is None
        # Second call: must have attempt_context with attempt_number=2
        ac = calls_received[1].get("attempt_context")
        assert ac is not None
        assert ac["attempt_number"] == 2
        assert "pivot_hint" in ac

    def test_partially_met_when_both_attempts_fall_short(self) -> None:
        obj = _make_objective(target=10)
        controller = ObjectiveController(obj, llm_client=None)

        side_effects = [
            self._mock_session_result(self.SESSION_1, new_inserted=3),
            self._mock_session_result(self.SESSION_2, new_inserted=2),
        ]

        with patch(
            "career_intelligence.services.agent_service.run_discovery_session",
            side_effect=side_effects,
        ):
            result = controller.run(profile_name="test", search_brief="brief")

        assert result.status == "partially_met"
        assert result.total_new_jobs_inserted == 5
        assert result.attempts_run == 2

    def test_not_met_when_zero_across_all_attempts(self) -> None:
        obj = _make_objective(target=10)
        controller = ObjectiveController(obj, llm_client=None)

        side_effects = [
            self._mock_session_result(self.SESSION_1, new_inserted=0),
            self._mock_session_result(self.SESSION_2, new_inserted=0),
        ]

        with patch(
            "career_intelligence.services.agent_service.run_discovery_session",
            side_effect=side_effects,
        ):
            result = controller.run(profile_name="test", search_brief="brief")

        assert result.status == "not_met"
        assert result.total_new_jobs_inserted == 0

    def test_final_result_aggregates_correctly(self) -> None:
        obj = _make_objective(target=10)
        controller = ObjectiveController(obj, llm_client=None)

        side_effects = [
            {**self._mock_session_result(self.SESSION_1, new_inserted=4),
             "existing_jobs_updated": 2, "possible_duplicates": 1, "jobs_failed": 1},
            {**self._mock_session_result(self.SESSION_2, new_inserted=6),
             "existing_jobs_updated": 1, "possible_duplicates": 0, "jobs_failed": 0},
        ]

        with patch(
            "career_intelligence.services.agent_service.run_discovery_session",
            side_effect=side_effects,
        ):
            result = controller.run(profile_name="test", search_brief="brief")

        assert result.total_new_jobs_inserted == 10
        assert result.total_existing_jobs_updated == 3
        assert result.total_possible_duplicates == 1
        assert result.total_jobs_failed == 1
        assert len(result.attempt_summaries) == 2
        assert result.attempt_summaries[0]["new_jobs_inserted"] == 4
        assert result.attempt_summaries[1]["new_jobs_inserted"] == 6

    def test_to_dict_includes_backward_compat_jobs_saved(self) -> None:
        obj = _make_objective(target=5)
        controller = ObjectiveController(obj, llm_client=None)

        with patch(
            "career_intelligence.services.agent_service.run_discovery_session",
            return_value=self._mock_session_result(self.SESSION_1, new_inserted=5),
        ):
            result = controller.run(profile_name="test", search_brief="brief")

        d = result.to_dict()
        assert "jobs_saved" in d
        assert d["jobs_saved"] == d["new_jobs_inserted"] + d["existing_jobs_updated"]
        assert "objective_status" in d
        assert "attempt_summaries" in d
