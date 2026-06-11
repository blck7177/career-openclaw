"""
Base connector types.

Defines NormalizedJob (shared output schema) and BaseConnector (interface).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..fetcher import FetchResult


@dataclass
class NormalizedJob:
    """Connector-output job record, compatible with the existing pipeline schema."""
    url: str
    title: str
    company: str
    location: str = ""
    description_text: str = ""   # plain text JD, used as `text` in FetchResult
    source_type: str = "html"    # connector type that produced this record
    job_external_id: str = ""    # ATS-native ID
    extra: dict = field(default_factory=dict)

    def to_fetch_result(self) -> FetchResult:
        """Convert to a FetchResult compatible with the existing runner pipeline."""
        return FetchResult(
            status="success" if self.description_text else "partial_success",
            text=self.description_text,
            content_length=len(self.description_text),
            source_type=self.source_type,
        )


class BaseConnector(ABC):
    """Abstract base for all ATS connectors."""

    @abstractmethod
    def fetch_job(self, url: str, classification: Any) -> FetchResult:
        """
        Fetch a single job posting.

        Args:
            url: The original job posting URL.
            classification: SourceClassification from source_classifier.

        Returns:
            FetchResult with populated source diagnostics fields.
        """

    def sync_board(self, company_slug: str, board_profile: dict) -> list[NormalizedJob]:
        """
        Sync all active jobs from a company's ATS board.

        Default implementation raises NotImplementedError — override in
        connectors that support board-level sync (Greenhouse, Lever, Ashby).
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support board-level sync"
        )
