from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import uuid


class EntityType(str, Enum):
    DRUG = "drug"
    ALLERGY = "allergy"
    CONDITION = "condition"
    DOSAGE = "dosage"
    ROUTE = "route"


class InteractionSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFORMATIONAL = "INFORMATIONAL"


class AmbiguityReason(str, Enum):
    MULTIPLE_MAPPINGS = "multiple_mappings"
    LOW_CONFIDENCE = "low_confidence"
    ABBREVIATION = "abbreviation"
    CONTEXT_DEPENDENT = "context_dependent"


class AuditState(str, Enum):
    EXTRACT = "extract"
    VALIDATE_ENTITIES = "validate_entities"
    KB_LOOKUP = "kb_lookup"
    CONFLICT_CHECK = "conflict_check"
    FINAL_AUDIT = "final_audit"
    MANUAL_REVIEW = "manual_review"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class SourceSpan:
    start: int
    end: int
    text: str


@dataclass
class Provenance:
    rule_id: str
    kb_version: str
    logic_hash: str
    ontology_code: str
    ontology_system: str
    source_span: SourceSpan
    extracted_at: str
    engine_version: str = "1.0.0"


@dataclass
class ExtractedEntity:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    entity_type: EntityType = EntityType.DRUG
    raw_text: str = ""
    normalized_name: str = ""
    confidence: float = 0.0
    source_span: Optional[SourceSpan] = None
    rxnorm_code: Optional[str] = None
    snomed_code: Optional[str] = None
    dosage: Optional[str] = None
    route: Optional[str] = None
    frequency: Optional[str] = None
    is_negated: bool = False


@dataclass
class AmbiguityFlag:
    entity_raw_text: str
    reason: AmbiguityReason
    confidence: float
    candidates: list[dict]
    source_span: Optional[SourceSpan] = None
    requires_human_review: bool = True


@dataclass
class SafetyFlag:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    severity: InteractionSeverity = InteractionSeverity.WARNING
    entity_a: str = ""
    entity_b: str = ""
    description: str = ""
    recommendation: str = ""
    provenance: Optional[Provenance] = None


@dataclass
class AuditResult:
    audit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: AuditState = AuditState.EXTRACT
    clinical_note: str = ""
    entities: list[ExtractedEntity] = field(default_factory=list)
    ambiguity_flags: list[AmbiguityFlag] = field(default_factory=list)
    safety_flags: list[SafetyFlag] = field(default_factory=list)
    error: Optional[str] = None
    requires_manual_review: bool = False
    completed: bool = False

    @property
    def critical_flags(self) -> list[SafetyFlag]:
        return [f for f in self.safety_flags if f.severity == InteractionSeverity.CRITICAL]

    @property
    def warning_flags(self) -> list[SafetyFlag]:
        return [f for f in self.safety_flags if f.severity == InteractionSeverity.WARNING]
