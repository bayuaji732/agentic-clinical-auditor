from __future__ import annotations
import logging
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agents.workflow import run_audit
from evaluation.evaluator import run_evaluation
from utils.models import AuditResult, AuditState

log = logging.getLogger(__name__)

app = FastAPI(
    title="Clinical Protocol Safety Engine",
    description="Deterministic DDI/allergy auditor with full provenance tracking.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuditRequest(BaseModel):
    clinical_note: str = Field(..., min_length=10, max_length=20_000)


class ProvenanceOut(BaseModel):
    rule_id: str
    kb_version: str
    logic_hash: str
    ontology_code: str
    ontology_system: str
    source_span: dict
    extracted_at: str
    engine_version: str


class SafetyFlagOut(BaseModel):
    id: str
    severity: str
    entity_a: str
    entity_b: str
    description: str
    recommendation: str
    provenance: ProvenanceOut | None


class AmbiguityFlagOut(BaseModel):
    entity_raw_text: str
    reason: str
    confidence: float
    candidates: list[dict]
    requires_human_review: bool


class EntityOut(BaseModel):
    entity_type: str
    raw_text: str
    normalized_name: str
    confidence: float
    rxnorm_code: str | None
    dosage: str | None
    route: str | None
    frequency: str | None
    is_negated: bool
    source_span: dict | None


class AuditResponse(BaseModel):
    audit_id: str
    state: str
    completed: bool
    requires_manual_review: bool
    entities: list[EntityOut]
    safety_flags: list[SafetyFlagOut]
    ambiguity_flags: list[AmbiguityFlagOut]
    critical_count: int
    warning_count: int
    error: str | None


def _serialize_result(result: AuditResult) -> AuditResponse:
    entities_out = [
        EntityOut(
            entity_type=e.entity_type.value,
            raw_text=e.raw_text,
            normalized_name=e.normalized_name,
            confidence=e.confidence,
            rxnorm_code=e.rxnorm_code,
            dosage=e.dosage,
            route=e.route,
            frequency=e.frequency,
            is_negated=e.is_negated,
            source_span=(
                {"start": e.source_span.start, "end": e.source_span.end, "text": e.source_span.text}
                if e.source_span else None
            ),
        )
        for e in result.entities
    ]

    flags_out = []
    for f in result.safety_flags:
        prov_out = None
        if f.provenance:
            p = f.provenance
            prov_out = ProvenanceOut(
                rule_id=p.rule_id,
                kb_version=p.kb_version,
                logic_hash=p.logic_hash,
                ontology_code=p.ontology_code,
                ontology_system=p.ontology_system,
                source_span={"start": p.source_span.start, "end": p.source_span.end, "text": p.source_span.text},
                extracted_at=p.extracted_at,
                engine_version=p.engine_version,
            )
        flags_out.append(SafetyFlagOut(
            id=f.id,
            severity=f.severity.value,
            entity_a=f.entity_a,
            entity_b=f.entity_b,
            description=f.description,
            recommendation=f.recommendation,
            provenance=prov_out,
        ))

    ambiguity_out = [
        AmbiguityFlagOut(
            entity_raw_text=a.entity_raw_text,
            reason=a.reason.value,
            confidence=a.confidence,
            candidates=a.candidates,
            requires_human_review=a.requires_human_review,
        )
        for a in result.ambiguity_flags
    ]

    return AuditResponse(
        audit_id=result.audit_id,
        state=result.state.value,
        completed=result.completed,
        requires_manual_review=result.requires_manual_review,
        entities=entities_out,
        safety_flags=flags_out,
        ambiguity_flags=ambiguity_out,
        critical_count=len(result.critical_flags),
        warning_count=len(result.warning_flags),
        error=result.error,
    )


@app.post("/audit", response_model=AuditResponse)
async def audit_clinical_note(req: AuditRequest):
    result = run_audit(req.clinical_note)
    if result.state == AuditState.FAILED:
        raise HTTPException(status_code=500, detail=result.error)
    return _serialize_result(result)


@app.post("/evaluate")
async def evaluate():
    report = run_evaluation()
    return report.to_dict()


@app.get("/rules")
async def list_rules():
    from kb.knowledge_base import get_ddi_rules, LOGIC_HASH
    from config import settings
    return {
        "kb_version": settings.kb_version,
        "logic_hash": LOGIC_HASH,
        "rule_count": len(get_ddi_rules()),
        "rules": get_ddi_rules(),
    }


@app.get("/health")
async def health():
    from kb.knowledge_base import LOGIC_HASH
    from config import settings
    return {
        "status": "ok",
        "kb_version": settings.kb_version,
        "logic_hash": LOGIC_HASH,
    }
