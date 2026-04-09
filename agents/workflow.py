from __future__ import annotations
import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.extractor import extract_entities
from agents.checker import (
    conflict_check, final_audit, kb_lookup, validate_entities,
)
from utils.models import AuditResult, AuditState

log = logging.getLogger(__name__)


def _route_after_extraction(state: AuditResult) -> str:
    if state.state == AuditState.FAILED:
        return "failed"
    if state.requires_manual_review and not state.entities:
        return "manual_review"
    return "validate_entities"


def _route_after_validation(state: AuditResult) -> str:
    active_drugs = [
        e for e in state.entities
        if not e.is_negated and e.rxnorm_code
    ]
    if not active_drugs:
        log.info("No active resolvable drugs found — skipping conflict check.")
        return "final_audit"
    return "kb_lookup"


def _manual_review_node(state: AuditResult) -> AuditResult:
    state.state = AuditState.MANUAL_REVIEW
    state.completed = True
    log.warning(
        "Audit %s routed to MANUAL REVIEW. Ambiguity flags: %d",
        state.audit_id, len(state.ambiguity_flags),
    )
    return state


def _failed_node(state: AuditResult) -> AuditResult:
    state.state = AuditState.FAILED
    state.completed = True
    return state


def build_workflow() -> Any:
    graph = StateGraph(AuditResult)

    graph.add_node("extract", extract_entities)
    graph.add_node("validate_entities", validate_entities)
    graph.add_node("kb_lookup", kb_lookup)
    graph.add_node("conflict_check", conflict_check)
    graph.add_node("final_audit", final_audit)
    graph.add_node("manual_review", _manual_review_node)
    graph.add_node("failed", _failed_node)

    graph.add_edge(START, "extract")

    graph.add_conditional_edges(
        "extract",
        _route_after_extraction,
        {
            "validate_entities": "validate_entities",
            "manual_review": "manual_review",
            "failed": "failed",
        },
    )

    graph.add_conditional_edges(
        "validate_entities",
        _route_after_validation,
        {
            "kb_lookup": "kb_lookup",
            "final_audit": "final_audit",
        },
    )

    graph.add_edge("kb_lookup", "conflict_check")
    graph.add_edge("conflict_check", "final_audit")
    graph.add_edge("final_audit", END)
    graph.add_edge("manual_review", END)
    graph.add_edge("failed", END)

    return graph.compile()


_workflow = None


def get_workflow():
    global _workflow
    if _workflow is None:
        _workflow = build_workflow()
    return _workflow


def run_audit(clinical_note: str) -> AuditResult:
    workflow = get_workflow()
    initial_state = AuditResult(clinical_note=clinical_note)
    result = workflow.invoke(initial_state)
    if isinstance(result, dict):
        return AuditResult(**result)
    return result
