"""
Greenhouse Connector — uses the public Greenhouse boards API (no auth required).

API endpoints:
  Board list:   GET boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
  Single job:   GET boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from ..fetcher import FetchResult, _strip_html
from ..source_classifier import SourceClassification
from .base import BaseConnector, NormalizedJob

_API_BASE = "https://boards-api.greenhouse.io/v1/boards"
_TIMEOUT = 15.0
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; career-openclaw/0.1; +research-bot)",
    "Accept": "application/json",
}


def _extract_location(job: dict) -> str:
    loc = job.get("location", {})
    if isinstance(loc, dict):
        return loc.get("name", "")
    return str(loc) if loc else ""


def _parse_description(job: dict) -> str:
    """Extract plain text from Greenhouse job content field."""
    content = job.get("content", "")
    if not content:
        return ""
    if "<" in content:
        return _strip_html(content)
    return content.strip()


class GreenhouseConnector(BaseConnector):
    def __init__(self, boards_registry: dict | None = None) -> None:
        self._registry = boards_registry or {}

    def _resolve_slug(self, classification: SourceClassification) -> str:
        slug = classification.company_slug
        # Check registry for override
        for company, profile in self._registry.items():
            if profile.get("source") == "greenhouse":
                token = profile.get("board_token", "")
                if token == slug or company == slug:
                    return token
        return slug

    def fetch_job(self, url: str, classification: SourceClassification) -> FetchResult:
        slug = self._resolve_slug(classification)
        job_id = classification.job_external_id

        if not slug:
            return FetchResult(
                status="failed",
                error="Greenhouse: could not determine board slug from URL",
                source_type="greenhouse",
                failure_stage="classify",
                error_type="unsupported_source",
                retryable=False,
                recommended_next_actions=["check_company_boards_yaml", "use_html_fallback"],
            )

        if not job_id:
            # Board-level URL — try HTML fallback for the page
            from .html_fallback import HtmlFallbackConnector
            result = HtmlFallbackConnector().fetch_job(url, classification)
            result.source_type = "greenhouse"
            return result

        api_url = f"{_API_BASE}/{slug}/jobs/{job_id}"
        try:
            with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=_TIMEOUT) as client:
                resp = client.get(api_url)
                resp.raise_for_status()
            job = resp.json()
            text = _parse_description(job)
            return FetchResult(
                status="success" if text else "partial_success",
                text=text,
                content_length=len(text),
                source_type="greenhouse",
            )
        except httpx.HTTPStatusError as e:
            sc = e.response.status_code
            error_type = "blocked_403" if sc == 403 else ("not_found_404" if sc == 404 else f"http_{sc}")
            return FetchResult(
                status="failed",
                error=f"Greenhouse API HTTP {sc}: {api_url}",
                source_type="greenhouse",
                failure_stage="api_call",
                error_type=error_type,
                retryable=sc not in (403, 404),
                recommended_next_actions=["verify_board_token", "check_company_boards_yaml"],
            )
        except Exception as e:
            return FetchResult(
                status="failed",
                error=f"Greenhouse API error: {type(e).__name__}: {e}",
                source_type="greenhouse",
                failure_stage="api_call",
                error_type="unknown",
                retryable=True,
            )

    def sync_board(self, company_slug: str, board_profile: dict) -> list[NormalizedJob]:
        """Sync all active jobs for a company from its Greenhouse board."""
        slug = board_profile.get("board_token", company_slug)
        api_url = f"{_API_BASE}/{slug}/jobs?content=true"
        try:
            with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=30.0) as client:
                resp = client.get(api_url)
                resp.raise_for_status()
            data = resp.json()
            jobs_raw = data.get("jobs", [])
            results: list[NormalizedJob] = []
            for j in jobs_raw:
                job_url = j.get("absolute_url", "")
                title = j.get("title", "")
                location = _extract_location(j)
                text = _parse_description(j)
                job_id = str(j.get("id", ""))
                if job_url and title:
                    results.append(NormalizedJob(
                        url=job_url,
                        title=title,
                        company=company_slug,
                        location=location,
                        description_text=text,
                        source_type="greenhouse",
                        job_external_id=job_id,
                    ))
            return results
        except Exception as e:
            raise RuntimeError(f"Greenhouse board sync failed for {slug}: {e}") from e
