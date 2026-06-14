"""
Research Planner — derive targeted web-research queries from a job_record.

Pure functions, no filesystem IO, no CLI. Salvaged from the (removed)
career_prepare_research CLI. Used by research_service to build the input spec
handed to the career-research before a research-augmented Job Report.

Query derivation strategy (three-tier priority):
  1. high   : company + division_or_business_line  (explicit org name from JD)
  2. medium : company + top finance_domains
  3. low    : company + cleaned title keywords (always present as fallback)

When division_or_business_line is empty, a minimal LLM call extracts the most
search-relevant org name from inferred_team_context before falling back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_TITLE_NOISE_WORDS = frozenset({
    "senior", "sr", "junior", "jr", "lead", "staff", "principal", "associate",
    "assistant", "head", "vp", "director", "managing", "executive", "manager",
    "officer", "specialist", "analyst", "engineer", "developer", "consultant",
    "f/m/d", "f/m", "m/f/d",
})

_ORG_EXTRACT_SYSTEM = (
    "You are a concise data extractor. Extract the single most search-useful "
    "organizational unit name from the provided team context sentence. "
    "Return ONLY the name as a plain string — no quotes, no explanation. "
    "If no useful org name is present, return an empty string."
)


@dataclass
class ResearchPlan:
    """Derived research plan for a single job_record."""

    queries: list[dict[str, Any]] = field(default_factory=list)
    context_gaps: list[str] = field(default_factory=list)
    avoid_queries: list[str] = field(default_factory=list)
    org_name: str = ""
    org_name_source: str = "none"


def _clean_title_keywords(title: str) -> list[str]:
    """Return meaningful words from a job title, dropping noise words."""
    words = re.split(r"[\s,/\-()]+", title.lower())
    return [w for w in words if w and w not in _TITLE_NOISE_WORDS and len(w) > 2]


def _extract_org_name_via_llm(inferred_team_context: str, llm_client) -> str:
    """Use a minimal LLM call to pull the best org/team name from free text."""
    if not inferred_team_context.strip():
        return ""
    try:
        result = llm_client.call(
            system=_ORG_EXTRACT_SYSTEM,
            user=f"Team context: {inferred_team_context[:400]}",
            max_tokens=40,
        ).strip().strip('"').strip("'")
        # Reject suspiciously long results (hallucination guard)
        return result if len(result) <= 80 else ""
    except Exception:
        return ""


def _build_queries(job: dict[str, Any], org_name: str) -> list[dict[str, Any]]:
    """Build prioritised search queries from job_record fields."""
    company = (job.get("company") or "").strip()
    title = (job.get("title") or "").strip()
    finance_domains = [d for d in job.get("finance_domains", []) if d]
    queries: list[dict[str, Any]] = []

    # High priority: company + explicit org name
    if org_name:
        queries.append({
            "query": f'"{company}" "{org_name}"',
            "purpose": f"Understand what {org_name} covers within {company}",
            "priority": "high",
            "derived_from": (
                "division_or_business_line"
                if job.get("division_or_business_line")
                else "inferred_team_context_llm"
            ),
        })

    # Medium priority: company + top domain terms
    if finance_domains:
        top_domains = finance_domains[:3]
        domain_part = " ".join(f'"{d}"' for d in top_domains)
        queries.append({
            "query": f'"{company}" {domain_part}',
            "purpose": f"Confirm {company}'s scope in these domains",
            "priority": "medium",
            "derived_from": "finance_domains",
        })

    # Low priority: company + cleaned title keywords (always present as fallback)
    kw = _clean_title_keywords(title)
    if kw:
        kw_part = " ".join(f'"{w}"' for w in kw[:3])
        queries.append({
            "query": f'"{company}" {kw_part}',
            "purpose": f"Locate {company} team/role context for this position type",
            "priority": "low",
            "derived_from": "title_keywords",
        })

    return queries


def _build_context_gaps(job: dict[str, Any]) -> list[str]:
    """Derive research context gaps from job_record signals."""
    gaps: list[str] = []
    conf = job.get("classification_confidence", "")
    if conf in ("medium", "low"):
        gaps.append(
            "Workstream classification confidence is not high — research may clarify "
            "whether this role is analytics/risk/ops/engineering focused."
        )
    team_ctx = job.get("inferred_team_context", "")
    uncertainty_markers = ("appears to be", "likely", "possibly", "unclear", "uncertain")
    if any(m in team_ctx.lower() for m in uncertainty_markers):
        gaps.append("Team context contains uncertain language — confirm actual team scope.")
    if not job.get("division_or_business_line"):
        gaps.append(
            "JD did not explicitly name a division or business line — "
            "research should identify the team's place in the org."
        )
    return gaps


def _build_avoid_queries(job: dict[str, Any], org_name: str) -> list[str]:
    """Return generic queries that should be avoided when targeted ones exist."""
    company = (job.get("company") or "").strip()
    avoid: list[str] = []
    if org_name:
        avoid.append(f'"{company}" company overview')
        avoid.append(f'"{company}" about us')
    return avoid


def build_research_plan(job_record: dict[str, Any], llm_client=None) -> ResearchPlan:
    """
    Build a targeted research plan for one job_record.

    Resolves the best org name (explicit division first, then an optional minimal
    LLM extraction from inferred_team_context), then derives prioritised queries,
    context gaps, and avoid-queries. Pure with respect to the filesystem.
    """
    org_name = (job_record.get("division_or_business_line") or "").strip()
    org_source = "division_or_business_line"
    if not org_name and llm_client is not None:
        team_ctx = job_record.get("inferred_team_context", "")
        if team_ctx.strip():
            org_name = _extract_org_name_via_llm(team_ctx, llm_client)
            org_source = "inferred_team_context_llm"

    return ResearchPlan(
        queries=_build_queries(job_record, org_name),
        context_gaps=_build_context_gaps(job_record),
        avoid_queries=_build_avoid_queries(job_record, org_name),
        org_name=org_name,
        org_name_source=org_source if org_name else "none",
    )
