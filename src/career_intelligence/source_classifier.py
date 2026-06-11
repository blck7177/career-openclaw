"""
Source Classifier — deterministic URL → ATS type classification.

Pure pattern matching, no network calls. Used by connector_router and
career_classify_source wrapper to decide which connector to use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class SourceClassification:
    source_type: str        # "greenhouse" | "lever" | "ashby" | "workday" | "html"
    company_slug: str       # e.g. "schonfeld", "stripe", "" if unknown
    job_external_id: str    # ATS-native job ID, "" if not parseable
    confidence: float       # 1.0 = definitive pattern match, 0.5 = best-guess
    route_to: str           # connector key: "greenhouse" | "lever" | "ashby" | "workday" | "html"


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

_GREENHOUSE_PATTERNS = [
    # boards.greenhouse.io/{slug}/jobs/{id}
    re.compile(r"boards\.greenhouse\.io/([^/?#]+)/jobs/(\d+)", re.IGNORECASE),
    # job-boards.greenhouse.io/{slug}/jobs/{id}
    re.compile(r"job-boards\.greenhouse\.io/([^/?#]+)/jobs/(\d+)", re.IGNORECASE),
    # boards-api.greenhouse.io/v1/boards/{slug}/jobs/{id}
    re.compile(r"boards-api\.greenhouse\.io/[^/]+/boards/([^/?#]+)/jobs/(\d+)", re.IGNORECASE),
]

_LEVER_PATTERNS = [
    # jobs.lever.co/{slug}/{id}
    re.compile(r"jobs\.lever\.co/([^/?#]+)/([0-9a-f-]{36})", re.IGNORECASE),
    # api.lever.co/v0/postings/{slug}/{id}
    re.compile(r"api\.lever\.co/v0/postings/([^/?#]+)/([0-9a-f-]{36})", re.IGNORECASE),
]

_ASHBY_PATTERNS = [
    # jobs.ashbyhq.com/{board}/{id}
    re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", re.IGNORECASE),
    # ashbyhq.com/posting-api/job-board/{board}
    re.compile(r"ashbyhq\.com/([^/?#]+)", re.IGNORECASE),
]

_WORKDAY_MYWORKDAY_RE = re.compile(r"myworkday\.com/([^/?#]+)/", re.IGNORECASE)


def classify_source(url: str) -> SourceClassification:
    """
    Classify a job posting URL into its ATS type.

    Returns a SourceClassification with source_type, company_slug,
    job_external_id, confidence, and route_to.
    """
    if not url:
        return SourceClassification(
            source_type="html",
            company_slug="",
            job_external_id="",
            confidence=0.0,
            route_to="html",
        )

    # --- Greenhouse ---
    for pattern in _GREENHOUSE_PATTERNS:
        m = pattern.search(url)
        if m:
            return SourceClassification(
                source_type="greenhouse",
                company_slug=m.group(1).lower(),
                job_external_id=m.group(2),
                confidence=1.0,
                route_to="greenhouse",
            )

    # Greenhouse board-level URL (no job id)
    if re.search(r"(boards|job-boards|boards-api)\.greenhouse\.io", url, re.IGNORECASE):
        slug_m = re.search(
            r"(?:boards|job-boards)\.greenhouse\.io/([^/?#]+)", url, re.IGNORECASE
        )
        slug = slug_m.group(1).lower() if slug_m else ""
        return SourceClassification(
            source_type="greenhouse",
            company_slug=slug,
            job_external_id="",
            confidence=0.9,
            route_to="greenhouse",
        )

    # --- Lever ---
    for pattern in _LEVER_PATTERNS:
        m = pattern.search(url)
        if m:
            return SourceClassification(
                source_type="lever",
                company_slug=m.group(1).lower(),
                job_external_id=m.group(2),
                confidence=1.0,
                route_to="lever",
            )

    # Lever board-level
    if re.search(r"jobs\.lever\.co/([^/?#]+)/?$", url, re.IGNORECASE):
        slug_m = re.search(r"jobs\.lever\.co/([^/?#]+)", url, re.IGNORECASE)
        slug = slug_m.group(1).lower() if slug_m else ""
        return SourceClassification(
            source_type="lever",
            company_slug=slug,
            job_external_id="",
            confidence=0.9,
            route_to="lever",
        )

    # --- Ashby ---
    for pattern in _ASHBY_PATTERNS:
        m = pattern.search(url)
        if m:
            job_id = m.group(2) if pattern.groups == 2 else ""  # type: ignore[attr-defined]
            try:
                job_id = m.group(2)
            except IndexError:
                job_id = ""
            return SourceClassification(
                source_type="ashby",
                company_slug=m.group(1).lower(),
                job_external_id=job_id,
                confidence=1.0,
                route_to="ashby",
            )

    # --- Workday ---
    # Use URL parsing to reliably extract tenant from *.myworkdayjobs.com
    try:
        hostname = urlparse(url).hostname or ""
    except Exception:
        hostname = ""
    if hostname.lower().endswith(".myworkdayjobs.com"):
        subdomain = hostname[: -len(".myworkdayjobs.com")]
        # Tenant is the first label of the subdomain (e.g. "jpmc" from "jpmc.wd5")
        tenant = subdomain.split(".")[0].lower()
        return SourceClassification(
            source_type="workday",
            company_slug=tenant,
            job_external_id="",
            confidence=1.0,
            route_to="workday",
        )
    m = _WORKDAY_MYWORKDAY_RE.search(url)
    if m:
        return SourceClassification(
            source_type="workday",
            company_slug=m.group(1).lower(),
            job_external_id="",
            confidence=1.0,
            route_to="workday",
        )

    # --- HTML fallback ---
    return SourceClassification(
        source_type="html",
        company_slug="",
        job_external_id="",
        confidence=0.5,
        route_to="html",
    )
