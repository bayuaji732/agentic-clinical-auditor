from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.workflow import run_audit
from utils.models import AuditResult, InteractionSeverity

log = logging.getLogger(__name__)

ADVERSARIAL_GOLD_DATASET: list[dict] = [
    {
        "id": "ADV-001",
        "description": "Direct DDI — standard phrasing",
        "note": "Patient is on Warfarin 5mg daily. Started Aspirin 81mg for cardiac prophylaxis.",
        "expected_critical": ["DDI-001"],
        "expected_entities": ["warfarin", "aspirin"],
        "expected_negated": [],
    },
    {
        "id": "ADV-002",
        "description": "Synonym perturbation — Aspirin as ASA",
        "note": "Patient prescribed Coumadin 5mg OD and ASA 81mg.",
        "expected_critical": [],
        "expected_entities": [],
        "expected_negated": [],
        "requires_manual_review": True,
        "ambiguity_trigger": "ASA",
    },
    {
        "id": "ADV-003",
        "description": "Adversarial negation — should NOT receive",
        "note": "Patient should NOT receive warfarin. Currently on Aspirin 100mg.",
        "expected_critical": [],
        "expected_entities": ["aspirin"],
        "expected_negated": ["warfarin"],
    },
    {
        "id": "ADV-004",
        "description": "Negation with discontinue",
        "note": "Discontinue ibuprofen. Patient remains on warfarin 5mg daily.",
        "expected_critical": [],
        "expected_entities": ["warfarin"],
        "expected_negated": ["ibuprofen"],
    },
    {
        "id": "ADV-005",
        "description": "Full name synonym — Acetylsalicylic acid",
        "note": "Patient taking warfarin and acetylsalicylic acid 100mg QD.",
        "expected_critical": ["DDI-001"],
        "expected_entities": ["warfarin", "aspirin"],
        "expected_negated": [],
    },
    {
        "id": "ADV-006",
        "description": "Serotonin syndrome — SSRI + Tramadol",
        "note": "Prescription: Fluoxetine 20mg daily, Tramadol 50mg PRN pain.",
        "expected_critical": ["DDI-007"],
        "expected_entities": ["fluoxetine", "tramadol"],
        "expected_negated": [],
    },
    {
        "id": "ADV-007",
        "description": "Rhabdomyolysis risk",
        "note": "Cardiac patient on Amiodarone 200mg and Simvastatin 80mg.",
        "expected_critical": ["DDI-003"],
        "expected_entities": ["amiodarone", "simvastatin"],
        "expected_negated": [],
    },
    {
        "id": "ADV-008",
        "description": "Allergy contraindication",
        "note": "Allergies: Ibuprofen. Treatment: Warfarin 5mg, Ibuprofen 400mg TID.",
        "expected_critical": [],
        "expected_entities": ["warfarin"],
        "expected_negated": [],
        "expected_allergy_flags": True,
    },
    {
        "id": "ADV-009",
        "description": "No interaction — safe combination",
        "note": "Patient on Lisinopril 10mg and Metformin 500mg BID for hypertension and T2DM.",
        "expected_critical": [],
        "expected_entities": ["lisinopril", "metformin"],
        "expected_negated": [],
    },
    {
        "id": "ADV-010",
        "description": "ER abbreviation stress — MTX",
        "note": "Patient receiving MTX 15mg weekly.",
        "expected_critical": [],
        "expected_entities": [],
        "requires_manual_review": True,
        "ambiguity_trigger": "MTX",
    },
]


@dataclass
class CaseResult:
    case_id: str
    description: str
    passed: bool
    critical_recall: float
    false_positive_critical: int
    manual_review_correct: bool
    negation_correct: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    total_cases: int
    passed: int
    failed: int
    safety_floor_met: bool
    critical_recall: float
    false_positive_rate: float
    manual_review_accuracy: float
    negation_accuracy: float
    case_results: list[CaseResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_cases": self.total_cases,
            "passed": self.passed,
            "failed": self.failed,
            "safety_floor_met": self.safety_floor_met,
            "critical_recall": round(self.critical_recall, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "manual_review_accuracy": round(self.manual_review_accuracy, 4),
            "negation_accuracy": round(self.negation_accuracy, 4),
            "cases": [
                {
                    "id": r.case_id,
                    "description": r.description,
                    "passed": r.passed,
                    "errors": r.errors,
                }
                for r in self.case_results
            ],
        }


def _evaluate_case(case: dict) -> CaseResult:
    result = run_audit(case["note"])
    errors: list[str] = []

    actual_critical_rule_ids = {
        f.provenance.rule_id
        for f in result.safety_flags
        if f.severity == InteractionSeverity.CRITICAL and f.provenance
    }
    expected_critical = set(case.get("expected_critical", []))

    missed = expected_critical - actual_critical_rule_ids
    for rule_id in missed:
        errors.append(f"MISSED CRITICAL: {rule_id}")

    false_positives = actual_critical_rule_ids - expected_critical
    fp_count = len(false_positives)

    critical_recall = (
        len(expected_critical & actual_critical_rule_ids) / len(expected_critical)
        if expected_critical else 1.0
    )

    manual_review_expected = case.get("requires_manual_review", False)
    manual_review_correct = result.requires_manual_review == manual_review_expected
    if not manual_review_correct:
        errors.append(
            f"Manual review mismatch: expected={manual_review_expected}, got={result.requires_manual_review}"
        )

    negated_entities = {
        e.normalized_name.lower()
        for e in result.entities
        if e.is_negated
    }
    expected_negated = {n.lower() for n in case.get("expected_negated", [])}
    negation_correct = expected_negated.issubset(negated_entities) if expected_negated else True
    if not negation_correct:
        missed_neg = expected_negated - negated_entities
        errors.append(f"Missed negation detection: {missed_neg}")

    passed = len(errors) == 0
    return CaseResult(
        case_id=case["id"],
        description=case["description"],
        passed=passed,
        critical_recall=critical_recall,
        false_positive_critical=fp_count,
        manual_review_correct=manual_review_correct,
        negation_correct=negation_correct,
        errors=errors,
    )


def run_evaluation(dataset: list[dict] | None = None) -> EvalReport:
    dataset = dataset or ADVERSARIAL_GOLD_DATASET
    case_results: list[CaseResult] = []

    log.info("Starting evaluation on %d cases.", len(dataset))
    for case in dataset:
        log.info("Evaluating case %s: %s", case["id"], case["description"])
        cr = _evaluate_case(case)
        case_results.append(cr)
        if not cr.passed:
            log.warning("FAILED: %s — %s", case["id"], cr.errors)

    total = len(case_results)
    passed = sum(1 for r in case_results if r.passed)

    critical_cases = [r for r in case_results if r.critical_recall < 1.0]
    safety_floor_met = len(critical_cases) == 0

    avg_recall = (
        sum(r.critical_recall for r in case_results) / total if total else 0.0
    )
    total_fp = sum(r.false_positive_critical for r in case_results)
    fp_rate = total_fp / total if total else 0.0

    manual_correct = sum(1 for r in case_results if r.manual_review_correct)
    manual_accuracy = manual_correct / total if total else 0.0

    negation_correct = sum(1 for r in case_results if r.negation_correct)
    negation_accuracy = negation_correct / total if total else 0.0

    report = EvalReport(
        total_cases=total,
        passed=passed,
        failed=total - passed,
        safety_floor_met=safety_floor_met,
        critical_recall=avg_recall,
        false_positive_rate=fp_rate,
        manual_review_accuracy=manual_accuracy,
        negation_accuracy=negation_accuracy,
        case_results=case_results,
    )

    log.info(
        "Eval complete: %d/%d passed | safety_floor=%s | recall=%.4f",
        passed, total, safety_floor_met, avg_recall,
    )
    return report
