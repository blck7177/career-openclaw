"""
HTML Fallback Connector — wraps the existing fetcher.fetch_jd() for URLs
that don't match any structured ATS pattern.
"""

from __future__ import annotations

from ..fetcher import FetchResult, fetch_jd
from ..source_classifier import SourceClassification
from .base import BaseConnector, NormalizedJob


class HtmlFallbackConnector(BaseConnector):
    """Wraps fetcher.fetch_jd() and ensures source_type="html" is set."""

    def fetch_job(self, url: str, classification: SourceClassification) -> FetchResult:
        result = fetch_jd(url)
        # Preserve source_type from caller if set (e.g. "workday" wrapping html)
        if result.source_type in ("unknown", "html", ""):
            result.source_type = "html"
        return result

    def sync_board(self, company_slug: str, board_profile: dict) -> list[NormalizedJob]:
        """HTML fallback has no board-level sync capability."""
        raise NotImplementedError(
            f"HTML fallback connector does not support board-level sync for {company_slug}. "
            "Board sync is only available for Greenhouse, Lever, and Ashby."
        )
