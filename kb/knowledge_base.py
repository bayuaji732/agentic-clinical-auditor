from __future__ import annotations
import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from config import settings

log = logging.getLogger(__name__)

# Fallback definitions if files don't exist
_DEFAULT_DDI_RULES = [
    {
        "rule_id": "DDI-001",
        "drug_a_rxnorm": "11289",
        "drug_b_rxnorm": "114970",
        "drug_a_name": "warfarin",
        "drug_b_name": "aspirin",
        "severity": "CRITICAL",
        "description": "Warfarin + Aspirin: significant bleeding risk. Concurrent use increases hemorrhagic events 3-5x.",
        "recommendation": "Avoid concurrent use. If necessary, monitor INR closely and use lowest aspirin dose.",
    },
    {
        "rule_id": "DDI-002",
        "drug_a_rxnorm": "11289",
        "drug_b_rxnorm": "41493",
        "drug_a_name": "warfarin",
        "drug_b_name": "ibuprofen",
        "severity": "CRITICAL",
        "description": "Warfarin + NSAIDs: markedly increased bleeding risk and potential for warfarin displacement.",
        "recommendation": "Contraindicated. Use acetaminophen as analgesic alternative with close INR monitoring.",
    },
    {
        "rule_id": "DDI-003",
        "drug_a_rxnorm": "36567",
        "drug_b_rxnorm": "321988",
        "drug_a_name": "simvastatin",
        "drug_b_name": "amiodarone",
        "severity": "CRITICAL",
        "description": "Simvastatin + Amiodarone: risk of myopathy and rhabdomyolysis. Amiodarone inhibits CYP3A4.",
        "recommendation": "Limit simvastatin to 20mg/day. Consider alternative statin (pravastatin, rosuvastatin).",
    },
    {
        "rule_id": "DDI-004",
        "drug_a_rxnorm": "32968",
        "drug_b_rxnorm": "2200644",
        "drug_a_name": "methotrexate",
        "drug_b_name": "trimethoprim",
        "severity": "CRITICAL",
        "description": "Methotrexate + Trimethoprim: severe bone marrow suppression. Both inhibit dihydrofolate reductase.",
        "recommendation": "Contraindicated. Monitor CBC. Folinic acid rescue if combination unavoidable.",
    },
    {
        "rule_id": "DDI-005",
        "drug_a_rxnorm": "41493",
        "drug_b_rxnorm": "7646",
        "drug_a_name": "ibuprofen",
        "drug_b_name": "lithium",
        "severity": "CRITICAL",
        "description": "NSAIDs + Lithium: NSAIDs reduce renal lithium clearance causing toxicity.",
        "recommendation": "Avoid. Use acetaminophen. If NSAID required, reduce lithium dose and monitor serum levels.",
    },
    {
        "rule_id": "DDI-006",
        "drug_a_rxnorm": "114970",
        "drug_b_rxnorm": "7646",
        "drug_a_name": "aspirin",
        "drug_b_name": "metformin",
        "severity": "INFORMATIONAL",
        "description": "Low-dose aspirin with metformin: generally safe. Monitor for GI effects.",
        "recommendation": "No dose adjustment required. Monitor for GI symptoms.",
    },
    {
        "rule_id": "DDI-007",
        "drug_a_rxnorm": "50121",
        "drug_b_rxnorm": "2200644",
        "drug_a_name": "fluoxetine",
        "drug_b_name": "tramadol",
        "severity": "CRITICAL",
        "description": "SSRIs + Tramadol: serotonin syndrome risk. Tramadol inhibits serotonin reuptake.",
        "recommendation": "Contraindicated. Use alternative analgesic. If unavoidable, monitor for serotonin syndrome.",
    },
    {
        "rule_id": "DDI-008",
        "drug_a_rxnorm": "29046",
        "drug_b_rxnorm": "50121",
        "drug_a_name": "lisinopril",
        "drug_b_name": "potassium",
        "severity": "WARNING",
        "description": "ACE inhibitors + Potassium supplements: hyperkalemia risk.",
        "recommendation": "Monitor serum potassium. Avoid high-dose potassium supplementation.",
    },
]

_DEFAULT_RXNORM_SYNONYMS = {
    "11289":   ["warfarin", "coumadin", "jantoven"],
    "114970":  ["aspirin", "asa", "acetylsalicylic acid", "ecotrin", "bufferin"],
    "41493":   ["ibuprofen", "advil", "motrin", "nurofen"],
    "36567":   ["simvastatin", "zocor"],
    "321988":  ["amiodarone", "cordarone", "pacerone"],
    "32968":   ["methotrexate", "mtx", "rheumatrex", "trexall"],
    "2200644": ["trimethoprim", "tmp", "proloprim", "primsol", "tramadol", "ultram", "conzip"],
    "7646":    ["lithium", "lithobid", "eskalith", "metformin", "glucophage", "fortamet"],
    "50121":   ["fluoxetine", "prozac", "sarafem"],
    "29046":   ["lisinopril", "prinivil", "zestril"],
}

_DEFAULT_AMBIGUOUS_TERMS = {
    "asa":  ["aspirin (RxNorm:114970)", "aminosalicylic acid (RxNorm:57561)"],
    "tmp":  ["trimethoprim (RxNorm:2200644)", "thymidine monophosphate"],
    "mtx":  ["methotrexate (RxNorm:32968)", "mitoxantrone (RxNorm:30764)"],
}

_DEFAULT_CROSS_REACTIVITY = {
    "114970": ["41493"],
    "41493": ["114970"],
}


def _initialize_dbs():
    # 1. Initialize DDI rules JSON
    ddi_path = Path(settings.ddi_rules_path)
    ddi_path.parent.mkdir(parents=True, exist_ok=True)
    if not ddi_path.exists():
        log.info("Creating %s from default DDI rules...", ddi_path)
        with open(ddi_path, "w") as f:
            json.dump(_DEFAULT_DDI_RULES, f, indent=2)

    # 2. Initialize RxNorm SQLite Database
    db_path = Path(settings.rxnorm_db_path)
    if not db_path.exists():
        log.info("Seeding RxNorm SQLite database...")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()
            
            # Create tables
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS rxnorm_codes (
                    code TEXT,
                    canonical_name TEXT,
                    synonym TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ambiguous_terms (
                    term TEXT,
                    candidate TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cross_reactivity (
                    drug_rxnorm TEXT,
                    allergen_rxnorm TEXT
                )
            ''')

            # Create indices
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_rxnorm_syn on rxnorm_codes(synonym)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ambig_term on ambiguous_terms(term)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cross_reactivity on cross_reactivity(drug_rxnorm)')
            
            # Seed data
            for code, syns in _DEFAULT_RXNORM_SYNONYMS.items():
                canonical = syns[0]
                for s in syns:
                    cursor.execute(
                        'INSERT INTO rxnorm_codes (code, canonical_name, synonym) VALUES (?, ?, ?)',
                        (code, canonical, s.lower())
                    )
            
            for term, candidates in _DEFAULT_AMBIGUOUS_TERMS.items():
                for c in candidates:
                    cursor.execute(
                        'INSERT INTO ambiguous_terms (term, candidate) VALUES (?, ?)',
                        (term.lower(), c)
                    )
            
            for drug_code, cross_codes in _DEFAULT_CROSS_REACTIVITY.items():
                for cross_code in cross_codes:
                    cursor.execute(
                        'INSERT INTO cross_reactivity (drug_rxnorm, allergen_rxnorm) VALUES (?, ?)',
                        (drug_code, cross_code)
                    )
            conn.commit()

# Bootstrap on import
_initialize_dbs()


def _compute_rule_hash(filepath: Path) -> str:
    if filepath.exists():
        with open(filepath, "r") as f:
            payload = json.dumps(json.load(f), sort_keys=True).encode()
            return hashlib.sha256(payload).hexdigest()
    return ""

def _load_ddi_rules() -> list[dict]:
    filepath = Path(settings.ddi_rules_path)
    if filepath.exists():
        with open(filepath, "r") as f:
            return json.load(f)
    return []

# Dynamic logic state
DDI_RULES = _load_ddi_rules()
LOGIC_HASH = _compute_rule_hash(Path(settings.ddi_rules_path))


def lookup_rxnorm(term: str) -> Optional[tuple[str, str]]:
    normalized = term.lower().strip()
    
    with sqlite3.connect(settings.rxnorm_db_path) as conn:
        cursor = conn.cursor()
        
        # Exact match
        cursor.execute('SELECT code, canonical_name FROM rxnorm_codes WHERE synonym = ? LIMIT 1', (normalized,))
        row = cursor.fetchone()
        if row:
            return (row[0], row[1])
            
        # Try substring match: the mapped synonym is inside the user term
        cursor.execute('SELECT code, canonical_name, synonym FROM rxnorm_codes')
        for r_code, r_canonical, r_synonym in cursor.fetchall():
            if r_synonym in normalized or normalized in r_synonym:
                return (r_code, r_canonical)
    
    return None

def is_ambiguous(term: str) -> Optional[list[str]]:
    normalized = term.lower().strip()
    with sqlite3.connect(settings.rxnorm_db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT candidate FROM ambiguous_terms WHERE term = ?', (normalized,))
        rows = cursor.fetchall()
        if rows:
            return [r[0] for r in rows]
    return None


def get_ddi_rules() -> list[dict]:
    return DDI_RULES


def check_interactions(rxnorm_codes: list[str]) -> list[dict]:
    flagged: list[dict] = []
    code_set = set(rxnorm_codes)
    seen: set[tuple] = set()

    for rule in DDI_RULES:
        a = rule["drug_a_rxnorm"]
        b = rule["drug_b_rxnorm"]
        if a in code_set and b in code_set:
            pair = tuple(sorted([a, b]))
            if pair not in seen:
                seen.add(pair)
                flagged.append(rule)
    return flagged


def check_allergy_contraindication(
    drug_rxnorm: str,
    allergy_rxnorm_list: list[str],
) -> Optional[dict]:
    if drug_rxnorm in allergy_rxnorm_list:
        return {
            "type": "direct_allergy",
            "rule_id": f"ALLERGY-DIRECT-{drug_rxnorm}",
            "severity": "CRITICAL",
            "description": "Direct allergy contraindication: prescribed drug matches patient allergy.",
        }

    with sqlite3.connect(settings.rxnorm_db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT allergen_rxnorm FROM cross_reactivity WHERE drug_rxnorm = ?', (drug_rxnorm,))
        cross = [r[0] for r in cursor.fetchall()]

    for allergen in allergy_rxnorm_list:
        if allergen in cross:
            return {
                "type": "cross_reactivity",
                "rule_id": f"ALLERGY-CROSS-{drug_rxnorm}-{allergen}",
                "severity": "WARNING",
                "description": f"Cross-reactivity risk between drug (RxNorm:{drug_rxnorm}) and known allergen (RxNorm:{allergen}).",
            }
    return None
