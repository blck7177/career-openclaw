"""
Workday Connector — best-effort HTML fetch for Workday career pages.

Workday uses heavy JavaScript rendering, so most detail pages fail with
dynamic_render_failed. This connector wraps the HTML fallback and annotates
failures with structured diagnostics so the agent knows to use aggregator
search instead.
"""

from __future__ import annotations

from ..fetcher import FetchResult
from ..source_classifier import SourceClassification
from .base import BaseConnector, NormalizedJob

_WORKDAY_NEXT_ACTIONS = [
    "search_aggregator_for_workday_companies",
    "mark_hard_source",
    "use_linkedin_search_for_company",
]


class WorkdayConnector(BaseConnector):
    def __init__(self, boards_registry: dict | None = None) -> None:
        self._registry = boards_registry or {}

    def fetch_job(self, url: str, classification: SourceClassification) -> FetchResult:
        """Best-effort fetch: try HTML, annotate failure with Workday diagnostics."""
        from .html_fallback import HtmlFallbackConnector
        result = HtmlFallbackConnector().fetch_job(url, classification)
        result.source_type = "workday"

        if result.status == "failed":
            # Workday pages typically fail due to JS rendering, not network errors
            if result.error_type in ("", "unknown"):
                result.error_type = "dynamic_render_failed"
                result.retryable = False
            result.recommended_next_actions = _WORKDAY_NEXT_ACTIONS
            return result

        # Success — but check if the content looks like a real JD
        # (Workday search pages often return the search/listing page instead of JD)
        if result.text and len(result.text) < 500:
            return FetchResult(
                status="failed",
                error="Workday: fetched page appears to be a listing page, not a JD",
                source_type="workday",
                failure_stage="parse_response",
                error_type="dynamic_render_failed",
                retryable=False,
                recommended_next_actions=_WORKDAY_NEXT_ACTIONS,
            )

        return result

    def sync_board(self, company_slug: str, board_profile: dict) -> list[NormalizedJob]:
        """Workday board sync is not supported — always raises with guidance."""
        raise NotImplementedError(
            f"Workday board sync is not supported for {company_slug}. "
            "Use search aggregator (LinkedIn, Indeed) to discover Workday jobs."
        )
