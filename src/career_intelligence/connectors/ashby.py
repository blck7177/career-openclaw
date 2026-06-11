"""
Ashby Connector — uses the public Ashby posting API (no auth required).

API endpoints:
  Board list:  GET api.ashbyhq.com/posting-api/job-board/{board_name}
  (No separate single-job endpoint; board response includes all jobs with descriptions.)
"""

from __future__ import annotations

import httpx

from ..fetcher import FetchResult, _strip_html
from ..source_classifier import SourceClassification
from .base import BaseConnector, NormalizedJob

_API_BASE = "https://api.ashbyhq.com/posting-api/job-board"
_TIMEOUT = 15.0
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; career-openclaw/0.1; +research-bot)",
    "Accept": "application/json",
}


def _parse_description(job: dict) -> str:
    text = job.get("descriptionPlain", "") or ""
    if not text:
        html = job.get("descriptionHtml", "") or ""
        if html:
            text = _strip_html(html)
    return text.strip()


def _extract_location(job: dict) -> str:
    loc = job.get("location", "")
    if isinstance(loc, str):
        return loc
    return ""


class AshbyConnector(BaseConnector):
    def __init__(self, boards_registry: dict | None = None) -> None:
        self._registry = boards_registry or {}
        # board cache: slug → list of job dicts (populated on first sync)
        self._board_cache: dict[str, list[dict]] = {}

    def _resolve_slug(self, classification: SourceClassification) -> str:
        return classification.company_slug

    def _fetch_board(self, slug: str) -> list[dict]:
        if slug in self._board_cache:
            return self._board_cache[slug]
        api_url = f"{_API_BASE}/{slug}"
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=_TIMEOUT) as client:
            resp = client.get(api_url)
            resp.raise_for_status()
        data = resp.json()
        jobs = data.get("jobs", [])
        self._board_cache[slug] = jobs
        return jobs

    def fetch_job(self, url: str, classification: SourceClassification) -> FetchResult:
        slug = self._resolve_slug(classification)
        job_id = classification.job_external_id

        if not slug:
            return FetchResult(
                status="failed",
                error="Ashby: could not determine board slug from URL",
                source_type="ashby",
                failure_stage="classify",
                error_type="unsupported_source",
                retryable=False,
            )

        try:
            jobs = self._fetch_board(slug)
        except httpx.HTTPStatusError as e:
            sc = e.response.status_code
            error_type = "blocked_403" if sc == 403 else ("not_found_404" if sc == 404 else f"http_{sc}")
            return FetchResult(
                status="failed",
                error=f"Ashby board API HTTP {sc}: {slug}",
                source_type="ashby",
                failure_stage="api_call",
                error_type=error_type,
                retryable=sc not in (403, 404),
            )
        except Exception as e:
            return FetchResult(
                status="failed",
                error=f"Ashby board API error: {type(e).__name__}: {e}",
                source_type="ashby",
                failure_stage="api_call",
                error_type="unknown",
                retryable=True,
            )

        # Find the specific job by ID or URL match
        matched = None
        for j in jobs:
            if job_id and str(j.get("id", "")) == job_id:
                matched = j
                break
            if j.get("jobUrl", "") == url or j.get("applyUrl", "") == url:
                matched = j
                break

        if matched is None:
            # Fall back to HTML fetch if job not found in board listing
            from .html_fallback import HtmlFallbackConnector
            result = HtmlFallbackConnector().fetch_job(url, classification)
            result.source_type = "ashby"
            return result

        text = _parse_description(matched)
        return FetchResult(
            status="success" if text else "partial_success",
            text=text,
            content_length=len(text),
            source_type="ashby",
        )

    def sync_board(self, company_slug: str, board_profile: dict) -> list[NormalizedJob]:
        slug = board_profile.get("board_token", company_slug)
        try:
            jobs = self._fetch_board(slug)
        except Exception as e:
            raise RuntimeError(f"Ashby board sync failed for {slug}: {e}") from e

        results: list[NormalizedJob] = []
        for j in jobs:
            job_url = j.get("jobUrl", "") or j.get("applyUrl", "")
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
                    source_type="ashby",
                    job_external_id=job_id,
                ))
        return results
