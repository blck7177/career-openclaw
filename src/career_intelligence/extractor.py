"""
Structured Extractor — extracts job record fields from raw JD text via LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_EXTRACTION_SYSTEM_PROMPT = """\
You are a structured job description extractor for a finance career intelligence system.

Rules:
1. Extract only information explicitly stated in the JD. Do not infer or hallucinate.
2. For inferred fields (likely_tasks, likely_stakeholders, inferred_team_context), you may infer
   from JD context but must provide evidence_from_jd for each inferred field.
3. Use exact quoted phrases from the JD as evidence.
4. If a field cannot be extracted, use an empty list [] or empty string "".
5. seniority_inferred: infer from title or requirements (analyst/associate/vp/director/md).
6. finance_domains: list of finance domains mentioned (e.g. derivatives, fixed income, equities).
7. tools_mentioned: list of tools/systems/languages explicitly named.

Output valid JSON only, matching the schema exactly.
"""

_EXTRACTION_USER_TEMPLATE = """\
Extract structured fields from this job description.

Company: {company}
Title: {title}
Role Context: {role_context}

Job Description:
{jd_text}

Output JSON with these fields:
{{
  "responsibilities": ["..."],
  "required_skills": ["..."],
  "preferred_skills": ["..."],
  "tools_mentioned": ["..."],
  "finance_domains": ["..."],
  "seniority_inferred": "analyst|associate|vp|director|md|unknown",
  "likely_tasks": ["..."],
  "likely_stakeholders": ["..."],
  "inferred_team_context": "...",
  "division_or_business_line": "If the JD explicitly names a specific division, business line, desk, group, or team within the company (e.g. 'Global Markets Risk', 'Risk Platform team', 'Group Governance', 'IBD', 'Fixed Income'), extract that name verbatim. Empty string if no such org name is explicitly stated in the JD.",
  "evidence_from_jd": {{
    "likely_tasks": "...",
    "likely_stakeholders": "...",
    "inferred_team_context": "..."
  }}
}}
"""


def extract_fields(
    jd_text: str,
    company: str,
    title: str,
    role_context: str = "",
    llm_client=None,
) -> dict[str, Any]:
    """Extract structured fields from raw JD text."""
    if llm_client is None:
        llm_client = _get_default_client()

    if llm_client is None:
        return _empty_extraction(reason="LLM client unavailable")

    prompt = _EXTRACTION_USER_TEMPLATE.format(
        company=company,
        title=title,
        role_context=role_context[:500] if role_context else "N/A",
        jd_text=jd_text[:6000],
    )

    for attempt in range(3):
        try:
            text = llm_client.call(
                system=_EXTRACTION_SYSTEM_PROMPT,
                user=prompt,
                max_tokens=2048,
            ).strip()
            if "```" in text:
                text = text.split("```")[1].lstrip("json").strip()
            data = json.loads(text)
            return _normalize_extraction(data)
        except json.JSONDecodeError as e:
            if attempt == 2:
                return _empty_extraction(reason=f"JSON parse error after 3 attempts: {e}")
        except Exception as e:
            if attempt == 2:
                return _empty_extraction(reason=f"LLM call failed: {e}")

    return _empty_extraction(reason="extraction failed")


def _get_default_client():
    from .llm_client import make_client
    return make_client()


def _normalize_extraction(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize extracted data to expected types."""
    list_fields = ["responsibilities", "required_skills", "preferred_skills",
                   "tools_mentioned", "finance_domains", "likely_tasks", "likely_stakeholders"]
    for field in list_fields:
        val = data.get(field)
        if not isinstance(val, list):
            data[field] = [val] if isinstance(val, str) and val else []
    if not isinstance(data.get("evidence_from_jd"), dict):
        data["evidence_from_jd"] = {}
    if not isinstance(data.get("seniority_inferred"), str):
        data["seniority_inferred"] = "unknown"
    if not isinstance(data.get("inferred_team_context"), str):
        data["inferred_team_context"] = ""
    if not isinstance(data.get("division_or_business_line"), str):
        data["division_or_business_line"] = ""
    return data


def _empty_extraction(reason: str = "") -> dict[str, Any]:
    return {
        "responsibilities": [],
        "required_skills": [],
        "preferred_skills": [],
        "tools_mentioned": [],
        "finance_domains": [],
        "seniority_inferred": "unknown",
        "likely_tasks": [],
        "likely_stakeholders": [],
        "inferred_team_context": "",
        "division_or_business_line": "",
        "evidence_from_jd": {"_extraction_error": reason},
    }
