"""
JD Fetcher — fetches raw job description text from a source URL.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx


@dataclass
class FetchResult:
    status: str                           # "success" | "failed" | "partial_success"
    text: str = ""
    error: str = ""
    content_length: int = 0
    # --- source diagnostics (added in intelligence-layer upgrade) ---
    source_type: str = "unknown"          # "greenhouse" | "lever" | "ashby" | "workday" | "html" | "unknown"
    failure_stage: str = ""               # "classify" | "api_call" | "parse_response" | "fetch_html"
    error_type: str = ""                  # "blocked_403" | "not_found_404" | "timeout" | "dynamic_render_failed" | "unsupported_source"
    retryable: bool = True
    recommended_next_actions: list = field(default_factory=list)


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; career-openclaw/0.1; +research-bot)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_MAX_CONTENT_BYTES = 200_000  # 200KB cap on raw JD content


def _strip_html(html: str) -> str:
    """Minimal HTML stripping — removes tags and decodes basic entities."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text.strip()


def fetch_jd(url: str, timeout: float = 15.0, delay: float = 1.0) -> FetchResult:
    """
    Fetch raw JD text from a URL.
    Returns FetchResult with status and text.
    """
    time.sleep(delay)
    try:
        with httpx.Client(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            response = client.get(url)
            response.raise_for_status()

        content = response.text[:_MAX_CONTENT_BYTES]
        content_type = response.headers.get("content-type", "")

        if "html" in content_type:
            text = _strip_html(content)
        else:
            text = content

        return FetchResult(
            status="success",
            text=text,
            content_length=len(text),
            source_type="html",
        )

    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        error_type = "blocked_403" if status_code == 403 else (
            "not_found_404" if status_code == 404 else f"http_{status_code}"
        )
        return FetchResult(
            status="failed",
            error=f"HTTP {status_code}: {e.request.url}",
            source_type="html",
            failure_stage="fetch_html",
            error_type=error_type,
            retryable=status_code not in (403, 404),
        )
    except httpx.TimeoutException:
        return FetchResult(
            status="failed",
            error=f"Timeout fetching {url}",
            source_type="html",
            failure_stage="fetch_html",
            error_type="timeout",
            retryable=True,
        )
    except Exception as e:
        return FetchResult(
            status="failed",
            error=f"{type(e).__name__}: {e}",
            source_type="html",
            failure_stage="fetch_html",
            error_type="unknown",
            retryable=True,
        )


def save_raw_jd(text: str, raw_jds_dir: Path, job_id: str) -> str:
    """Save raw JD text to file, return relative path."""
    raw_jds_dir.mkdir(parents=True, exist_ok=True)
    path = raw_jds_dir / f"{job_id}.txt"
    path.write_text(text, encoding="utf-8")
    return str(path.relative_to(raw_jds_dir.parent.parent))
