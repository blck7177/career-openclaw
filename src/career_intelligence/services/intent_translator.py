"""
Intent Translator — convert a candidate profile + user instruction into a
structured DiscoveryIntent that the career-search-agent can execute.

The translator is a deterministic service wrapper around a single LLM call.
It does NOT search the web, invent jobs, or make final career recommendations.
Its only job is to produce an auditable, schema-valid DiscoveryIntent that
specifies what to search and how to allocate the query budget.

Public API
----------
    from career_intelligence.services.intent_translator import translate

    intent = translate(
        profile=profile_dict,
        user_instruction="多找中型银行、保险公司，经验3年以下",
        catalog_context={...},
        strategy_context={...},
        workspace_root=Path(".../data/workspaces/dev_default"),
        repo_root=Path(".../career-openclaw"),
        requested_mode="auto",
        search_source="instruction_plus_profile",  # "instruction_only" | "profile_only" | "instruction_plus_profile"
        session_root=Path(".../runs/2026-06-16_..."),  # optional; enables artifact persist
    )

Artifact layout (when session_root is provided)
-----------------------------------------------
    <session_root>/
        translator_input.json   — full input envelope (for debugging)
        discovery_intent.json   — validated DiscoveryIntent output

Environment variables
---------------------
    INTENT_TRANSLATOR_VERSION   Stamp written into translator_notes.translator_version
                                (default: "1.0.0")
    LLM_MODEL, OPENAI_API_KEY, ANTHROPIC_API_KEY  (from llm_client)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import jsonschema

from career_intelligence.llm_client import make_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "discovery_intent.schema.json"
_TRANSLATOR_VERSION = "1.0.0"

# Prompt version — bump when the 4-block prompt changes semantically so that
# cached intents are not silently reused with an outdated translator.
_PROMPT_VERSION = "2.0.0"


# ---------------------------------------------------------------------------
# Prompt (4-block structure)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the Career Discovery Intent Translator.

Your task is to compile the provided candidate_profile, user_instruction, \
catalog_context, strategy_context, and workstream_taxonomy \
into one structured DiscoveryIntent object.

You do not search the web.
You do not invent job postings, companies, URLs, or live market facts.
You do not make final career recommendations.
You only produce an executable search intent contract for a downstream job discovery agent.

--- NO SILENT DEFAULTS ---
Never fabricate or assume location, seniority, years cap, remote policy, or company type \
when they are not present in the allowed input sources (see search_source below).
If a constraint is absent from the allowed sources, omit it entirely or set it to null. \
Do NOT use any product defaults. Do NOT invent "New York" or any city. \
Do NOT invent "allow_if_finance_relevant" or any remote policy. \
Missing information belongs in translator_notes.missing_information, not in constraints.

--- SEARCH SOURCE RULES ---
The search_source field tells you which inputs you are allowed to read for constraints.

instruction_only:
  Read ONLY user_instruction and explicit search parameters (location, seniority, \
remote policy, exclusions, years cap, workstreams).
  Ignore candidate_profile entirely for hard constraints, location, seniority, \
and target roles. You may still use profile background to choose relevant query seeds, \
but do not surface profile location, target_roles, or seniority as constraints.

profile_only:
  Read ONLY candidate_profile for search lanes, role targeting, and any constraints \
derivable from the profile.
  Ignore user_instruction for hard constraints (treat it as an optional hint for \
query style only).

instruction_plus_profile:
  user_instruction sets hard constraints. profile context enriches lane hypotheses \
and query seeds.
  Hard rule: any constraint stated in user_instruction overrides profile data. \
If user_instruction says "remote only", the remote_policy must be "remote_only" \
even if the profile lists a city.

--- DECISION PRIORITY ---
1. Explicit user constraints from user_instruction (if search_source allows).
2. Profile-derived constraints (only if search_source is profile_only or \
instruction_plus_profile and the user did not contradict them).
3. Strategy context may improve source selection and query priority, \
but must not introduce location, seniority, or company-type constraints.
4. Anything absent from allowed sources → omit or record in missing_information.

--- MODE SELECTION ---
- directed_discovery: user gives concrete target role types, industries, company types, \
location, seniority, experience range, or exclusions.
- profile_based_exploration: user is unsure, asks what roles may fit, \
or search_source is profile_only.
- gap_fill_discovery: no strong user direction and strategy_context has meaningful \
coverage gaps or recommended next searches.
- If requested_mode is not "auto", respect it unless impossible.

--- LANE GENERATION ---
- For directed_discovery: one main lane, optional expansion lanes only if they \
preserve user constraints.
- For profile_based_exploration: 3 to 5 lanes derived from profile evidence.
- For gap_fill_discovery: lanes around weak or missing coverage areas.
- Every lane must include profile evidence, user signal, or strategy signal.
- Do not create lanes only because they sound popular.
- Translate work evidence into adjacent workstreams; do not just mirror current title.

--- CONSTRAINT HANDLING ---
- Preserve explicit max years of experience, excluded role types, location limits, \
and company/industry exclusions from allowed sources.
- Copy global hard constraints into lane-level inherited_hard_constraints.
- Distinguish hard_constraints, soft_preferences, and negative_preferences.
- If a constraint is ambiguous, record it in assumptions.
- Every item in hard_constraints MUST be a JSON object with two fields:
  {"value": "<constraint text>", "source": "<provenance>"}
  where source is exactly one of: "user_explicit", "profile_derived", "system_strategy".
  user_explicit: the user stated it directly in the instruction or search_params.
  profile_derived: inferred from the candidate profile \
(only valid when search_source is profile_only or instruction_plus_profile).
  system_strategy: from strategy_context — MUST NOT be used as a hard constraint; \
use source_strategy instead.
  Do NOT emit plain strings in hard_constraints. Each entry must have value and source.

--- PRIVACY ---
- Do not include personal names, private employer-sensitive details, compensation, \
visa status, or private profile text in query_seeds.
- Query seeds must be general job-market search phrases.

Output:
Return only the structured DiscoveryIntent object matching the supplied JSON schema.
Do not include markdown, comments, prose, or chain-of-thought.
Use assumptions, evidence_from_profile, and risk_of_false_positive fields for auditability.\
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_schema() -> dict[str, Any]:
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_workstream_taxonomy(repo_root: Path) -> list[dict[str, Any]]:
    """Load workstream taxonomy as a list of {id, label, keywords_pattern} dicts."""
    taxonomy_path = repo_root / "configs" / "workstream_taxonomy.yaml"
    if not taxonomy_path.exists():
        return []
    try:
        import yaml  # type: ignore
        raw = yaml.safe_load(taxonomy_path.read_text(encoding="utf-8")) or {}
        workstreams = raw.get("workstreams") or {}
        result = []
        for ws_id, ws_data in workstreams.items():
            if isinstance(ws_data, dict):
                result.append({
                    "id": ws_id,
                    "label": ws_data.get("label", ws_id),
                    "keywords_pattern": ws_data.get("keywords_pattern", []),
                })
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load workstream taxonomy: %s", exc)
        return []


def _format_profile_for_prompt(profile: dict[str, Any]) -> str:
    """Render candidate profile as structured text for the LLM prompt."""
    lines = [
        f"years_experience: {profile.get('years_experience', 'unknown')}",
        f"current_background: {profile.get('current_background', '')}",
        f"domain_experience: {', '.join(profile.get('domain_experience', []))}",
        f"technical_skills: {', '.join(profile.get('technical_skills', []))}",
        f"analytical_methods: {', '.join(profile.get('analytical_methods', []))}",
        f"finance_domains: {', '.join(profile.get('finance_domains', []))}",
        f"tools: {', '.join(profile.get('tools', []))}",
    ]
    target_workstreams = profile.get("target_workstreams", [])
    if target_workstreams:
        lines.append(f"target_workstreams: {', '.join(target_workstreams)}")
    target_roles = profile.get("target_roles", [])
    if target_roles:
        lines.append(f"target_roles: {', '.join(target_roles)}")
    constraints = profile.get("constraints", "")
    if constraints:
        lines.append(f"constraints: {constraints}")
    projects = profile.get("representative_projects", [])
    if projects:
        lines.append("representative_projects:")
        for i, proj in enumerate(projects, 1):
            title = proj.get("title", f"Project {i}")
            desc = proj.get("description", "")
            skills = ", ".join(proj.get("skills_used", []))
            impact = proj.get("quantified_impact", "")
            lines.append(f"  {i}. {title}: {desc}")
            if skills:
                lines.append(f"     skills_used: {skills}")
            if impact:
                lines.append(f"     impact: {impact}")
    return "\n".join(lines)


def build_input_envelope(
    profile: dict[str, Any],
    user_instruction: str,
    catalog_context: dict[str, Any],
    strategy_context: dict[str, Any],
    workstream_taxonomy: list[dict[str, Any]],
    requested_mode: str,
    search_source: str = "instruction_plus_profile",
) -> dict[str, Any]:
    """
    Assemble all translator inputs into a structured envelope.

    This object is persisted as translator_input.json so that any downstream
    debug session can exactly reproduce the LLM call inputs.

    search_source controls which inputs the LLM is allowed to use for constraints:
      "instruction_only"       — user_instruction only; profile ignored for constraints
      "profile_only"           — profile only; user_instruction treated as style hint
      "instruction_plus_profile" — instruction sets hard constraints, profile enriches lanes
    """
    return {
        "profile": profile,
        "user_instruction": user_instruction,
        "catalog_context": catalog_context,
        "strategy_context": strategy_context,
        "workstream_taxonomy": workstream_taxonomy,
        "requested_mode": requested_mode,
        "search_source": search_source,
    }


def _build_user_message(envelope: dict[str, Any]) -> str:
    """Render the envelope as a structured user message for the LLM."""
    profile = envelope["profile"]
    user_instruction = envelope["user_instruction"]
    catalog_context = envelope.get("catalog_context", {})
    strategy_context = envelope.get("strategy_context", {})
    taxonomy = envelope.get("workstream_taxonomy", [])
    requested_mode = envelope.get("requested_mode", "auto")
    search_source = envelope.get("search_source", "instruction_plus_profile")

    taxonomy_text = "\n".join(
        f"  - {ws['id']}: {ws['label']}"
        for ws in taxonomy
    ) or "  (none loaded)"

    coverage_gaps = strategy_context.get("coverage_gaps", [])
    effective_sources = strategy_context.get("effective_sources", [])
    avoid_sources = strategy_context.get("avoid_sources", [])
    recommended_searches = strategy_context.get("recommended_next_searches", [])

    return f"""\
## search_source
{search_source}

## requested_mode
{requested_mode}

## candidate_profile
{_format_profile_for_prompt(profile)}

## user_instruction
{user_instruction or "(none)"}

## catalog_context
existing_job_count: {catalog_context.get('existing_job_count', 0)}
recent_companies: {', '.join(catalog_context.get('recent_companies', []))}

## strategy_context
coverage_gaps: {', '.join(coverage_gaps) if coverage_gaps else '(none)'}
effective_sources: {', '.join(effective_sources[:5]) if effective_sources else '(none)'}
avoid_sources: {', '.join(avoid_sources[:5]) if avoid_sources else '(none)'}
recommended_next_searches:
{chr(10).join(f'  - {s}' for s in recommended_searches[:5]) if recommended_searches else '  (none)'}

## workstream_taxonomy
{taxonomy_text}

## output_instructions
Return only the DiscoveryIntent JSON object. Match this schema exactly:
{json.dumps(_load_schema(), ensure_ascii=False, indent=2)}\
"""


def call_llm_structured_output(
    envelope: dict[str, Any],
    llm_client: Any,
) -> str:
    """
    Call the LLM with the 4-block system prompt and the assembled user message.

    Returns the raw response string. Callers are responsible for parsing and
    validating the JSON.
    """
    user_message = _build_user_message(envelope)
    raw = llm_client.call(
        system=_SYSTEM_PROMPT,
        user=user_message,
        max_tokens=4096,
    )
    return raw


def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM response text, tolerating stray prose."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find the outermost { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(
        f"Could not extract valid JSON from LLM response (length={len(text)})"
    )


def validate_schema(intent: dict[str, Any]) -> list[str]:
    """
    Validate intent against discovery_intent.schema.json.

    Returns a list of error messages (empty list means valid).
    """
    schema = _load_schema()
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(intent), key=lambda e: list(e.path))
    return [f"{'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]


def repair_once_if_invalid(
    envelope: dict[str, Any],
    raw_response: str,
    errors: list[str],
    llm_client: Any,
) -> dict[str, Any]:
    """
    One repair attempt: send schema errors back to the LLM and ask for a fix.

    Returns the repaired intent dict (caller must re-validate).
    Raises ValueError if the repaired response is also unparseable.
    """
    error_summary = "\n".join(f"  - {e}" for e in errors[:10])
    repair_message = (
        f"Your previous response had schema validation errors:\n{error_summary}\n\n"
        f"Previous response was:\n{raw_response[:2000]}\n\n"
        f"Please fix the errors and return only the corrected DiscoveryIntent JSON object. "
        f"No prose, no markdown, no explanation."
    )
    logger.debug("Intent translator: attempting repair due to %d schema error(s)", len(errors))
    raw_repair = llm_client.call(
        system=_SYSTEM_PROMPT,
        user=repair_message,
        max_tokens=4096,
    )
    return _extract_json(raw_repair)


def normalize_budget_share(intent: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure all search_lanes[].budget_share values sum to 1.0.

    If any lane is missing budget_share, assigns equal shares. If the total
    is not 1.0, rescales proportionally. Mutates intent in place and returns it.
    """
    lanes = intent.get("search_lanes", [])
    if not lanes:
        return intent

    shares = [lane.get("budget_share") for lane in lanes]
    # Fill missing shares with equal portion
    missing_count = sum(1 for s in shares if s is None)
    total_defined = sum(s for s in shares if s is not None) or 0.0

    if missing_count > 0:
        remaining = max(0.0, 1.0 - total_defined)
        fill = remaining / missing_count if missing_count else 0.0
        for lane in lanes:
            if lane.get("budget_share") is None:
                lane["budget_share"] = round(fill, 4)

    # Re-read after fill
    shares = [lane.get("budget_share", 0.0) for lane in lanes]
    total = sum(shares)

    if total > 0 and abs(total - 1.0) > 0.001:
        # Rescale proportionally
        for lane in lanes:
            lane["budget_share"] = round(lane.get("budget_share", 0.0) / total, 4)
        # Fix last lane to ensure exact sum of 1.0
        running = sum(lane["budget_share"] for lane in lanes[:-1])
        lanes[-1]["budget_share"] = round(1.0 - running, 4)

    return intent


def copy_global_constraints_to_lanes(intent: dict[str, Any]) -> dict[str, Any]:
    """
    Propagate global_constraints.hard_constraints into each lane's
    inherited_hard_constraints (flat string list).

    Global hard_constraints are now provenance-tagged objects {value, source}.
    Lane-level inherited_hard_constraints remain plain strings for backward
    compatibility with the search agent that reads them as text directives.
    Mutates intent in place and returns it.
    """
    hard = (intent.get("global_constraints") or {}).get("hard_constraints") or []
    if not hard:
        return intent

    # Extract plain string values from provenance objects (or legacy strings).
    hard_values: list[str] = []
    for item in hard:
        if isinstance(item, dict):
            v = item.get("value")
            if v:
                hard_values.append(str(v))
        elif isinstance(item, str):
            hard_values.append(item)

    if not hard_values:
        return intent

    for lane in intent.get("search_lanes", []):
        existing = lane.get("inherited_hard_constraints") or []
        merged = list(dict.fromkeys([*existing, *hard_values]))
        lane["inherited_hard_constraints"] = merged
    return intent


# Terms the translator must never include in query_seeds — they identify
# individuals or specific employers rather than job-market search phrases.
_PRIVATE_PATTERNS = [
    re.compile(r"\b(Goldman|GS|JPMorgan|JPM|Morgan Stanley|MS|Citi)\b", re.IGNORECASE),
    re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b"),  # two-word proper-noun names
]

# Regex to detect obviously personal or private terms in seeds
_PRIVATE_SEED_PATTERN = re.compile(
    r"(compensation|salary|visa|immigration|H-?1B|OPT|CPT|work\s+permit|SSN|NDA)",
    re.IGNORECASE,
)


def scrub_private_query_terms(intent: dict[str, Any]) -> dict[str, Any]:
    """
    Remove personal names, sensitive employer names, and private detail from
    query_seeds across all lanes. Mutates intent in place and returns it.
    """
    for lane in intent.get("search_lanes", []):
        seeds = lane.get("query_seeds") or []
        scrubbed = []
        for seed in seeds:
            if _PRIVATE_SEED_PATTERN.search(seed):
                logger.debug(
                    "Intent translator: dropped private query seed %r from lane %s",
                    seed, lane.get("lane_id", "?"),
                )
                continue
            scrubbed.append(seed)
        lane["query_seeds"] = scrubbed
    return intent


def persist_artifacts(
    session_root: Path,
    input_envelope: dict[str, Any],
    intent: dict[str, Any],
) -> None:
    """
    Write translator_input.json and discovery_intent.json to the session dir.

    These artifacts allow post-run debugging to distinguish:
    - translator errors   (bad intent output)
    - agent errors        (agent ignored valid intent)
    - pipeline errors     (fetch/provenance failure)
    """
    session_root.mkdir(parents=True, exist_ok=True)

    envelope_path = session_root / "translator_input.json"
    intent_path = session_root / "discovery_intent.json"

    # Omit the full schema from the persisted envelope to keep file size reasonable
    envelope_to_save = {k: v for k, v in input_envelope.items() if k != "output_instructions"}
    envelope_path.write_text(
        json.dumps(envelope_to_save, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    intent_path.write_text(
        json.dumps(intent, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.debug(
        "Intent translator: persisted artifacts → %s, %s", envelope_path, intent_path
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class IntentTranslatorError(Exception):
    """Raised when the translator cannot produce a valid DiscoveryIntent."""


def translate(
    profile: dict[str, Any],
    user_instruction: str,
    catalog_context: dict[str, Any],
    strategy_context: dict[str, Any],
    workspace_root: Path,
    repo_root: Path,
    requested_mode: str = "auto",
    session_root: Path | None = None,
    search_source: str = "instruction_plus_profile",
) -> dict[str, Any]:
    """
    Translate a candidate profile + user instruction into a validated DiscoveryIntent.

    Steps:
      1. build_input_envelope  — assemble all inputs
      2. call_llm_structured_output — LLM call with system prompt
      3. _extract_json          — parse raw response
      4. validate_schema        — check against discovery_intent.schema.json
      5. repair_once_if_invalid — one retry if schema validation fails
      6. normalize_budget_share — ensure lane shares sum to 1.0
      7. copy_global_constraints_to_lanes — propagate hard constraints
      8. scrub_private_query_terms — strip personal/sensitive terms from seeds
      9. persist_artifacts      — write translator_input.json + discovery_intent.json

    Args:
        profile:           Full candidate profile dict from profile_service.
        user_instruction:  Raw user instruction string (may be empty).
        catalog_context:   From agent_service._build_catalog_context().
        strategy_context:  From agent_service._build_strategy_context().
        workspace_root:    Workspace root Path (for context; not directly used here).
        repo_root:         Repo root Path (to load workstream taxonomy).
        requested_mode:    "auto" | "directed_discovery" | "profile_based_exploration"
                           | "gap_fill_discovery". "auto" lets the LLM decide.
        session_root:      If provided, artifacts are persisted to this directory.
        search_source:     "instruction_only" | "profile_only" | "instruction_plus_profile".
                           Controls which inputs the LLM may use for hard constraints.

    Returns:
        Validated DiscoveryIntent dict.

    Raises:
        IntentTranslatorError  — LLM unavailable, JSON parse failure after repair,
                                 or schema still invalid after one repair attempt.
    """
    import os
    translator_version = os.environ.get("INTENT_TRANSLATOR_VERSION", _TRANSLATOR_VERSION)

    # Load workstream taxonomy
    taxonomy = _load_workstream_taxonomy(repo_root)

    # 1. Build input envelope
    envelope = build_input_envelope(
        profile=profile,
        user_instruction=user_instruction,
        catalog_context=catalog_context,
        strategy_context=strategy_context,
        workstream_taxonomy=taxonomy,
        requested_mode=requested_mode,
        search_source=search_source,
    )

    # 2. LLM client
    llm_client = make_client()
    if llm_client is None:
        raise IntentTranslatorError(
            "No LLM API key configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY."
        )

    # 3. Call LLM
    logger.info(
        "Intent translator: calling LLM (mode=%s, profile_id=%s, instruction_len=%d)",
        requested_mode, profile.get("candidate_profile_id", "?"), len(user_instruction),
    )
    try:
        raw_response = call_llm_structured_output(envelope, llm_client)
    except Exception as exc:
        raise IntentTranslatorError(f"LLM call failed: {exc}") from exc

    # 4. Parse JSON
    try:
        intent = _extract_json(raw_response)
    except ValueError as exc:
        raise IntentTranslatorError(f"Could not parse LLM response as JSON: {exc}") from exc

    # 5. Validate schema; repair once if invalid
    errors = validate_schema(intent)
    if errors:
        logger.warning(
            "Intent translator: schema invalid (%d error(s)); attempting repair", len(errors)
        )
        try:
            intent = repair_once_if_invalid(envelope, raw_response, errors, llm_client)
        except ValueError as exc:
            raise IntentTranslatorError(
                f"Repair attempt produced unparseable JSON: {exc}"
            ) from exc
        errors = validate_schema(intent)
        if errors:
            raise IntentTranslatorError(
                f"DiscoveryIntent still invalid after repair ({len(errors)} error(s)): "
                + "; ".join(errors[:5])
            )

    # 6. Post-processing (deterministic, no LLM)
    normalize_budget_share(intent)
    copy_global_constraints_to_lanes(intent)
    scrub_private_query_terms(intent)

    # Stamp translator metadata
    if "translator_notes" in intent:
        intent["translator_notes"]["translator_version"] = translator_version
    else:
        intent["translator_notes"] = {
            "assumptions": [],
            "missing_information": [],
            "translator_version": translator_version,
        }

    # Stamp profile_id for traceability.
    # Treat placeholder values ("unknown", "", "none", "null") as missing so that
    # a real profile id is always stamped even when the LLM emits a placeholder.
    _PLACEHOLDER_PROFILE_IDS = {"", "unknown", "none", "null"}
    current_profile_id = (intent.get("profile_id") or "").strip().lower()
    if current_profile_id in _PLACEHOLDER_PROFILE_IDS and profile.get("candidate_profile_id"):
        intent["profile_id"] = profile["candidate_profile_id"]

    logger.info(
        "Intent translator: produced %s with %d lane(s) for profile %s",
        intent.get("intent_kind", "?"),
        len(intent.get("search_lanes", [])),
        profile.get("candidate_profile_id", "?"),
    )

    # 7. Persist artifacts
    if session_root is not None:
        try:
            persist_artifacts(session_root, envelope, intent)
        except OSError as exc:
            logger.warning("Intent translator: could not persist artifacts: %s", exc)

    return intent
