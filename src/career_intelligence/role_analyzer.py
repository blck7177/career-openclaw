"""
Role Analyzer — two-layer role dossier generation.

Layer 1: Narrative Role Dossier Report
  - Unconstrained reasoning: what the role is, what business problem it solves,
    what underlying capabilities the JD implies.
  - Output: markdown report (English).

Layer 2: Structured Role Dossier Schema
  - Canonicalizes Layer 1 into queryable JSON.
  - Does NOT re-analyze the JD. Uses Layer 1 as primary source.
  - Output: dict matching role_dossier.schema.json.

Usage:
    from career_intelligence.role_analyzer import analyze_role

    report_md, dossier = analyze_role(
        jd_text=...,
        job_record=...,       # dict from jobs_structured.json
        taxonomy=...,         # list of workstream dicts from workstream_taxonomy.yaml
        llm_client=...,
    )
"""

from __future__ import annotations

import json
from typing import Any

ANALYSIS_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Layer 1: Narrative Role Dossier Report
# ---------------------------------------------------------------------------

_LAYER1_SYSTEM_PROMPT = """\
# Generalized Role Dossier Prompt — Layer 1

## Role

You are a career intelligence analyst. Your task is to analyze a job description and produce a narrative Role Dossier that explains what the role actually does, what business or organizational problem it solves, and what underlying capabilities are required.

This is an analysis task, not a resume-writing task.

## Objective

Produce a deep, evidence-based role analysis report from the provided job description.

The goal is to answer:

> What kind of person is this role really looking for, and what capabilities does the JD imply beyond its surface keywords?

## Input

You may receive some or all of the following:

* Job title
* Company name
* Location
* Job description text
* Source URL
* Existing structured JD extraction
* Existing role taxonomy or workstream taxonomy
* Optional company or team research notes

Use the job description as the primary source of truth. Use any external or company research only as supporting context.

## Non-Goals

Do not write resume bullets.

Do not rewrite the candidate's resume.

Do not evaluate any specific candidate.

Do not infer candidate fit.

Do not recommend resume edits.

Do not produce cover letter content.

Do not fill the final database schema.

Do not reduce the analysis to keyword extraction.

This layer should produce a narrative analytical report. A separate downstream step will convert the report into a structured schema.

## Analysis Rules

1. Analyze the role before classifying it.

2. Distinguish surface keywords from underlying capabilities.

3. Explain what the role likely does in practice, not only what the JD says.

4. Identify the business, operational, technical, customer, regulatory, analytical, or organizational problem the role exists to solve.

5. For each major inference, provide supporting evidence from the JD or supplied research notes.

6. If the JD is vague, state the uncertainty clearly instead of forcing a conclusion.

7. If multiple interpretations are possible, compare them and explain which interpretation is more likely.

8. Do not assume domain-specific meaning unless the JD supports it.

9. Prefer concrete workflow interpretation over generic statements.

10. Avoid generic phrases such as "strong communication skills" unless you explain what kind of communication the role requires and why.

## Evidence Rules

Use evidence labels when possible.

Examples:

* [JD] for direct job description evidence
* [TITLE] for job title evidence
* [COMPANY] for company or team context
* [RESEARCH] for external or provided research notes
* [INFERENCE] for analyst inference based on multiple signals

Every major conclusion should include at least one evidence reference.

When evidence is weak, say so explicitly.

## Output Format

# Role Dossier Report

## 1. Business / Organizational Context

Explain why this role exists.

What business, operational, technical, customer, regulatory, analytical, or organizational problem does this role help solve?

Discuss the role's likely place within the company or team.

Include supporting evidence.

## 2. Position Function

Identify the role's primary function and secondary functions.

Possible function types may include, but are not limited to:

* Operations
* Analytics
* Data
* Engineering
* Product
* Design
* Sales
* Marketing
* Customer Success
* Support
* Finance
* Risk / Compliance
* Research
* Strategy
* Program / Project Management
* People / HR
* Legal / Policy
* Governance
* General Management
* Mixed / Hybrid

Explain why the function classification fits.

If the role is hybrid, describe the function mix.

Include supporting evidence.

## 3. Likely Daily Workflow

Describe what the person in this role likely does day to day.

Cover as many of the following as the JD supports:

* What inputs they work with
* What tools, systems, documents, customers, data, products, or processes they interact with
* What analysis, execution, coordination, or decision-making they perform
* Who they communicate with
* What outputs they produce
* What problems or escalations they handle
* What success probably looks like in the role

Do not invent specifics. Mark uncertain points as inference.

## 4. Underlying Capability Demands

Translate JD keywords into real capabilities.

For each important JD phrase or requirement:

* Quote or summarize the surface JD phrase
* Explain the underlying capability it implies
* Explain why that capability matters in this role
* Classify the capability as core, supporting, or nice-to-have
* Include evidence

Examples of the expected reasoning style:

* "SQL" may imply data extraction, data quality checks, recurring reporting, analytical ownership, or dashboard maintenance depending on context.
* "Stakeholder management" may imply requirement clarification, escalation handling, cross-functional negotiation, or executive communication.
* "Automation" may imply repeatable workflows, error reduction, process control, or operational scalability.
* "Customer support" may imply issue diagnosis, empathy, product feedback loops, and retention risk detection.
* "Project management" may imply dependency tracking, prioritization, execution governance, and tradeoff communication.

Do not stop at listing skills. Explain the actual work behavior behind them.

## 5. Role Archetype / Family Classification

Classify the role into one or more broad role archetypes.

If a taxonomy is provided, use that taxonomy.

If no taxonomy is provided, define the most natural role archetype based on the JD.

For each classification, include:

* Primary role family
* Secondary role families, if any
* Approximate function mix, if useful
* Reasoning
* Supporting evidence
* Uncertainty

Example format:

Primary family: Data / Analytics Operations
Secondary family: Customer Success / Business Operations
Approximate mix: 70% analytics workflow, 20% stakeholder coordination, 10% process improvement

## 6. Evidence and Uncertainty Review

List the strongest pieces of evidence supporting the analysis.

Then list the main uncertainties.

For each uncertainty, explain:

* What is unclear
* Why it matters
* What additional information would resolve it

## 7. Analyst Summary

Conclude with a concise interpretation of the role.

Answer:

* What is this role really about?
* What type of person would likely succeed in it?
* What makes this role different from similar-looking roles?
* Which capabilities appear most important?

Do not discuss any specific candidate.
Do not recommend resume changes.
"""

_LAYER1_USER_TEMPLATE = """\
Job Title: {title}
Company: {company}
Location: {location}
Source URL: {source_url}

=== ROLE TAXONOMY (use these labels in Section 5 classification) ===
{taxonomy_labels}
{research_section}
=== JOB DESCRIPTION ===
{jd_text}
"""

_RESEARCH_SECTION_WRAPPER = """\
=== COMPANY / TEAM RESEARCH NOTES ===
(Use [RESEARCH] label when citing information from this section. \
Treat these notes as supplementary context — the JD remains the primary source of truth.)
{research_notes}
"""

# ---------------------------------------------------------------------------
# Layer 2: Structured Role Dossier Schema Filler
# ---------------------------------------------------------------------------

_LAYER2_SYSTEM_PROMPT = """\
You are a structured data extractor. A narrative Role Dossier Report has already been written (Layer 1 analysis).
Your task is to canonicalize that report into a JSON schema.

Rules:
1. Use the Layer 1 report as your primary source. Extract structured data FROM the report.
2. Do not re-analyze the job description independently. The report is your input.
3. If the report is ambiguous on a field, consult the raw JD excerpt only to resolve ambiguity — do not re-reason.
4. For evidence fields: copy exact phrases or sentences from the report or JD. Do not paraphrase.
5. For confidence fields: "high" = strongly supported by multiple evidence points; "medium" = inferred from limited signals; "low" = uncertain.
6. For primary_workstream: use ONLY the exact label string from the taxonomy list provided. Do not invent new labels. Use "unknown" if no label fits.
7. For underlying_skill_demands: include the most important capabilities only (up to 8). Quality over quantity.
8. Output valid JSON only. No markdown code fences, no commentary outside the JSON object.
"""

_LAYER2_USER_TEMPLATE = """\
=== WORKSTREAM TAXONOMY LABELS (use exact strings for workstream fields) ===
{taxonomy_labels}

=== LAYER 1 ROLE DOSSIER REPORT ===
{report_md}

=== ORIGINAL JOB DESCRIPTION EXCERPT (reference only — use to resolve ambiguity, not to re-reason) ===
{jd_excerpt}

=== OUTPUT JSON SCHEMA TO FILL ===
{{
  "business_context": {{
    "summary": "one to three sentence summary of the role's organizational purpose",
    "problem_solved": "the specific business, operational, or technical problem this role helps solve",
    "evidence": ["exact phrase or sentence from report/JD supporting this context"],
    "confidence": "high | medium | low"
  }},
  "position_function": {{
    "primary_function": "primary function label (from the list in Section 2 of the report)",
    "secondary_functions": ["secondary function label"],
    "function_mix_description": "brief description of function breakdown if hybrid, else empty string",
    "reason": "why this function classification fits",
    "evidence": ["supporting evidence phrase"],
    "confidence": "high | medium | low"
  }},
  "daily_workflow": {{
    "likely_inputs": ["data, documents, systems, processes, customers the role works with"],
    "likely_analyses": ["analysis, execution, coordination, decisions the role performs"],
    "likely_outputs": ["reports, decisions, code, models, documents, recommendations produced"],
    "likely_stakeholders": ["who the role works with or communicates to"],
    "evidence": ["supporting evidence phrase"]
  }},
  "underlying_skill_demands": [
    {{
      "jd_phrase": "exact or closely summarized phrase from JD",
      "underlying_capability": "what this actually requires the person to do in practice",
      "importance": "core | supporting | nice_to_have",
      "evidence": ["supporting evidence phrase from report or JD"],
      "confidence": "high | medium | low"
    }}
  ],
  "primary_workstream": "exact label from taxonomy, or unknown",
  "secondary_workstreams": ["exact label from taxonomy"],
  "workstream_evidence": ["phrase or sentence from report supporting workstream classification"],
  "workstream_confidence": "high | medium | low",
  "uncertainty_notes": [
    {{
      "issue": "what is unclear in the JD or report",
      "impact": "why this uncertainty matters for understanding the role"
    }}
  ],
  "analyst_notes": "concise analyst summary: what the role is really about, who would succeed, what makes it different from similar-looking roles"
}}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_role(
    jd_text: str,
    job_record: dict[str, Any],
    taxonomy: list[dict[str, Any]],
    llm_client,
    research_notes: str = "",
) -> tuple[str, dict[str, Any]]:
    """
    Run two-layer role analysis.

    Args:
        jd_text:        Raw job description text.
        job_record:     Dict from jobs_structured.json (title, company, location, etc.).
        taxonomy:       List of workstream dicts from workstream_taxonomy.yaml.
        llm_client:     LLM client instance.
        research_notes: Optional pre-research markdown (company background, team context).
                        When provided, included in the Layer 1 prompt under a clearly
                        labelled section; agent cites it with [RESEARCH] evidence labels.
                        When empty, the Layer 1 prompt is identical to the no-research path.

    Returns:
        (report_md, dossier_dict)
        report_md    — Layer 1 narrative markdown report (English)
        dossier_dict — Layer 2 structured dossier (matches role_dossier.schema.json)

    Raises:
        RuntimeError if LLM client is None.
        ValueError if Layer 2 JSON cannot be parsed after retries.
    """
    if llm_client is None:
        raise RuntimeError("LLM client is required for role analysis.")

    taxonomy_labels = _format_taxonomy_labels(taxonomy)

    report_md = _generate_role_report(
        jd_text, job_record, taxonomy_labels, llm_client, research_notes
    )
    dossier = _fill_dossier_schema(jd_text, report_md, taxonomy_labels, llm_client)

    return report_md, dossier


# ---------------------------------------------------------------------------
# Layer 1 implementation
# ---------------------------------------------------------------------------

def _format_taxonomy_labels(taxonomy: list[dict[str, Any]]) -> str:
    if not taxonomy:
        return "(no taxonomy provided)"
    return "\n".join(f"- {ws['label']}" for ws in taxonomy)


def _generate_role_report(
    jd_text: str,
    job_record: dict[str, Any],
    taxonomy_labels: str,
    llm_client,
    research_notes: str = "",
) -> str:
    research_section = (
        _RESEARCH_SECTION_WRAPPER.format(research_notes=research_notes.strip())
        if research_notes.strip()
        else ""
    )

    user_msg = _LAYER1_USER_TEMPLATE.format(
        title=job_record.get("title", "Unknown"),
        company=job_record.get("company", "Unknown"),
        location=job_record.get("location", ""),
        source_url=job_record.get("source_url", ""),
        taxonomy_labels=taxonomy_labels,
        research_section=research_section,
        jd_text=jd_text[:7000],
    )

    for attempt in range(3):
        try:
            report = llm_client.call(
                system=_LAYER1_SYSTEM_PROMPT,
                user=user_msg,
                max_tokens=3500,
            ).strip()
            if report:
                return report
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"Layer 1 LLM call failed after 3 attempts: {e}") from e

    raise RuntimeError("Layer 1 report generation failed: empty response after retries.")


# ---------------------------------------------------------------------------
# Layer 2 implementation
# ---------------------------------------------------------------------------

def _fill_dossier_schema(
    jd_text: str,
    report_md: str,
    taxonomy_labels: str,
    llm_client,
) -> dict[str, Any]:
    user_msg = _LAYER2_USER_TEMPLATE.format(
        taxonomy_labels=taxonomy_labels,
        report_md=report_md[:5000],
        jd_excerpt=jd_text[:2500],
    )

    for attempt in range(3):
        try:
            raw = llm_client.call(
                system=_LAYER2_SYSTEM_PROMPT,
                user=user_msg,
                max_tokens=2500,
            ).strip()

            # Strip markdown code fences if present
            if "```" in raw:
                parts = raw.split("```")
                # Take the content inside the first code block
                raw = parts[1].lstrip("json").strip() if len(parts) >= 3 else raw

            dossier = json.loads(raw)
            return _normalize_dossier(dossier)

        except json.JSONDecodeError as e:
            if attempt == 2:
                raise ValueError(
                    f"Layer 2 JSON parse failed after 3 attempts: {e}\nRaw output: {raw[:500]}"
                ) from e
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"Layer 2 LLM call failed after 3 attempts: {e}") from e

    raise RuntimeError("Layer 2 schema filling failed.")


def _normalize_dossier(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure required fields exist with sensible defaults."""
    # business_context
    bc = data.get("business_context")
    if not isinstance(bc, dict):
        data["business_context"] = {
            "summary": "",
            "problem_solved": "",
            "evidence": [],
            "confidence": "low",
        }
    else:
        bc.setdefault("summary", "")
        bc.setdefault("problem_solved", "")
        bc.setdefault("evidence", [])
        bc.setdefault("confidence", "low")

    # position_function
    pf = data.get("position_function")
    if not isinstance(pf, dict):
        data["position_function"] = {
            "primary_function": "unknown",
            "secondary_functions": [],
            "function_mix_description": "",
            "reason": "",
            "evidence": [],
            "confidence": "low",
        }
    else:
        pf.setdefault("primary_function", "unknown")
        pf.setdefault("secondary_functions", [])
        pf.setdefault("function_mix_description", "")
        pf.setdefault("reason", "")
        pf.setdefault("evidence", [])
        pf.setdefault("confidence", "low")

    # daily_workflow
    dw = data.get("daily_workflow")
    if not isinstance(dw, dict):
        data["daily_workflow"] = {
            "likely_inputs": [],
            "likely_analyses": [],
            "likely_outputs": [],
            "likely_stakeholders": [],
            "evidence": [],
        }
    else:
        for key in ("likely_inputs", "likely_analyses", "likely_outputs", "likely_stakeholders", "evidence"):
            if not isinstance(dw.get(key), list):
                dw[key] = []

    # underlying_skill_demands
    usd = data.get("underlying_skill_demands")
    if not isinstance(usd, list):
        data["underlying_skill_demands"] = []
    else:
        cleaned = []
        for item in usd:
            if not isinstance(item, dict):
                continue
            item.setdefault("jd_phrase", "")
            item.setdefault("underlying_capability", "")
            item.setdefault("importance", "supporting")
            item.setdefault("evidence", [])
            item.setdefault("confidence", "medium")
            cleaned.append(item)
        data["underlying_skill_demands"] = cleaned

    # workstream fields
    data.setdefault("primary_workstream", "unknown")
    if not isinstance(data.get("secondary_workstreams"), list):
        data["secondary_workstreams"] = []
    if not isinstance(data.get("workstream_evidence"), list):
        data["workstream_evidence"] = []
    data.setdefault("workstream_confidence", "low")

    # uncertainty_notes
    un = data.get("uncertainty_notes")
    if not isinstance(un, list):
        data["uncertainty_notes"] = []
    else:
        cleaned_un = []
        for item in un:
            if isinstance(item, dict):
                item.setdefault("issue", "")
                item.setdefault("impact", "")
                cleaned_un.append(item)
        data["uncertainty_notes"] = cleaned_un

    # analyst_notes
    data.setdefault("analyst_notes", "")

    return data
