"""
Role Researcher — supplements job record with company/department context.
MVP: 1-2 targeted web searches, no deep research chain.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class RoleContext:
    company_description: str = ""
    department_context: str = ""
    company_size_hint: str = ""
    business_lines: list[str] = None  # type: ignore
    research_sources: list[str] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.business_lines is None:
            self.business_lines = []
        if self.research_sources is None:
            self.research_sources = []


def research_role(company: str, title: str, llm_client=None) -> RoleContext:
    """
    Supplement company/role context.
    MVP: uses LLM knowledge for well-known firms; can be extended with web search.
    """
    if llm_client is None:
        return _llm_research(company, title)
    return _llm_research(company, title, llm_client)


_RESEARCH_SYSTEM_PROMPT = (
    "You are a concise financial services research assistant. "
    "Answer factually based on training knowledge. "
    "Acknowledge uncertainty when you have limited information."
)


def _llm_research(company: str, title: str, client=None) -> RoleContext:
    """Ask LLM for general company context based on training knowledge."""
    if client is None:
        from .llm_client import make_client
        client = make_client()
    if client is None:
        return RoleContext(company_description=f"Research unavailable for {company}")

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
            system=_RESEARCH_SYSTEM_PROMPT,
            user=prompt,
            max_tokens=512,
        )
        return RoleContext(
            company_description=text,
            research_sources=["llm_training_knowledge"],
        )
    except Exception as e:
        return RoleContext(
            company_description=f"Research failed: {e}",
            research_sources=[],
        )
