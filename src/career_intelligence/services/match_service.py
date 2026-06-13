"""
MatchService — generate workspace-scoped Candidate Fit Reports.

A Fit Report compares a candidate's manual profile against a Job Intelligence
Report to produce match scores, gap analysis, and resume positioning guidance.

Artifact layout:
    data/workspaces/<workspace_id>/reports/<fit_report_id>/fit_report.md
    data/workspaces/<workspace_id>/reports/<fit_report_id>/structured.json

Cache key: (job_id, job_report_id, candidate_profile_id, profile_hash, FIT_PROMPT_VERSION)
  - profile_hash = md5[:16] of the full candidate profile JSON (includes profile_version)
  - job_report_id is the specific Job Intelligence Report that was used as input

Design:
  - Takes RequestContext because the job record and candidate profile are workspace-scoped.
  - The output is workspace-scoped (candidate data is private).
  - Use force=True to skip the cache and regenerate.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from career_intelligence.app_state.context import RequestContext
from career_intelligence.app_state.metadata_store import MetadataStore
from career_intelligence.app_state.workspace_paths import (
    get_data_root,
    get_workspace_paths,
)
from career_intelligence.llm_client import make_client
from career_intelligence.services.job_service import get_job
from career_intelligence.services.profile_service import get_profile

FIT_PROMPT_VERSION = "0.1.0"

_SYSTEM_PROMPT = """\
You are a senior career advisor specialising in finance and risk roles at investment banks, \
asset managers, and financial institutions. Your task is to analyse how well a candidate's \
experience and skills match a specific role, based on a deep job intelligence report.

Be specific and evidence-based. When citing strong matches, reference the candidate's actual \
projects and skills. When identifying gaps, be concrete about what is missing and why it matters.

Output only valid JSON — no markdown fences, no explanation outside the JSON object.\
"""


def _build_user_prompt(
    job_record: dict[str, Any],
    structured_job_report: dict[str, Any],
    candidate_profile: dict[str, Any],
    fit_report_id: str,
    job_report_id: str,
    workspace_id: str,
    profile_id: str,
) -> str:
    now = datetime.now(timezone.utc).isoformat()

    # Format representative_projects for readability
    projects_text = ""
    for i, proj in enumerate(candidate_profile.get("representative_projects", []), 1):
        title = proj.get("title", f"Project {i}")
        desc = proj.get("description", "")
        skills = ", ".join(proj.get("skills_used", []))
        impact = proj.get("quantified_impact", "")
        projects_text += f"\n  {i}. {title}\n     Description: {desc}\n     Skills used: {skills}"
        if impact:
            projects_text += f"\n     Impact: {impact}"

    return f"""\
## Role Overview
Title: {job_record.get('title', 'Unknown')}
Company: {job_record.get('company', 'Unknown')}
Workstream: {job_record.get('primary_workstream', 'Unknown')}
Location: {job_record.get('location', 'Unknown')}

## Job Intelligence Report (structured analysis)
{json.dumps(structured_job_report, ensure_ascii=False, indent=2)}

## Candidate Profile
Years of experience: {candidate_profile.get('years_experience', 'Unknown')}
Background: {candidate_profile.get('current_background', '')}
Domain experience: {', '.join(candidate_profile.get('domain_experience', []))}
Technical skills: {', '.join(candidate_profile.get('technical_skills', []))}
Analytical methods: {', '.join(candidate_profile.get('analytical_methods', []))}
Finance domains: {', '.join(candidate_profile.get('finance_domains', []))}
Tools: {', '.join(candidate_profile.get('tools', []))}

Key projects:{projects_text}

## Output Requirements

Return a single JSON object with these exact fields:

{{
  "fit_report_id": "{fit_report_id}",
  "workspace_id": "{workspace_id}",
  "job_id": "{job_record.get('job_id', '')}",
  "job_report_id": "{job_report_id}",
  "candidate_profile_id": "{profile_id}",
  "analyzed_at": "{now}",
  "prompt_version": "{FIT_PROMPT_VERSION}",

  "overall_match_score": <integer 0-100, alignment signal — not a hiring prediction>,
  "match_summary": "<2-3 sentences summarising fit and key gaps>",

  "strong_matches": [
    {{"demand": "<role requirement>", "evidence": "<specific evidence from candidate profile>"}}
  ],

  "partial_matches": [
    {{"demand": "<role requirement>", "gap_description": "<what the candidate has vs what is needed>"}}
  ],

  "gaps": [
    {{
      "demand": "<role requirement>",
      "gap_description": "<what is missing>",
      "severity": "<blocking|significant|minor>"
    }}
  ],

  "risk_flags": [
    "<string — e.g. title mismatch, missing licence, seniority bar>"
  ],

  "interview_talking_points": [
    "<3-4 concrete angles the candidate should prepare to discuss>"
  ],

  "resume_rewrite_strategy": {{
    "positioning": "<how to frame the candidate's overall story for this specific role>",
    "keywords_to_add": ["<JD term missing from candidate's visible skill set>"],
    "bullets_to_reframe": [],
    "evidence_to_surface": ["<project or experience that should be made more prominent>"]
  }},

  "recommended_next_action": "<one of: apply now | revise resume first | get more context | skip>"
}}

Rules:
- strong_matches must cite specific project names or skills from the candidate profile.
- gaps severity: 'blocking' = role cannot proceed without it; 'significant' = real weakness; 'minor' = nice-to-have.
- bullets_to_reframe must always be an empty array [] — no resume bullets are available yet.
- overall_match_score: 80+ means strong alignment; 60-79 good with addressable gaps; below 60 significant gaps.\
"""


def _extract_json(text: str) -> dict[str, Any]:
    """
    Extract a JSON object from LLM response text.

    Handles responses that include stray text before/after the JSON object.
    """
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not extract valid JSON from LLM response (length={len(text)})")


def _build_narrative(structured: dict[str, Any]) -> str:
    """Build a lightweight markdown narrative from the structured fit report."""
    score = structured.get("overall_match_score", "?")
    summary = structured.get("match_summary", "")
    action = structured.get("recommended_next_action", "")

    lines = [
        f"# Candidate Fit Report",
        f"",
        f"**Match Score:** {score}/100  |  **Recommended action:** {action}",
        f"",
        f"## Summary",
        summary,
        "",
    ]

    strong = structured.get("strong_matches", [])
    if strong:
        lines += ["## Strong Matches", ""]
        for m in strong:
            lines.append(f"- **{m.get('demand', '')}** — {m.get('evidence', '')}")
        lines.append("")

    partial = structured.get("partial_matches", [])
    if partial:
        lines += ["## Partial Matches", ""]
        for m in partial:
            lines.append(f"- **{m.get('demand', '')}** — {m.get('gap_description', '')}")
        lines.append("")

    gaps = structured.get("gaps", [])
    if gaps:
        lines += ["## Gaps", ""]
        for g in gaps:
            sev = g.get("severity", "")
            lines.append(f"- [{sev.upper()}] **{g.get('demand', '')}** — {g.get('gap_description', '')}")
        lines.append("")

    flags = structured.get("risk_flags", [])
    if flags:
        lines += ["## Risk Flags", ""]
        for f in flags:
            lines.append(f"- ⚠ {f}")
        lines.append("")

    points = structured.get("interview_talking_points", [])
    if points:
        lines += ["## Interview Talking Points", ""]
        for i, p in enumerate(points, 1):
            lines.append(f"{i}. {p}")
        lines.append("")

    strategy = structured.get("resume_rewrite_strategy", {})
    if strategy:
        lines += ["## Resume Positioning Guidance", ""]
        positioning = strategy.get("positioning", "")
        if positioning:
            lines += [f"**Positioning:** {positioning}", ""]
        keywords = strategy.get("keywords_to_add", [])
        if keywords:
            lines += ["**Keywords to add:** " + ", ".join(f"`{k}`" for k in keywords), ""]
        evidence = strategy.get("evidence_to_surface", [])
        if evidence:
            lines += ["**Evidence to surface:**", ""]
            for e in evidence:
                lines.append(f"- {e}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_fit_report(
    ctx: RequestContext,
    job_id: str,
    profile_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """
    Generate (or return cached) a workspace-scoped Candidate Fit Report.

    Args:
        ctx:        RequestContext — used to locate the workspace job record
                    and candidate profile.
        job_id:     The job to analyse.
        profile_id: The candidate profile to compare against the job.
        force:      If True, skip cache and regenerate.

    Returns:
        {
          "fit_report_id": str,
          "status": "created" | "cache_hit",
          "report_path": str,
          "structured_path": str,
        }

    Raises:
        ValueError  — job/profile/job_report not found.
        RuntimeError — LLM client unavailable or response unparseable.
    """
    data_root = get_data_root()
    store = MetadataStore.from_data_root(data_root)
    store.init_schema()

    # 1. Load job record from the shared catalog
    job_record = get_job(ctx, job_id)
    if job_record is None:
        raise ValueError(f"Job not found in catalog: {job_id}")

    # 2. Load candidate profile
    candidate_profile = get_profile(ctx, profile_id)
    if candidate_profile is None:
        raise ValueError(f"Candidate profile not found: {profile_id}")

    # 3. Verify a Job Intelligence Report exists for this job
    job_report_row = store.get_latest_active_job_report(job_id)
    if job_report_row is None:
        raise ValueError(
            f"No Job Intelligence Report found for job {job_id}. "
            "Run 'Analyze Role' first before generating a Fit Report."
        )

    # 4. Load the structured job report (this is the LLM analysis input)
    structured_job_report: dict[str, Any] = {}
    structured_path_str = job_report_row.get("structured_path") or ""
    if structured_path_str:
        sp = Path(structured_path_str)
        if sp.exists():
            try:
                structured_job_report = json.loads(sp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass

    # 5. Compute profile_hash (includes profile_version → cache invalidates on version bump)
    profile_hash = hashlib.md5(
        json.dumps(candidate_profile, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]

    # 6. Cache lookup
    if not force:
        cached = store.get_active_fit_report(
            job_id=job_id,
            job_report_id=job_report_row["job_report_id"],
            candidate_profile_id=profile_id,
            profile_hash=profile_hash,
            prompt_version=FIT_PROMPT_VERSION,
        )
        if cached:
            return {
                "fit_report_id": cached["fit_report_id"],
                "status": "cache_hit",
                "report_path": cached.get("report_path", ""),
                "structured_path": cached.get("structured_path", ""),
            }

    # 7. LLM client
    llm_client = make_client()
    if llm_client is None:
        raise RuntimeError(
            "No LLM API key configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY."
        )

    # 8. Pre-allocate ID so filesystem path and DB row stay in sync
    fit_report_id = "fit_" + uuid.uuid4().hex[:8]

    # 9. Call LLM
    user_prompt = _build_user_prompt(
        job_record=job_record,
        structured_job_report=structured_job_report,
        candidate_profile=candidate_profile,
        fit_report_id=fit_report_id,
        job_report_id=job_report_row["job_report_id"],
        workspace_id=ctx.workspace_id,
        profile_id=profile_id,
    )
    raw_response = llm_client.call(
        system=_SYSTEM_PROMPT,
        user=user_prompt,
        max_tokens=4096,
    )

    try:
        fit_structured = _extract_json(raw_response)
    except ValueError as exc:
        raise RuntimeError(f"Failed to parse LLM fit report response: {exc}") from exc

    # 10. Build narrative markdown
    fit_narrative = _build_narrative(fit_structured)

    # 11. Write artifacts
    ws_paths = get_workspace_paths(ctx.workspace_id, data_root)
    artifact_dir = ws_paths.fit_report_dir(fit_report_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    report_path = ws_paths.fit_report_narrative(fit_report_id)
    structured_out_path = ws_paths.fit_report_structured(fit_report_id)
    report_path.write_text(fit_narrative, encoding="utf-8")
    structured_out_path.write_text(
        json.dumps(fit_structured, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 12. Insert into MetadataStore
    store.insert_fit_report(
        workspace_id=ctx.workspace_id,
        job_id=job_id,
        job_report_id=job_report_row["job_report_id"],
        candidate_profile_id=profile_id,
        profile_hash=profile_hash,
        prompt_version=FIT_PROMPT_VERSION,
        report_path=str(report_path),
        structured_path=str(structured_out_path),
        fit_report_id=fit_report_id,
    )

    return {
        "fit_report_id": fit_report_id,
        "status": "created",
        "report_path": str(report_path),
        "structured_path": str(structured_out_path),
    }
