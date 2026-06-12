"""
LLM Role Context — lightweight company/role background from LLM training knowledge.

This module provides a quick context hint for the extraction pipeline (runner.py Step 2).
It is NOT web search. It uses the LLM's training knowledge to produce a short company
description that helps extract_fields() interpret domain-specific JD language.

Architecture boundary:
  llm_role_context  →  extract_fields() in runner.py  (job_record extraction aid)
  research_notes/   →  role_analyzer.py Layer 1       (role dossier web research context)

These two are separate and must not be confused. This module never writes research_notes files
and is never consumed by career_analyze_roles.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMRoleContext:
    company_description: str = ""
    department_context: str = ""
    company_size_hint: str = ""
    business_lines: list[str] = None  # type: ignore
    context_sources: list[str] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.business_lines is None:
            self.business_lines = []
        if self.context_sources is None:
            self.context_sources = []


def get_llm_role_context(company: str, title: str, llm_client=None) -> LLMRoleContext:
    """
    Return a lightweight company/role context hint from LLM training knowledge.

    Used by runner.py to give extract_fields() enough domain context to correctly
    interpret JD language. Not a substitute for web-based research notes.
    """
    if llm_client is None:
        return _query_llm(company, title)
    return _query_llm(company, title, llm_client)


_SYSTEM_PROMPT = (
    "You are a concise financial services research assistant. "
    "Answer factually based on training knowledge. "
    "Acknowledge uncertainty when you have limited information."
)


def _query_llm(company: str, title: str, client=None) -> LLMRoleContext:
    """Ask LLM for general company context based on training knowledge."""
    if client is None:
        from .llm_client import make_client
        client = make_client()
    if client is None:
        return LLMRoleContext(company_description=f"Context unavailable for {company}")

    prompt = (
        f"Provide a brief context for a job seeker researching: {company} — role: {title}\n\n"
        "Answer with:\n"
        "1. Company description (1-2 sentences, focus on financial services relevance)\n"
        "2. Relevant department/division context for this role type\n"
        "3. Company size (rough: boutique / mid-size / large bank / global SIFI)\n"
        "4. Key business lines relevant to this role\n\n"
        "Keep each answer to 1-2 sentences. If you don't have reliable information, say so."
    )

    try:
        text = client.call(
            system=_SYSTEM_PROMPT,
            user=prompt,
            max_tokens=512,
        )
        return LLMRoleContext(
            company_description=text,
            context_sources=["llm_training_knowledge"],
        )
    except Exception as e:
        return LLMRoleContext(
            company_description=f"Context fetch failed: {e}",
            context_sources=[],
        )
