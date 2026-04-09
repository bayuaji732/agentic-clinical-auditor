from __future__ import annotations
import logging
from datetime import datetime, timezone

from config import settings
from kb.knowledge_base import (
    LOGIC_HASH,
    check_interactions,
    check_allergy_contraindication,
)
from utils.models import (
    AuditResult, AuditState, EntityType,
    InteractionSeverity, Provenance, SafetyFlag, SourceSpan,
)

log = logging.getLogger(__name__)


def _build_provenance(
    rule: dict,
    entity_a_span: SourceSpan,
    entity_b_span: SourceSpan | None = None,
) -> Provenance:
    return Provenance(
        rule_id=rule["rule_id"],
        kb_version=settings.kb_version,
        logic_hash=LOGIC_HASH,
        ontology_code=rule.get("drug_a_rxnorm", rule.get("rxnorm", "")),
        ontology_system="RxNorm",
        source_span=entity_a_span,
        extracted_at=datetime.now(timezone.utc).isoformat(),
    )


def validate_entities(state: AuditResult) -> AuditResult:
    state.state = AuditState.VALIDATE_ENTITIES

    unresolved = [
        e for e in state.entities
        if not e.is_negated and e.rxnorm_code is None and e.entity_type == EntityType.DRUG
    ]
    if unresolved:
        for entity in unresolved:
            log.warning(
                "Audit %s: entity '%s' has no RxNorm mapping — flagging for review.",
                state.audit_id, entity.raw_text,
            )
            state.requires_manual_review = True

    return state


def kb_lookup(state: AuditResult) -> AuditResult:
    state.state = AuditState.KB_LOOKUP
    return state


def conflict_check(state: AuditResult) -> AuditResult:
    state.state = AuditState.CONFLICT_CHECK

    active_drugs = [
        e for e in state.entities
        if not e.is_negated and e.entity_type == EntityType.DRUG and e.rxnorm_code
    ]
    allergies = [
        e for e in state.entities
        if e.entity_type == EntityType.ALLERGY and e.rxnorm_code
    ]

    drug_codes = [e.rxnorm_code for e in active_drugs]
    allergy_codes = [e.rxnorm_code for e in allergies]

    code_to_entity = {e.rxnorm_code: e for e in active_drugs}
    code_to_entity.update({e.rxnorm_code: e for e in allergies})

    ddi_hits = check_interactions(drug_codes)
    for rule in ddi_hits:
        entity_a = code_to_entity.get(rule["drug_a_rxnorm"])
        entity_b = code_to_entity.get(rule["drug_b_rxnorm"])

        span_a = entity_a.source_span if entity_a else SourceSpan(0, 0, "")
        span_b = entity_b.source_span if entity_b else SourceSpan(0, 0, "")

        provenance = _build_provenance(rule, span_a, span_b)
        try:
            severity = InteractionSeverity(rule["severity"])
        except ValueError:
            severity = InteractionSeverity.WARNING

        state.safety_flags.append(SafetyFlag(
            severity=severity,
            entity_a=rule["drug_a_name"],
            entity_b=rule["drug_b_name"],
            description=rule["description"],
            recommendation=rule["recommendation"],
            provenance=provenance,
        ))
        log.info(
            "Audit %s: DDI flag [%s] %s — %s + %s",
            state.audit_id, rule["severity"], rule["rule_id"],
            rule["drug_a_name"], rule["drug_b_name"],
        )

    for drug in active_drugs:
        hit = check_allergy_contraindication(drug.rxnorm_code, allergy_codes)
        if hit:
            allergy_entity = next(
                (e for e in allergies if e.rxnorm_code in allergy_codes), None
            )
            span_a = drug.source_span or SourceSpan(0, 0, "")
            prov = _build_provenance(hit, span_a)
            try:
                severity = InteractionSeverity(hit["severity"])
            except ValueError:
                severity = InteractionSeverity.CRITICAL

            state.safety_flags.append(SafetyFlag(
                severity=severity,
                entity_a=drug.normalized_name,
                entity_b=allergy_entity.normalized_name if allergy_entity else "known allergen",
                description=hit["description"],
                recommendation="Do not administer. Document allergy override if clinically mandated.",
                provenance=prov,
            ))

    if not state.safety_flags:
        log.info("Audit %s: no interactions detected.", state.audit_id)

    return state


def final_audit(state: AuditResult) -> AuditResult:
    state.state = AuditState.FINAL_AUDIT

    critical_count = len(state.critical_flags)
    warning_count = len(state.warning_flags)

    log.info(
        "Audit %s complete: %d critical, %d warning flags | manual_review=%s",
        state.audit_id, critical_count, warning_count, state.requires_manual_review,
    )

    state.completed = True
    state.state = AuditState.COMPLETE if not state.requires_manual_review else AuditState.MANUAL_REVIEW
    return state
