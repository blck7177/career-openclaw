"""
Research Validator — anti-fabrication gate for research-augmented Job Reports.

A research-agent that never goes online can still write a plausible-looking
research_notes.md from training knowledge. That is exactly the failure mode the
search-side guard prevents (candidate_pool is unwritable when queries_run==0,
see search_session.log_candidates). This module is the research-side equivalent.

Two evidence layers:
  Layer A (primary, strong) — tool_calls parsed from the agent run log by
      agent_gateway. An agent cannot fabricate these: not calling web_fetch
      means no entry exists.
  Layer B (fallback, weak)  — a self-reported fetch ledger written by the agent
      via career_research_session log-fetch. Used only when the run log does not
      expose tool calls. Layer A wins on conflict.

A source in research_sources.json is "verified" only when its URL hash appears
in the real fetch set. The bundle status is failed / partial / passed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .url_utils import url_hash


@dataclass
class SourceVerification:
    url: str
    url_hash: str
    verified: bool
    reason: str = ""


@dataclass
class ResearchValidation:
    status: str  # "passed" | "partial" | "failed"
    source_count: int
    verified_source_count: int
    per_source: list[SourceVerification] = field(default_factory=list)
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def usable(self) -> bool:
        """Whether the worker should feed this research into the report."""
        return self.status in ("passed", "partial")


def _real_fetch_hashes(
    tool_calls: list[dict[str, Any]],
    fetch_ledger: list[dict[str, Any]],
) -> tuple[set[str], int]:
    """
    Build the set of url_hashes that correspond to a *real* web_fetch.

    Layer A (tool_calls) is authoritative. Layer B (ledger) supplements it so a
    run whose log does not expose tool calls can still be validated. Returns
    (hashes, real_fetch_count) where real_fetch_count prefers Layer A.
    """
    hashes: set[str] = set()
    layer_a_count = 0
    for tc in tool_calls:
        if tc.get("tool") == "web_fetch":
            url = (tc.get("url") or "").strip()
            # Only a fetch with a real URL counts as Layer A evidence; a
            # URL-less entry carries no provenance and must not inflate the count.
            if url:
                layer_a_count += 1
                hashes.add(url_hash(url))

    for entry in fetch_ledger:
        url = (entry.get("url") or "").strip()
        h = entry.get("url_hash") or (url_hash(url) if url else "")
        if h:
            hashes.add(h)

    real_fetch_count = layer_a_count if layer_a_count else len(fetch_ledger)
    return hashes, real_fetch_count


def _source_well_formed(source: dict[str, Any]) -> bool:
    """
    Format guard: if the structured source carries the provenance fields, they
    must be non-empty. Prevents generic company-overview padding from counting
    as verified. Absent fields are not penalised (agent may keep them only in
    the markdown notes).
    """
    for key in ("related_jd_signal", "boundary"):
        if key in source and not str(source.get(key) or "").strip():
            return False
    return True


def validate_research_bundle(
    notes_text: str,
    sources: list[dict[str, Any]],
    fetch_ledger: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    *,
    min_verified: int = 1,
) -> ResearchValidation:
    """
    Validate a research bundle against the real fetch set.

    Args:
        notes_text:   research_notes.md contents.
        sources:      parsed research_sources.json (list of source dicts).
        fetch_ledger: Layer B self-reported fetch ledger entries.
        tool_calls:   Layer A tool calls parsed by agent_gateway.
        min_verified: minimum verified sources for a non-failed bundle.

    Returns:
        ResearchValidation with status passed | partial | failed.
    """
    sources = sources or []
    fetched_hashes, real_fetch_count = _real_fetch_hashes(tool_calls, fetch_ledger)

    # Rule 1 — zero real fetch (fabrication guard, mirrors queries_run==0).
    if real_fetch_count == 0 or not fetched_hashes:
        return ResearchValidation(
            status="failed",
            source_count=len(sources),
            verified_source_count=0,
            reason="no real web_fetch detected (tool_calls and fetch ledger both empty)",
        )

    # Rule 2 — notes present but no sources (conclusions without provenance).
    if (notes_text or "").strip() and not sources:
        return ResearchValidation(
            status="failed",
            source_count=0,
            verified_source_count=0,
            reason="research_notes present but research_sources is empty",
        )

    # Rule 3 — per-source verification against the real fetch set.
    per_source: list[SourceVerification] = []
    for src in sources:
        url = (src.get("url") or "").strip()
        if not url:
            per_source.append(SourceVerification("", "", False, "missing url"))
            continue
        h = url_hash(url)
        if h not in fetched_hashes:
            per_source.append(SourceVerification(url, h, False, "url not in real fetch set"))
        elif not _source_well_formed(src):
            per_source.append(SourceVerification(url, h, False, "missing related_jd_signal/boundary"))
        else:
            per_source.append(SourceVerification(url, h, True))

    verified_count = sum(1 for p in per_source if p.verified)
    source_count = len(sources)

    # Rule 4 — aggregate.
    if verified_count == 0:
        return ResearchValidation(
            status="failed",
            source_count=source_count,
            verified_source_count=0,
            per_source=per_source,
            reason="no source URL matches a real web_fetch",
        )
    if verified_count < min_verified:
        return ResearchValidation(
            status="failed",
            source_count=source_count,
            verified_source_count=verified_count,
            per_source=per_source,
            reason=f"verified sources {verified_count} < min_verified {min_verified}",
        )
    if verified_count < source_count:
        return ResearchValidation(
            status="partial",
            source_count=source_count,
            verified_source_count=verified_count,
            per_source=per_source,
            reason=f"{verified_count}/{source_count} sources verified",
        )
    return ResearchValidation(
        status="passed",
        source_count=source_count,
        verified_source_count=verified_count,
        per_source=per_source,
    )
