"""
Workstream Classifier — classifies a job record against the workstream taxonomy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ClassificationResult:
    primary_workstream: str
    secondary_workstreams: list[str]
    classification_confidence: str  # "high" | "medium" | "low"
    classification_evidence: list[str]
    uncertainty_notes: str | None = None


def _load_taxonomy(workspace_root: Path) -> list[dict[str, Any]]:
    taxonomy_path = workspace_root / "configs" / "workstream_taxonomy.yaml"
    with open(taxonomy_path) as f:
        data = yaml.safe_load(f)
    return data.get("workstreams", [])


def _keyword_classify(text: str, taxonomy: list[dict[str, Any]]) -> tuple[str | None, list[str], list[str]]:
    """
    Simple keyword-based pre-classification for speed and transparency.
    Returns (best_id, evidence_list, all_matching_ids).
    """
    text_lower = text.lower()
    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}

    for ws in taxonomy:
        ws_id = ws["id"]
        hits = []
        for kw in ws.get("keywords_pattern", []):
            if kw.lower() in text_lower:
                hits.append(kw)
        if hits:
            scores[ws_id] = len(hits)
            evidence[ws_id] = hits

    if not scores:
        return None, [], []

    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    best_id = sorted_ids[0]
    best_label = next(w["label"] for w in taxonomy if w["id"] == best_id)
    secondary_labels = [
        next(w["label"] for w in taxonomy if w["id"] == sid)
        for sid in sorted_ids[1:3]
        if scores[sid] >= 2
    ]
    return best_label, evidence[best_id], secondary_labels


def classify_workstream(
    jd_text: str,
    extracted_fields: dict[str, Any],
    workspace_root: Path,
    llm_client=None,
) -> ClassificationResult:
    """
    Classify workstream using keyword heuristics + optional LLM confirmation.
    """
    taxonomy = _load_taxonomy(workspace_root)
    combined_text = jd_text + " " + " ".join(
        str(v) for v in extracted_fields.values() if isinstance(v, (str, list))
        for s in ([v] if isinstance(v, str) else v)
    )

    best_label, evidence, secondary = _keyword_classify(combined_text, taxonomy)

    if best_label and len(evidence) >= 3:
        confidence = "high"
    elif best_label and len(evidence) >= 1:
        confidence = "medium"
    else:
        confidence = "low"

    if llm_client and confidence != "high":
        result = _llm_classify(jd_text, taxonomy, llm_client)
        if result:
            return result

    if not best_label:
        return ClassificationResult(
            primary_workstream="unknown",
            secondary_workstreams=[],
            classification_confidence="low",
            classification_evidence=[],
            uncertainty_notes="No taxonomy keywords matched. Manual review required.",
        )

    return ClassificationResult(
        primary_workstream=best_label,
        secondary_workstreams=secondary,
        classification_confidence=confidence,
        classification_evidence=evidence[:5],
        uncertainty_notes="Low confidence — consider manual review." if confidence == "low" else None,
    )


def _llm_classify(jd_text: str, taxonomy: list[dict], client) -> ClassificationResult | None:
    """LLM-assisted classification for ambiguous cases."""
    labels = [ws["label"] for ws in taxonomy]
    labels_str = "\n".join(f"- {l}" for l in labels)

    prompt = (
        f"Classify the following job description into the most relevant workstream.\n\n"
        f"Available workstreams:\n{labels_str}\n\n"
        f"Job Description (excerpt):\n{jd_text[:3000]}\n\n"
        f"Respond in JSON:\n"
        f'{{"primary": "<exact label>", "secondary": ["<label>"], "confidence": "high|medium|low", "evidence": ["<quoted phrase from JD>"], "uncertainty_notes": null}}'
    )

    try:
        import json
        text = client.call(
            system="You are a job classification assistant. Respond in JSON only.",
            user=prompt,
            max_tokens=400,
        ).strip()
        if "```" in text:
            text = text.split("```")[1].lstrip("json").strip()
        data = json.loads(text)
        return ClassificationResult(
            primary_workstream=data.get("primary", "unknown"),
            secondary_workstreams=data.get("secondary", []),
            classification_confidence=data.get("confidence", "medium"),
            classification_evidence=data.get("evidence", []),
            uncertainty_notes=data.get("uncertainty_notes"),
        )
    except Exception:
        return None
