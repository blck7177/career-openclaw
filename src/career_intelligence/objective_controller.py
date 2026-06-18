"""
Objective Controller — worker-owned goal tracking for discovery runs.

The Objective Controller is the "project manager" layer that sits between the
user's search request and individual bounded search agent attempts. It:

  1. Holds a SearchObjective derived from the user request + DiscoveryIntent.
  2. Runs at most MAX_ATTEMPTS search attempts via run_discovery_session().
  3. After each attempt, a deterministic Evaluator decides whether to stop or retry.
  4. If retry is needed, an LLM-powered FollowupPlanner generates a pivot hint for
     the next attempt so the agent can adjust strategy intelligently.
  5. Aggregates results across all attempts and returns a FinalSearchResult.

Design principles:
  - The agent owns what to search. The controller owns whether the goal is met.
  - Evaluator is pure Python (no LLM) for reliability and speed.
  - FollowupPlanner uses one LLM call per retry; it is best-effort (degrades
    gracefully to a deterministic fallback if the LLM is unavailable).
  - The controller never touches the candidate pool or JSONL storage directly;
    it delegates entirely to run_discovery_session() for each attempt.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

_FAILURE_TYPE_HIGH_DUPLICATES = "high_duplicates"
_FAILURE_TYPE_LOW_CANDIDATES = "low_candidates"
_FAILURE_TYPE_FETCH_FAILURES = "fetch_failures"
_FAILURE_TYPE_CONSTRAINT_DRIFT = "constraint_drift"
_FAILURE_TYPE_BUDGET_EXHAUSTED = "budget_exhausted"

_STATUS_MET = "met"
_STATUS_RETRY = "retry"
_STATUS_GIVE_UP = "give_up"


@dataclass
class SearchObjective:
    """Worker-owned execution contract for a discovery run."""

    objective_id: str
    target_new_jobs: int
    max_attempts: int = 2

    # Budget split: attempt 1 gets the larger share; attempt 2 gets the rest.
    attempt_1_queries: int = 25
    attempt_1_pages: int = 40
    attempt_2_queries: int = 15
    attempt_2_pages: int = 25

    # Hard constraints (propagated from DiscoveryIntent / search_params)
    hard_constraints: dict[str, Any] = field(default_factory=dict)
    soft_preferences: dict[str, Any] = field(default_factory=dict)

    # Completion thresholds
    max_duplicate_rate: float = 0.7
    max_fetch_failure_rate: float = 0.6
    min_candidate_count: int = 5

    search_mode: str = "auto"
    additional_instruction: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_intent_and_request(
        cls,
        *,
        objective_id: str,
        target_new_jobs: int,
        total_queries: int,
        total_pages: int,
        max_attempts: int = 2,
        discovery_intent: dict[str, Any] | None = None,
        search_mode: str = "auto",
        additional_instruction: str = "",
        hard_constraints: dict[str, Any] | None = None,
        soft_preferences: dict[str, Any] | None = None,
    ) -> "SearchObjective":
        """Create a SearchObjective by splitting the total budget across max_attempts.

        Budget split: attempt 1 gets ceil(60%), attempt 2 gets the remainder.
        If max_attempts == 1, attempt 1 gets the full budget.
        """
        if max_attempts <= 1:
            a1_q, a1_p = total_queries, total_pages
            a2_q, a2_p = 0, 0
        else:
            a1_q = max(1, round(total_queries * 0.6))
            a1_p = max(1, round(total_pages * 0.6))
            a2_q = max(1, total_queries - a1_q)
            a2_p = max(1, total_pages - a1_p)

        # Propagate hard constraints from discovery_intent if not explicitly provided
        effective_hard = hard_constraints or {}
        effective_soft = soft_preferences or {}
        if discovery_intent:
            effective_hard = effective_hard or discovery_intent.get("hard_constraints", {}) or {}
            effective_soft = effective_soft or discovery_intent.get("soft_preferences", {}) or {}

        return cls(
            objective_id=objective_id,
            target_new_jobs=target_new_jobs,
            max_attempts=max_attempts,
            attempt_1_queries=a1_q,
            attempt_1_pages=a1_p,
            attempt_2_queries=a2_q,
            attempt_2_pages=a2_p,
            hard_constraints=effective_hard,
            soft_preferences=effective_soft,
            search_mode=search_mode,
            additional_instruction=additional_instruction,
        )

    def per_attempt_budget(self, attempt_number: int) -> tuple[int, int]:
        """Return (max_queries, max_pages) for the given attempt (1-indexed)."""
        if attempt_number == 1:
            return self.attempt_1_queries, self.attempt_1_pages
        return self.attempt_2_queries, self.attempt_2_pages

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "target_new_jobs": self.target_new_jobs,
            "max_attempts": self.max_attempts,
            "per_attempt_budget": {
                "attempt_1_queries": self.attempt_1_queries,
                "attempt_1_pages": self.attempt_1_pages,
                "attempt_2_queries": self.attempt_2_queries,
                "attempt_2_pages": self.attempt_2_pages,
            },
            "hard_constraints": self.hard_constraints,
            "soft_preferences": self.soft_preferences,
            "completion_criteria": {
                "min_new_jobs": self.target_new_jobs,
                "max_duplicate_rate": self.max_duplicate_rate,
                "max_fetch_failure_rate": self.max_fetch_failure_rate,
                "min_candidate_count": self.min_candidate_count,
            },
            "search_mode": self.search_mode,
            "additional_instruction": self.additional_instruction,
            "created_at": self.created_at,
        }


@dataclass
class AttemptResult:
    """Outcome from a single search attempt (from run_discovery_session)."""

    attempt_number: int
    session_id: str
    queries_run: int
    candidates_captured: int
    jobs_fetched: int
    jobs_structured: int
    new_jobs_inserted: int
    existing_jobs_updated: int
    possible_duplicates: int
    jobs_failed: int
    duration_seconds: float
    search_complete: bool
    # Companies and URLs seen during this attempt (for seen_* lists in attempt 2)
    seen_companies: list[str] = field(default_factory=list)
    seen_urls: list[str] = field(default_factory=list)

    @classmethod
    def from_session_result(cls, attempt_number: int, result: dict[str, Any]) -> "AttemptResult":
        return cls(
            attempt_number=attempt_number,
            session_id=result.get("session_id", ""),
            queries_run=result.get("queries_run", 0),
            candidates_captured=result.get("candidates_captured", 0),
            jobs_fetched=result.get("jobs_fetched", 0),
            jobs_structured=result.get("jobs_structured", 0),
            new_jobs_inserted=result.get("new_jobs_inserted", 0),
            existing_jobs_updated=result.get("existing_jobs_updated", 0),
            possible_duplicates=result.get("possible_duplicates", 0),
            jobs_failed=result.get("jobs_failed", 0),
            duration_seconds=result.get("duration_seconds", 0.0),
            search_complete=result.get("search_complete", False),
            seen_companies=result.get("seen_companies", []),
            seen_urls=result.get("seen_urls", []),
        )


@dataclass
class EvaluationResult:
    """Deterministic evaluation of a single attempt against the objective."""

    attempt_number: int
    status: str             # "met" | "retry" | "give_up"
    failure_type: str | None = None   # reason for retry/give_up
    failure_reason: str = ""
    new_jobs_so_far: int = 0
    remaining_target: int = 0


@dataclass
class FinalSearchResult:
    """Aggregate result across all attempts for a single discovery run."""

    objective_id: str
    target_new_jobs: int
    attempts_run: int
    status: str           # "met" | "partially_met" | "not_met"
    reason: str

    # Aggregate counters
    total_new_jobs_inserted: int = 0
    total_existing_jobs_updated: int = 0
    total_possible_duplicates: int = 0
    total_jobs_failed: int = 0
    total_candidates_captured: int = 0
    total_queries_run: int = 0
    total_duration_seconds: float = 0.0

    # Per-attempt breakdown
    attempt_summaries: list[dict[str, Any]] = field(default_factory=list)

    # The session_id from the last attempt (used as run identifier in DB)
    last_session_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "target_new_jobs": self.target_new_jobs,
            "attempts_run": self.attempts_run,
            "objective_status": self.status,
            "objective_reason": self.reason,
            "new_jobs_inserted": self.total_new_jobs_inserted,
            "existing_jobs_updated": self.total_existing_jobs_updated,
            "possible_duplicates": self.total_possible_duplicates,
            "jobs_failed": self.total_jobs_failed,
            "candidates_captured": self.total_candidates_captured,
            "queries_run": self.total_queries_run,
            "duration_seconds": round(self.total_duration_seconds, 1),
            "attempt_summaries": self.attempt_summaries,
            # Backward-compat: keep jobs_saved = new_jobs_inserted + existing_jobs_updated
            "jobs_saved": self.total_new_jobs_inserted + self.total_existing_jobs_updated,
            "session_id": self.last_session_id,
            "run_id": self.last_session_id,
        }


# ---------------------------------------------------------------------------
# Evaluator (pure Python, no LLM)
# ---------------------------------------------------------------------------


def evaluate_attempt(
    objective: SearchObjective,
    attempt: AttemptResult,
    cumulative_new_jobs: int,
) -> EvaluationResult:
    """
    Deterministic evaluation of a single attempt result against the objective.

    Returns an EvaluationResult with status "met" | "retry" | "give_up" and a
    failure_type that drives FollowupPlanner strategy.

    cumulative_new_jobs: total new_jobs_inserted across all attempts so far
    (including this one).
    """
    remaining = max(0, objective.target_new_jobs - cumulative_new_jobs)

    # --- Met ---
    if cumulative_new_jobs >= objective.target_new_jobs:
        return EvaluationResult(
            attempt_number=attempt.attempt_number,
            status=_STATUS_MET,
            new_jobs_so_far=cumulative_new_jobs,
            remaining_target=0,
        )

    # --- Must we stop regardless? ---
    is_final_attempt = attempt.attempt_number >= objective.max_attempts
    if is_final_attempt:
        reason = (
            f"Objective not fully met after {objective.max_attempts} attempt(s). "
            f"Inserted {cumulative_new_jobs}/{objective.target_new_jobs} new jobs."
        )
        return EvaluationResult(
            attempt_number=attempt.attempt_number,
            status=_STATUS_GIVE_UP,
            failure_type=_FAILURE_TYPE_BUDGET_EXHAUSTED,
            failure_reason=reason,
            new_jobs_so_far=cumulative_new_jobs,
            remaining_target=remaining,
        )

    # --- Retry: classify failure type to guide FollowupPlanner ---
    total_discovered = attempt.candidates_captured + attempt.jobs_failed

    # 1. High duplicates: most candidates already in catalog
    if attempt.candidates_captured > 0:
        dup_rate = attempt.possible_duplicates / attempt.candidates_captured
    else:
        dup_rate = 0.0

    # 2. Low candidates: search found very little
    low_candidates = attempt.candidates_captured < objective.min_candidate_count

    # 3. Fetch failures: connectors failed on most URLs
    if total_discovered > 0:
        fetch_failure_rate = attempt.jobs_failed / total_discovered
    else:
        fetch_failure_rate = 0.0

    # Rank failure types in priority order
    if dup_rate > objective.max_duplicate_rate:
        failure_type = _FAILURE_TYPE_HIGH_DUPLICATES
        failure_reason = (
            f"Duplicate rate {dup_rate:.0%} exceeds threshold {objective.max_duplicate_rate:.0%}. "
            f"{attempt.possible_duplicates}/{attempt.candidates_captured} candidates were already in catalog."
        )
    elif low_candidates:
        failure_type = _FAILURE_TYPE_LOW_CANDIDATES
        failure_reason = (
            f"Only {attempt.candidates_captured} candidates captured "
            f"(minimum threshold: {objective.min_candidate_count}). "
            f"Search may be too narrow or keywords not matching."
        )
    elif fetch_failure_rate > objective.max_fetch_failure_rate:
        failure_type = _FAILURE_TYPE_FETCH_FAILURES
        failure_reason = (
            f"Fetch failure rate {fetch_failure_rate:.0%} exceeds threshold "
            f"{objective.max_fetch_failure_rate:.0%}. "
            f"{attempt.jobs_failed}/{total_discovered} candidates failed to fetch."
        )
    else:
        # Generic: didn't meet target but no specific failure pattern
        failure_type = _FAILURE_TYPE_BUDGET_EXHAUSTED
        failure_reason = (
            f"Inserted {attempt.new_jobs_inserted} new jobs in attempt "
            f"{attempt.attempt_number}. Cumulative: {cumulative_new_jobs}/{objective.target_new_jobs}. "
            f"Remaining target: {remaining}."
        )

    return EvaluationResult(
        attempt_number=attempt.attempt_number,
        status=_STATUS_RETRY,
        failure_type=failure_type,
        failure_reason=failure_reason,
        new_jobs_so_far=cumulative_new_jobs,
        remaining_target=remaining,
    )


# ---------------------------------------------------------------------------
# Followup Planner (LLM-backed, best-effort)
# ---------------------------------------------------------------------------

_FOLLOWUP_SYSTEM_PROMPT = """\
You are a job search strategy advisor for a financial services job discovery pipeline.

You will receive:
1. The search objective (target roles, constraints, preferences)
2. The result from attempt 1 (what was found, what failed)
3. The failure diagnosis (why the attempt fell short)

Your task: Write a concise, actionable pivot_hint (2-5 sentences) telling the search agent
how to adjust strategy for attempt 2. The hint must:
- Directly address the failure type
- Be specific to the financial domain (name role families, source types, company types)
- Tell the agent what to DO differently, not just what went wrong
- Stay within the objective's hard constraints (location, seniority, exclusions)

For high_duplicates: Focus on companies and source families NOT yet covered.
  Suggest: specific company segments, direct ATS board types, niche aggregators.

For low_candidates: Expand the search vocabulary.
  Suggest: synonym titles, adjacent workstream families, broader company type inclusion.

For fetch_failures: Pivot to more accessible sources.
  Suggest: Greenhouse/Lever/Ashby over direct career pages, company-specific board URLs.

For budget_exhausted: Prioritize highest-yield lanes.
  Suggest: the 1-2 most productive query families, most reliable source types.

Output ONLY the pivot_hint text. No preamble, no labels, no JSON.
"""


def generate_followup_context(
    objective: SearchObjective,
    attempt_result: AttemptResult,
    evaluation: EvaluationResult,
    llm_client: Any,  # LLMClient or None
) -> dict[str, Any]:
    """
    Generate the AttemptContext dict for attempt 2.

    Uses an LLM call to produce a targeted pivot_hint. Degrades gracefully to a
    deterministic fallback if the LLM is unavailable or the call fails.

    Returns a dict matching the attempt_context schema in search_agent_input.schema.json.
    """
    # Build human-readable objective summary
    constraints = []
    hc = objective.hard_constraints or {}
    if hc.get("location"):
        constraints.append(f"Location: {', '.join(hc['location'])}")
    if hc.get("seniority"):
        constraints.append(f"Seniority: {', '.join(hc['seniority'])}")
    if hc.get("max_years_experience") is not None:
        constraints.append(f"Max experience: {hc['max_years_experience']} years")
    if hc.get("workstreams"):
        constraints.append(f"Workstreams: {', '.join(hc['workstreams'])}")
    if hc.get("exclusions"):
        constraints.append(f"Exclusions: {', '.join(hc['exclusions'])}")

    objective_summary = (
        f"Target: {objective.target_new_jobs} new jobs not yet in catalog\n"
        + ("\n".join(constraints) if constraints else "No hard constraints specified")
        + (f"\nAdditional instruction: {objective.additional_instruction}" if objective.additional_instruction else "")
    )

    attempt_summary = (
        f"Attempt {attempt_result.attempt_number} result:\n"
        f"  Candidates captured: {attempt_result.candidates_captured}\n"
        f"  New jobs inserted:   {attempt_result.new_jobs_inserted}\n"
        f"  Existing updated:    {attempt_result.existing_jobs_updated}\n"
        f"  Possible duplicates: {attempt_result.possible_duplicates}\n"
        f"  Fetch failures:      {attempt_result.jobs_failed}\n"
        f"  Companies seen:      {len(attempt_result.seen_companies)}\n"
        f"  Cumulative new jobs: {evaluation.new_jobs_so_far}/{objective.target_new_jobs}\n"
    )

    failure_summary = (
        f"Failure diagnosis:\n"
        f"  Type: {evaluation.failure_type}\n"
        f"  Reason: {evaluation.failure_reason}\n"
        f"\nRemaining target: {evaluation.remaining_target} more new jobs needed."
    )

    user_prompt = f"{objective_summary}\n\n{attempt_summary}\n{failure_summary}"

    pivot_hint: str | None = None

    if llm_client is not None:
        try:
            pivot_hint = llm_client.call(
                system=_FOLLOWUP_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=300,
            ).strip()
            logger.info("FollowupPlanner generated pivot_hint (len=%d)", len(pivot_hint))
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("FollowupPlanner LLM call failed, using deterministic fallback: %s", exc)
            pivot_hint = None

    if pivot_hint is None:
        pivot_hint = _deterministic_pivot_hint(evaluation.failure_type, attempt_result, objective)

    return {
        "attempt_number": 2,
        "max_attempts": objective.max_attempts,
        "target_new_jobs": objective.target_new_jobs,
        "remaining_target": evaluation.remaining_target,
        "seen_companies": attempt_result.seen_companies,
        "seen_urls": attempt_result.seen_urls,
        "previous_failure_summary": evaluation.failure_reason,
        "pivot_hint": pivot_hint,
    }


def _deterministic_pivot_hint(
    failure_type: str | None,
    attempt: AttemptResult,
    objective: SearchObjective,
) -> str:
    """Fallback pivot hint when LLM is unavailable."""
    n_seen = len(attempt.seen_companies)

    if failure_type == _FAILURE_TYPE_HIGH_DUPLICATES:
        return (
            f"Attempt 1 found mostly duplicates ({attempt.possible_duplicates} already in catalog). "
            f"Avoid the {n_seen} companies already captured. "
            "Switch to direct ATS board searches (Greenhouse, Lever, Ashby, Workday) "
            "and target company segments not yet covered: smaller asset managers, insurance firms, "
            "and regional banks. Reduce aggregator queries."
        )
    elif failure_type == _FAILURE_TYPE_LOW_CANDIDATES:
        return (
            f"Attempt 1 yielded very few candidates ({attempt.candidates_captured}). "
            "Broaden the search: use more title synonyms, include adjacent workstream families, "
            "and try company-name-specific queries. Consider expanding to related role families "
            "still within the hard constraints."
        )
    elif failure_type == _FAILURE_TYPE_FETCH_FAILURES:
        return (
            f"Attempt 1 had high fetch failures ({attempt.jobs_failed} failures). "
            "Pivot away from direct career pages to ATS-hosted postings: "
            "prefer Greenhouse, Lever, Ashby job board URLs. "
            "Search for the same roles at companies known to use accessible ATS platforms."
        )
    else:
        return (
            f"Attempt 1 inserted {attempt.new_jobs_inserted} new jobs. "
            f"{attempt.possible_duplicates} were duplicates. "
            "For attempt 2: prioritize the highest-yield search lanes, "
            "try different query formulations, and focus on direct company board postings "
            "for companies not yet covered."
        )


# ---------------------------------------------------------------------------
# Objective Controller
# ---------------------------------------------------------------------------


class ObjectiveController:
    """
    Orchestrates a multi-attempt discovery run to meet a SearchObjective.

    Usage:
        controller = ObjectiveController(objective, profile, llm_client)
        final_result = controller.run(
            discovery_intent=intent,
            profile_name=profile_id,
            search_brief=search_brief,
        )
    """

    def __init__(
        self,
        objective: SearchObjective,
        llm_client: Any | None,
    ) -> None:
        self._objective = objective
        self._llm_client = llm_client

    def run(
        self,
        *,
        profile_name: str,
        search_brief: str,
        discovery_intent: dict[str, Any] | None = None,
    ) -> FinalSearchResult:
        """
        Run up to max_attempts search attempts to meet the objective.

        Returns a FinalSearchResult with aggregate counters and per-attempt breakdown.
        """
        from career_intelligence.services.agent_service import run_discovery_session

        objective = self._objective
        all_attempts: list[AttemptResult] = []
        cumulative_new_jobs = 0
        attempt_context: dict[str, Any] | None = None
        last_session_id = ""

        for attempt_number in range(1, objective.max_attempts + 1):
            max_q, max_p = objective.per_attempt_budget(attempt_number)

            logger.info(
                "ObjectiveController: starting attempt %d/%d "
                "(target=%d, so_far=%d, queries=%d, pages=%d)",
                attempt_number, objective.max_attempts,
                objective.target_new_jobs, cumulative_new_jobs,
                max_q, max_p,
            )

            try:
                session_result = run_discovery_session(
                    profile_name=profile_name,
                    search_brief=search_brief,
                    mode="exploratory",
                    max_queries=max_q,
                    max_pages=max_p,
                    discovery_intent=discovery_intent,
                    attempt_context=attempt_context,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "ObjectiveController: attempt %d failed with exception: %s",
                    attempt_number, exc,
                )
                # Record a zero-result attempt so we can still aggregate
                session_result = {
                    "session_id": f"failed-attempt-{attempt_number}",
                    "queries_run": 0,
                    "candidates_captured": 0,
                    "jobs_fetched": 0,
                    "jobs_structured": 0,
                    "new_jobs_inserted": 0,
                    "existing_jobs_updated": 0,
                    "possible_duplicates": 0,
                    "jobs_failed": 0,
                    "duration_seconds": 0.0,
                    "search_complete": False,
                }
                # Re-raise so the caller (handle_search_run) can fail the task
                raise

            attempt = AttemptResult.from_session_result(attempt_number, session_result)
            all_attempts.append(attempt)
            cumulative_new_jobs += attempt.new_jobs_inserted
            last_session_id = attempt.session_id or last_session_id

            logger.info(
                "ObjectiveController: attempt %d complete: "
                "new_inserted=%d cumulative=%d/%d",
                attempt_number, attempt.new_jobs_inserted,
                cumulative_new_jobs, objective.target_new_jobs,
            )

            evaluation = evaluate_attempt(objective, attempt, cumulative_new_jobs)

            if evaluation.status == _STATUS_MET:
                logger.info(
                    "ObjectiveController: objective MET after %d attempt(s)", attempt_number,
                )
                return self._build_final_result(
                    all_attempts, cumulative_new_jobs, "met",
                    f"Objective met: {cumulative_new_jobs}/{objective.target_new_jobs} new jobs inserted.",
                    last_session_id,
                )

            if evaluation.status == _STATUS_GIVE_UP:
                logger.info(
                    "ObjectiveController: stopping after %d attempt(s): %s",
                    attempt_number, evaluation.failure_reason,
                )
                break

            # status == RETRY — generate followup context for next attempt
            attempt_context = generate_followup_context(
                objective=objective,
                attempt_result=attempt,
                evaluation=evaluation,
                llm_client=self._llm_client,
            )
            logger.info(
                "ObjectiveController: retry after attempt %d, failure_type=%s, pivot_hint=%.120s",
                attempt_number, evaluation.failure_type,
                (attempt_context.get("pivot_hint") or "")[:120],
            )

        # All attempts exhausted
        if cumulative_new_jobs >= objective.target_new_jobs:
            status = "met"
            reason = f"Objective met: {cumulative_new_jobs}/{objective.target_new_jobs} new jobs inserted."
        elif cumulative_new_jobs > 0:
            status = "partially_met"
            reason = (
                f"Partially met: {cumulative_new_jobs}/{objective.target_new_jobs} new jobs inserted "
                f"across {len(all_attempts)} attempt(s). "
            )
        else:
            status = "not_met"
            reason = (
                f"Objective not met: 0 new jobs inserted after {len(all_attempts)} attempt(s)."
            )

        return self._build_final_result(all_attempts, cumulative_new_jobs, status, reason, last_session_id)

    def _build_final_result(
        self,
        all_attempts: list[AttemptResult],
        cumulative_new_jobs: int,
        status: str,
        reason: str,
        last_session_id: str,
    ) -> FinalSearchResult:
        result = FinalSearchResult(
            objective_id=self._objective.objective_id,
            target_new_jobs=self._objective.target_new_jobs,
            attempts_run=len(all_attempts),
            status=status,
            reason=reason,
            total_new_jobs_inserted=cumulative_new_jobs,
            last_session_id=last_session_id,
        )
        for a in all_attempts:
            result.total_existing_jobs_updated += a.existing_jobs_updated
            result.total_possible_duplicates += a.possible_duplicates
            result.total_jobs_failed += a.jobs_failed
            result.total_candidates_captured += a.candidates_captured
            result.total_queries_run += a.queries_run
            result.total_duration_seconds += a.duration_seconds
            result.attempt_summaries.append({
                "attempt_number": a.attempt_number,
                "session_id": a.session_id,
                "new_jobs_inserted": a.new_jobs_inserted,
                "existing_jobs_updated": a.existing_jobs_updated,
                "possible_duplicates": a.possible_duplicates,
                "jobs_failed": a.jobs_failed,
                "candidates_captured": a.candidates_captured,
                "queries_run": a.queries_run,
                "duration_seconds": round(a.duration_seconds, 1),
            })
        return result
