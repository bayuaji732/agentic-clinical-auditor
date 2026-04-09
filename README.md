# Clinical Protocol Safety Engine

**An Agentic AI Healthcare Application for Clinical Note Auditing**

A deterministic, multi-agent drug-drug interaction (DDI) and allergy safety auditor with full provenance tracking, zero-regeneration policies, and adversarial evaluation protocols. Built for HIPAA-compliant, bare-metal deployments.

This project was developed as a flagship, demonstrating advanced capabilities in orchestrating non-deterministic Large Language Models (LLMs) alongside strict, deterministic safety rulesets (SQLite + JSON) using a state machine architecture.

## 🧠 Agentic AI Design & Architecture

This system demonstrates "Safe Agentic AI" — restricting an LLM's autonomy to strictly what it is good at (Natural Language Understanding) and offloading critical safety logic to deterministic programmatic checks.

### Core Agentic Workflows:
1. **Delegation via LangGraph**: The system utilizes a cyclic/directed state machine (LangGraph) to orchestrate agentic steps (Extract → Resolve → Check → Finalize), ensuring the execution graph is auditable and predictable.
2. **Confidence-Gated Autonomy**: The LLM Extractor assigns internal confidence scores ($0.0 - 1.0$) to its own entity extractions. Extractions that fall below the strict safety floor ($p < 0.95$) trigger an abort in the autonomous pipeline, immediately escalating the state to `MANUAL_REVIEW`.
3. **Ontology Resolution**: Extracted entities are passed through a deterministic synonym expansion and RxNorm mapping node. This prevents the LLM from trying to "hallucinate" safety conclusions based on loose string overlaps.

### The Execution Graph

```text
Clinical Note (raw text)
        ↓
[EXTRACT AGENT]     LLM extraction + confidence thresholding (p < 0.95 → MANUAL_REVIEW)
        ↓
[VALIDATION NODE]   RxNorm resolution, unresolved entity escalation
        ↓
[KNOWLEDGE BASE]    SQLite synonym expansion, ambiguity flagging
        ↓
[SAFETY ENGINE]     Deterministic DDI rules (70+ mapped Kaggle interactions) + Allergy cross-reactivity
        ↓
[AUDIT RESOLVER]    Severity tiering, state resolution calculation
        ↓
COMPLETE | MANUAL_REVIEW | FAILED
```

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Zero-Regeneration** | No retry loops on ambiguity — escalate to human |
| **Agentic Confidence Threshold** | Below 0.95 -> AmbiguityFlag, no "best guessing" |
| **Deterministic Backend** | Moving away from LLM "knowledge base querying" to strict SQLite/JSON execution |
| **Provenance per Flag** | Rule ID, KB version, logic hash, source span, timestamp |
| **Safety Floor** | 100% recall required on CRITICAL rules in CI/CD gate |

## 📦 Knowledge Base Infrastructure

The system employs a fast, locally hosted SQLite database (`kb/rxnorm.db`) interlinked with a dynamic JSON rules engine (`kb/ddi_rules.json`). 

*   **Expansive Coverage:** It is seeded with nearly 100 dynamically resolved, clinically peer-reviewed Drug-Drug Interactions sourced from academic datasets (Kaggle DDI 2.0). 
*   **RxNorm Ontology:** All drugs are translated dynamically into NIH RxNorm Canonical Identifiers via the RxNav REST API, guaranteeing exact matching.

## Quickstart

```bash
cp .env.example .env
# Fill in OPENAI_API_KEY

uv init
uv add -r requirements.txt
uv run uvicorn api.main:app --reload
```

## API Usage

**High-Confidence Agentic Audit Example (Bypasses manual review to Flag CRITICAL):**
```bash
curl -X POST http://localhost:8000/audit \
  -H "Content-Type: application/json" \
  -d '{"clinical_note": "Patient is prescribed 50mg Sildenafil for erectile dysfunction. Also taking Nitroglycerin sublingually for chest pain. Patient has no known drug allergies."}'
```
*Expected Output: The agent detects Sildenafil (RxNorm: 11149) and Nitroglycerin (RxNorm: 7454), maps them against the DDI engine, and correctly categorizes the state as `COMPLETE` but emitting a `CRITICAL` safety flag for profound hypotension risk.*

**Low-Confidence Audit Example (Ambiguity triggers Manual Review):**
```bash
curl -X POST http://localhost:8000/audit \
  -H "Content-Type: application/json" \
  -d '{"clinical_note": "Patient is prescribed 20mg Lisinopril for hypertension. Started taking \"the blue pill\" today for a mild headache."}'
```
*Expected Output: The Extractor Agent detects "the blue pill" but assigns a low confidence score, instantly escalating the system state to `MANUAL_REVIEW` by human clinicians.*

**Run adversarial evaluation:**
```bash
curl -X POST http://localhost:8000/evaluate
```

## Evaluation Framework

Gold dataset: Adversarial cases designed to trick LLMs.

| Metric | Target |
|---|---|
| CRITICAL recall | 100% (safety floor — CI gate) |
| False positive rate | ≤ 1% |
| Manual review accuracy | ≥ 99% |

### Adversarial Test Types
- **Synonym perturbation**: Warfarin → Coumadin, Aspirin → Acetylsalicylic acid
- **Abbreviation stress**: ASA, MTX, TMP — all trigger AmbiguityFlag + MANUAL_REVIEW
- **Adversarial phrasing**: "should NOT receive X" → negation correctly detected
- **ER shorthand**: Discontinue, PRN, QD, OD, BID, TID

## Project Structure

```text
clinical-safety-engine/
├── config.py
├── api/
│   └── main.py              FastAPI endpoints
├── agents/
│   ├── extractor.py         LLM extraction + confidence gating
│   ├── checker.py           DDI/allergy conflict checker + provenance
│   └── workflow.py          LangGraph state machine
├── kb/
│   ├── rxnorm.db            SQLite database for synonym expansion
│   ├── ddi_rules.json       Dynamic JSON rules engine
│   └── knowledge_base.py    KB controllers
├── evaluation/
│   └── evaluator.py         Adversarial gold dataset + eval metrics
└── utils/
    └── models.py            Dataclasses, enums, state types
```
