"""
Connector Router — entry point for all fetch operations in the pipeline.

Takes a URL + boards registry, classifies the source, routes to the
appropriate connector, and returns a FetchResult with structured diagnostics.

Usage:
    from career_intelligence.connectors.connector_router import route, sync_board

    result = route(url, boards_registry)
    jobs = sync_board(company_slug, boards_registry)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..fetcher import FetchResult
from ..source_classifier import SourceClassification, classify_source
from .ashby import AshbyConnector
from .base import NormalizedJob
from .greenhouse import GreenhouseConnector
from .html_fallback import HtmlFallbackConnector
from .lever import LeverConnector
from .workday import WorkdayConnector


def load_company_boards(workspace_root: Path | str | None = None) -> dict:
    """
    Load configs/company_boards.yaml relative to workspace_root.

    Falls back to empty dict if file not found.
    """
    if workspace_root is None:
        # Resolve relative to this file: connectors/ → career_intelligence/ → src/ → workspace
        workspace_root = Path(__file__).parent.parent.parent.parent
    path = Path(workspace_root) / "configs" / "company_boards.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def route(url: str, boards_registry: dict | None = None) -> FetchResult:
    """
    Classify URL and route to the correct connector.

    Args:
        url: Job posting URL (may be any ATS or HTML page).
        boards_registry: Optional dict from company_boards.yaml.
                         If None, loaded automatically from configs/.

    Returns:
        FetchResult with source diagnostics populated.
    """
    if boards_registry is None:
        boards_registry = load_company_boards()

    classification: SourceClassification = classify_source(url)

    match classification.source_type:
        case "greenhouse":
            connector = GreenhouseConnector(boards_registry)
        case "lever":
            connector = LeverConnector(boards_registry)
        case "ashby":
            connector = AshbyConnector(boards_registry)
        case "workday":
            connector = WorkdayConnector(boards_registry)
        case _:
            connector = HtmlFallbackConnector()

    return connector.fetch_job(url, classification)


def sync_board(company_slug: str, boards_registry: dict | None = None) -> list[NormalizedJob]:
    """
    Sync all active jobs for a company from its ATS board.

    Args:
        company_slug: Key from company_boards.yaml (e.g. "schonfeld").
        boards_registry: Optional dict from company_boards.yaml.

    Returns:
        List of NormalizedJob records.

    Raises:
        ValueError: if company_slug not found in registry or source type unknown.
        NotImplementedError: if the source type doesn't support board sync.
    """
    if boards_registry is None:
        boards_registry = load_company_boards()

    if company_slug not in boards_registry:
        raise ValueError(
            f"Company '{company_slug}' not found in company_boards.yaml. "
            "Add it first or check the slug spelling."
        )

    profile = boards_registry[company_slug]
    source = profile.get("source", "html")

    match source:
        case "greenhouse":
            connector: Any = GreenhouseConnector(boards_registry)
        case "lever":
            connector = LeverConnector(boards_registry)
        case "ashby":
            connector = AshbyConnector(boards_registry)
        case "workday":
            connector = WorkdayConnector(boards_registry)
        case _:
            connector = HtmlFallbackConnector()

    return connector.sync_board(company_slug, profile)
