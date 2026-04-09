from __future__ import annotations
import json
import logging
import re
from typing import Optional

from openai import OpenAI

from config import settings
from utils.models import (
    AmbiguityFlag, AmbiguityReason, AuditResult, AuditState,
    ExtractedEntity, EntityType, SourceSpan,
)
from kb.knowledge_base import lookup_rxnorm, is_ambiguous

log = logging.getLogger(__name__)

NEGATION_PATTERNS = [
    r"\bno\b.{0,30}",
    r"\bnot\b.{0,30}",
    r"\bwithout\b.{0,30}",
    r"\bdenies\b.{0,30}",
    r"\ballergic to\b.{0,30}",
    r"\bcontraindicated\b.{0,30}",
    r"\bdo not (give|administer|use)\b.{0,30}",
    r"\bshould not (receive|take|be given)\b.{0,30}",
    r"\bavoid\b.{0,30}",
    r"\bdiscontinue[d]?\b.{0,30}",
]

_EXTRACTION_SYSTEM = """\
You are a clinical NLP extraction engine operating in a safety-critical medical system.
Extract ALL medications, allergies, medical conditions, dosages, routes, and frequencies.

NEGATION DETECTION IS MANDATORY:
- "Patient should NOT receive warfarin" -> warfarin with is_negated=true
- "No known drug allergies" -> no allergy entities
- "Discontinue aspirin" -> aspirin with is_negated=true, entity_type="drug"
- "Allergic to penicillin" -> penicillin with entity_type="allergy"

Return ONLY valid JSON. No markdown. No explanation.

Schema:
{
  "entities": [
    {
      "entity_type": "drug|allergy|condition|dosage|route",
      "raw_text": "exact text from note",
      "normalized_name": "canonical medical name",
      "confidence": 0.0-1.0,
      "start_char": integer,
      "end_char": integer,
      "dosage": "e.g. 10mg or null",
      "route": "e.g. oral or null",
      "frequency": "e.g. twice daily or null",
      "is_negated": boolean
    }
  ]
}

Confidence scoring rules:
- Clear drug name with standard spelling: 0.97-0.99
- Abbreviation with single unambiguous mapping: 0.92-0.96
- Abbreviation with multiple possible mappings: 0.60-0.85
- Unclear or misspelled term: 0.50-0.75
- Dosage extracted from clear notation: 0.98-1.0
"""


def _detect_negation_context(text: str, start: int, end: int) -> bool:
    window_start = max(0, start - 60)
    pre_context = text[window_start:start].lower()
    for pattern in NEGATION_PATTERNS:
        if re.search(pattern, pre_context):
            return True
    post_context = text[end:end + 40].lower()
    if re.search(r"^\s*(should not|must not|do not)", post_context):
        return True
    return False


def _find_char_offset(text: str, raw_text: str, hint_start: int = 0) -> tuple[int, int]:
    idx = text.lower().find(raw_text.lower(), hint_start)
    if idx == -1:
        idx = text.lower().find(raw_text.lower())
    if idx == -1:
        return 0, len(raw_text)
    return idx, idx + len(raw_text)


def extract_entities(state: AuditResult) -> AuditResult:
    state.state = AuditState.EXTRACT
    client = OpenAI(api_key=settings.openai_api_key)

    try:
        response = client.chat.completions.create(
            model=settings.llm_model,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM},
                {"role": "user", "content": f"Clinical note:\n\n{state.clinical_note}"},
            ],
        )
        raw = json.loads(response.choices[0].message.content)
    except Exception as exc:
        state.state = AuditState.FAILED
        state.error = f"Extraction LLM failure: {exc}"
        return state

    entities: list[ExtractedEntity] = []
    ambiguity_flags: list[AmbiguityFlag] = []

    for item in raw.get("entities", []):
        raw_text = item.get("raw_text", "")
        confidence = float(item.get("confidence", 0.0))
        start, end = _find_char_offset(state.clinical_note, raw_text)

        llm_negated = bool(item.get("is_negated", False))
        pattern_negated = _detect_negation_context(state.clinical_note, start, end)
        is_negated = llm_negated or pattern_negated

        source_span = SourceSpan(start=start, end=end, text=state.clinical_note[start:end])

        candidates = is_ambiguous(raw_text)
        if candidates:
            ambiguity_flags.append(AmbiguityFlag(
                entity_raw_text=raw_text,
                reason=AmbiguityReason.ABBREVIATION,
                confidence=confidence,
                candidates=[{"label": c} for c in candidates],
                source_span=source_span,
                requires_human_review=True,
            ))
            continue

        try:
            entity_type = EntityType(item.get("entity_type", "drug"))
        except ValueError:
            entity_type = EntityType.DRUG

        if entity_type in (EntityType.DRUG, EntityType.ALLERGY):
            if confidence < settings.extraction_confidence_threshold:
                ambiguity_flags.append(AmbiguityFlag(
                    entity_raw_text=raw_text,
                    reason=AmbiguityReason.LOW_CONFIDENCE,
                    confidence=confidence,
                    candidates=[],
                    source_span=source_span,
                    requires_human_review=True,
                ))
                continue

        rxnorm_result = lookup_rxnorm(item.get("normalized_name", raw_text))
        rxnorm_code = rxnorm_result[0] if rxnorm_result else None
        normalized_name = rxnorm_result[1] if rxnorm_result else item.get("normalized_name", raw_text)

        entities.append(ExtractedEntity(
            entity_type=entity_type,
            raw_text=raw_text,
            normalized_name=normalized_name,
            confidence=confidence,
            source_span=source_span,
            rxnorm_code=rxnorm_code,
            dosage=item.get("dosage"),
            route=item.get("route"),
            frequency=item.get("frequency"),
            is_negated=is_negated,
        ))

    state.entities = entities
    state.ambiguity_flags = ambiguity_flags

    if ambiguity_flags:
        state.requires_manual_review = True
        log.warning(
            "Audit %s: %d ambiguity flags raised — escalating to manual review.",
            state.audit_id, len(ambiguity_flags),
        )

    return state
