"""
Lever Connector — uses the public Lever postings API (no auth required).

API endpoints:
  Board list:    GET api.lever.co/v0/postings/{slug}?mode=json[&offset=&limit=]
  Single job:    GET api.lever.co/v0/postings/{slug}/{id}
"""

from __future__ import annotations

import httpx

from ..fetcher import FetchResult, _strip_html
from ..source_classifier import SourceClassification
from .base import BaseConnector, NormalizedJob

_API_BASE = "https://api.lever.co/v0/postings"
_TIMEOUT = 15.0
_PAGE_LIMIT = 100
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; career-openclaw/0.1; +research-bot)",
    "Accept": "application/json",
}


def _parse_lever_text(posting: dict) -> str:
    """Extract plain text from Lever posting content lists."""
    parts: list[str] = []
    for section in posting.get("lists", []):
        parts.append(section.get("text", ""))
        for item in section.get("content", []):
            parts.append(f"• {item}")
    for section in posting.get("additional", []):
        content = section.get("content", "")
        if content:
            parts.append(_strip_html(content) if "<" in content else content)
    text = posting.get("text", "") or posting.get("descriptionPlain", "")
    if text:
        parts.insert(0, text)
    return "\n".join(p for p in parts if p).strip()


class LeverConnector(BaseConnector):
    def __init__(self, boards_registry: dict | None = None) -> None:
        self._registry = boards_registry or {}

    def _resolve_slug(self, classification: SourceClassification) -> str:
        slug = classification.company_slug
        for company, profile in self._registry.items():
            if profile.get("source") == "lever":
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
                error="Lever: could not determine company slug from URL",
                source_type="lever",
                failure_stage="classify",
                error_type="unsupported_source",
                retryable=False,
            )

        if not job_id:
            from .html_fallback import HtmlFallbackConnector
            result = HtmlFallbackConnector().fetch_job(url, classification)
            result.source_type = "lever"
            return result

        api_url = f"{_API_BASE}/{slug}/{job_id}"
        try:
            with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=_TIMEOUT) as client:
                resp = client.get(api_url)
                resp.raise_for_status()
            posting = resp.json()
            text = _parse_lever_text(posting)
            return FetchResult(
                status="success" if text else "partial_success",
                text=text,
                content_length=len(text),
                source_type="lever",
            )
        except httpx.HTTPStatusError as e:
            sc = e.response.status_code
            error_type = "blocked_403" if sc == 403 else ("not_found_404" if sc == 404 else f"http_{sc}")
            return FetchResult(
                status="failed",
                error=f"Lever API HTTP {sc}: {api_url}",
                source_type="lever",
                failure_stage="api_call",
                error_type=error_type,
                retryable=sc not in (403, 404),
            )
        except Exception as e:
            return FetchResult(
                status="failed",
                error=f"Lever API error: {type(e).__name__}: {e}",
                source_type="lever",
                failure_stage="api_call",
                error_type="unknown",
                retryable=True,
            )

    def sync_board(self, company_slug: str, board_profile: dict) -> list[NormalizedJob]:
        """Sync all active postings for a company from its Lever board (paginated)."""
        slug = board_profile.get("board_token", company_slug)
        results: list[NormalizedJob] = []
        offset = 0
        while True:
            api_url = f"{_API_BASE}/{slug}?mode=json&limit={_PAGE_LIMIT}&offset={offset}"
            try:
                with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=30.0) as client:
                    resp = client.get(api_url)
                    resp.raise_for_status()
                postings = resp.json()
            except Exception as e:
                raise RuntimeError(f"Lever board sync failed for {slug}: {e}") from e

            if not postings:
                break
            for p in postings:
                job_url = p.get("hostedUrl", "")
                title = p.get("text", "")
                location_data = p.get("categories", {})
                location = location_data.get("location", "") if isinstance(location_data, dict) else ""
                text = _parse_lever_text(p)
                job_id = p.get("id", "")
                if job_url and title:
                    results.append(NormalizedJob(
                        url=job_url,
                        title=title,
                        company=company_slug,
                        location=location,
                        description_text=text,
                        source_type="lever",
                        job_external_id=job_id,
                    ))
            if len(postings) < _PAGE_LIMIT:
                break
            offset += _PAGE_LIMIT
        return results
