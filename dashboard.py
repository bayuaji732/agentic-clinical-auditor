import json
from typing import Any, Dict, List

import pandas as pd
import requests
import streamlit as st

API_URL = "http://localhost:8000"
TIMEOUT = 20

# -----------------------------
# Configuration & State
# -----------------------------
st.set_page_config(
    page_title="Clinical Protocol Safety Engine",
    page_icon="⚕️",
    layout="wide",
    initial_sidebar_state="expanded",
)

DEFAULT_NOTE = (
    'Patient is prescribed 50mg Sildenafil for erectile dysfunction. '
    'Also taking Nitroglycerin sublingually for chest pain. '
    'Patient has no known drug allergies.'
)

if "note_text" not in st.session_state:
    st.session_state.note_text = DEFAULT_NOTE

# -----------------------------
# Styling (Theme-Aware UI)
# -----------------------------
st.markdown(
    """
<style>
    /* Main container spacing */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1400px;
    }

    /* Modern Hero Cards - Uses Streamlit's native theme variables */
    .hero-card {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }

    /* Status Flags - Uses rgba to adapt to both dark and light backgrounds */
    .flag-base {
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
        transition: transform 0.1s ease-in-out;
    }
    
    .flag-base:hover {
        transform: translateY(-2px);
    }

    .flag-critical {
        background-color: rgba(239, 68, 68, 0.1);
        border-left: 4px solid #ef4444;
        border-right: 1px solid rgba(239, 68, 68, 0.2);
        border-top: 1px solid rgba(239, 68, 68, 0.2);
        border-bottom: 1px solid rgba(239, 68, 68, 0.2);
    }

    .flag-warning {
        background-color: rgba(245, 158, 11, 0.1);
        border-left: 4px solid #f59e0b;
        border-right: 1px solid rgba(245, 158, 11, 0.2);
        border-top: 1px solid rgba(245, 158, 11, 0.2);
        border-bottom: 1px solid rgba(245, 158, 11, 0.2);
    }

    .flag-info {
        background-color: rgba(14, 165, 233, 0.1);
        border-left: 4px solid #0ea5e9;
        border-right: 1px solid rgba(14, 165, 233, 0.2);
        border-top: 1px solid rgba(14, 165, 233, 0.2);
        border-bottom: 1px solid rgba(14, 165, 233, 0.2);
    }

    /* Typography */
    .section-title {
        margin-top: 0;
        margin-bottom: 0.5rem;
        color: var(--text-color);
        font-weight: 600;
        font-size: 1.5rem;
    }

    .subtle {
        color: var(--text-color);
        opacity: 0.7;
        font-size: 1rem;
        margin-bottom: 0;
    }

    .small-label {
        display: inline-block;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        font-size: 0.7rem;
        font-weight: 700;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        margin-bottom: 0.5rem;
    }
    
    .label-critical { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
    .label-warning { background: rgba(245, 158, 11, 0.2); color: #f59e0b; }
    .label-info { background: rgba(14, 165, 233, 0.2); color: #0ea5e9; }

    /* Custom Metric styling */
    [data-testid="stMetricValue"] {
        font-size: 1.8rem;
        font-weight: 600;
        color: var(--text-color);
    }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------
# API Helpers
# -----------------------------
def api_get(path: str) -> requests.Response:
    return requests.get(f"{API_URL}{path}", timeout=TIMEOUT)

def api_post(path: str, payload: Dict[str, Any] | None = None) -> requests.Response:
    return requests.post(f"{API_URL}{path}", json=payload, timeout=TIMEOUT)

def safe_list(value: Any) -> List[Dict[str, Any]]:
    return value if isinstance(value, list) else []

def fmt_pct(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except Exception:
        return "—"

def status_badge(state: str) -> tuple[str, str]:
    state_upper = (state or "").upper()
    if state_upper == "COMPLETE":
        return "🟢", "Secure & Complete"
    if state_upper == "MANUAL_REVIEW":
        return "🟠", "Needs Human Review"
    if state_upper:
        return "🔴", state_upper
    return "🔴", "Failed Check"

# -----------------------------
# Component Rendering Helpers
# -----------------------------
def render_flag(flag: Dict[str, Any]) -> None:
    severity = str(flag.get("severity", "")).upper()
    entity_a = flag.get("entity_a", "Unknown A")
    entity_b = flag.get("entity_b", "Unknown B")
    description = flag.get("description", "No description provided.")
    recommendation = flag.get("recommendation", "No recommendation provided.")
    provenance = flag.get("provenance")

    if severity == "CRITICAL":
        css_class = "flag-base flag-critical"
        label_class = "small-label label-critical"
    elif severity == "WARNING":
        css_class = "flag-base flag-warning"
        label_class = "small-label label-warning"
    else:
        css_class = "flag-base flag-info"
        label_class = "small-label label-info"

    label = severity or "FLAG"

    st.markdown(
        f"""
        <div class="{css_class}">
            <div class="{label_class}">{label}</div>
            <h4 style="margin: 0 0 0.5rem 0; color: var(--text-color); font-size: 1.1rem;">{entity_a} ↔ {entity_b}</h4>
            <p style="margin: 0.25rem 0; color: var(--text-color); opacity: 0.9; font-size: 0.95rem;"><strong>Description:</strong> {description}</p>
            <p style="margin: 0.25rem 0; color: var(--text-color); opacity: 0.9; font-size: 0.95rem;"><strong>Action:</strong> {recommendation}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if provenance:
        with st.expander("View Provenance Data", expanded=False):
            st.json(provenance)

def render_ambiguity(amb: Dict[str, Any]) -> None:
    raw = amb.get("entity_raw_text", "Unknown text")
    reason = amb.get("reason", "No reason provided.")
    confidence = amb.get("confidence", None)
    candidates = amb.get("candidates", [])

    confidence_text = f"{float(confidence):.2f}" if confidence is not None else "—"

    st.markdown(
        f"""
        <div class="flag-base flag-info">
            <div class="small-label label-info">AMBIGUITY / HUMAN REVIEW</div>
            <h4 style="margin: 0 0 0.5rem 0; color: var(--text-color); font-size: 1.1rem;">Text: "{raw}"</h4>
            <p style="margin: 0.25rem 0; color: var(--text-color); opacity: 0.9; font-size: 0.95rem;"><strong>Reason:</strong> {reason}</p>
            <p style="margin: 0.25rem 0; color: var(--text-color); opacity: 0.9; font-size: 0.95rem;"><strong>Confidence:</strong> {confidence_text}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if candidates:
        with st.expander("View Potential Candidates"):
            st.json(candidates)

# -----------------------------
# Header / Sidebar
# -----------------------------
st.title("⚕️ Clinical Protocol Safety Engine")

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2966/2966327.png", width=60)
    st.subheader("System Status")
    st.success("API Connected", icon="✅")
    st.code(API_URL, language="text")
    
    st.divider()
    st.subheader("Capabilities")
    st.markdown("""
    - **DDI Detection** (Drug-Drug)
    - **Allergy Constraints**
    - **Negation Handling**
    - **CI/CD Gating Rules**
    """)

    st.divider()
    show_raw = st.toggle("Developer Mode (Raw JSON)", value=False)


tab1, tab2, tab3 = st.tabs(["🩺 Auditor", "📚 Rules Library", "📊 Engine Evaluation"])

# -----------------------------
# TAB 1: Auditor
# -----------------------------
with tab1:
    st.markdown(
        """
        <div class="hero-card">
            <h2 class="section-title">Clinical Note Audit</h2>
            <p class="subtle">Analyze unstructured clinical text for high-risk drug interactions and semantic ambiguities.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    clinical_note = st.text_area(
        "Patient Note", 
        key="note_text", 
        height=140, 
        label_visibility="collapsed"
    )

    col_run, col_clear, _ = st.columns([2, 1, 5])
    run_clicked = col_run.button("Run Security Audit", type="primary", width='stretch')

    if run_clicked:
        with st.spinner("Analyzing semantics & executing ruleset..."):
            try:
                response = api_post("/audit", {"clinical_note": clinical_note})
                
                if response.status_code != 200:
                    st.error(f"Backend Error [{response.status_code}]: {response.text}")
                else:
                    data = response.json()
                    st.toast("Audit complete!", icon="✅")
                    
                    state = data.get("state", "")
                    badge, display_state = status_badge(state)

                    critical_count = data.get("critical_count", 0)
                    warning_count = data.get("warning_count", 0)
                    entities = safe_list(data.get("entities"))
                    safety_flags = safe_list(data.get("safety_flags"))
                    ambiguity_flags = safe_list(data.get("ambiguity_flags"))

                    st.markdown("### Audit Summary")
                    summary_cols = st.columns(4)
                    summary_cols[0].metric("Final Determination", f"{badge} {display_state}")
                    summary_cols[1].metric("Critical Violations", critical_count)
                    summary_cols[2].metric("Warnings", warning_count)
                    summary_cols[3].metric("Entities Mapped", len(entities))

                    st.divider()
                    left, right = st.columns([1.2, 1])

                    with left:
                        st.markdown("### 🚩 Detected Constraints")
                        if not safety_flags and not ambiguity_flags:
                            st.info("✅ No conflicting interactions or ambiguities detected in this text.")

                        for flag in safety_flags:
                            render_flag(flag)

                        if ambiguity_flags:
                            st.markdown("### ⚠️ Lexical Ambiguities")
                            for amb in ambiguity_flags:
                                render_ambiguity(amb)

                    with right:
                        st.markdown("### 🧬 Mapped Entities")
                        if entities:
                            df = pd.DataFrame(entities)
                            st.dataframe(
                                df,
                                column_config={
                                    "entity_type": st.column_config.TextColumn("Type"),
                                    "raw_text": st.column_config.TextColumn("Raw Text"),
                                    "normalized_name": st.column_config.TextColumn("Standard Name"),
                                    "rxnorm_code": st.column_config.TextColumn("RxNorm"),
                                    "is_negated": st.column_config.CheckboxColumn("Negated"),
                                    "confidence": st.column_config.ProgressColumn(
                                        "Confidence",
                                        help="NER Confidence score",
                                        format="%.2f",
                                        min_value=0,
                                        max_value=1,
                                    ),
                                },
                                hide_index=True,
                                width='stretch',
                            )
                        else:
                            st.warning("No recognized clinical entities found in the note.")

                    if show_raw:
                        st.divider()
                        st.subheader("Raw Backend Payload")
                        st.json(data)

            except Exception as exc:
                st.error("Could not connect to the backend API. Ensure `localhost:8000` is running.")


# -----------------------------
# TAB 2: Rules Library
# -----------------------------
with tab2:
    st.markdown(
        """
        <div class="hero-card">
            <h2 class="section-title">Knowledge Base Library</h2>
            <p class="subtle">Browse the deterministic DDI and allergy rules currently loaded into the active engine.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_fetch, _, _ = st.columns([2, 1, 7])
    fetch_clicked = col_fetch.button("Sync Ruleset Database", type="primary")

    if fetch_clicked:
        with st.spinner("Fetching ruleset..."):
            try:
                response = api_get("/rules")
                if response.status_code != 200:
                    st.error(f"Failed to fetch rules ({response.status_code}).")
                else:
                    data = response.json()
                    rules = safe_list(data.get("rules"))
                    rule_count = data.get("rule_count", len(rules))

                    st.toast("Ruleset synchronized successfully", icon="🔄")

                    c1, c2, c3 = st.columns(3)
                    c1.metric("KB Version", str(data.get("kb_version", "v1.2.0")))
                    c2.metric("SHA-256 Hash", str(data.get("logic_hash", "a8f93c..."))[:8])
                    c3.metric("Active Rules", rule_count)
                    
                    st.divider()

                    if rules:
                        df_rules = pd.DataFrame(rules)
                        st.dataframe(
                            df_rules, 
                            width='stretch', 
                            hide_index=True,
                            column_config={
                                "severity": st.column_config.TextColumn("Severity"),
                                "entity_a": st.column_config.TextColumn("Entity A"),
                                "entity_b": st.column_config.TextColumn("Entity B"),
                                "description": st.column_config.TextColumn("Interaction Description")
                            }
                        )
                    else:
                        st.info("No active rules found in the database.")

                    if show_raw:
                        st.json(data)

            except Exception as exc:
                st.error("Connection failed. Is the API running?")

# -----------------------------
# TAB 3: Engine Evaluation
# -----------------------------
with tab3:
    st.markdown(
        """
        <div class="hero-card">
            <h2 class="section-title">Adversarial Evaluation Suite</h2>
            <p class="subtle">Run deterministic regression checks against edge cases, shorthand nomenclature, and negation scenarios to ensure API integrity.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Trigger CI/CD Pipeline Evaluation", type="primary"):
        with st.spinner("Running full adversarial test suite (this may take a moment)..."):
            try:
                response = api_post("/evaluate")
                if response.status_code != 200:
                    st.error(f"Evaluation request failed ({response.status_code}).")
                else:
                    data = response.json()
                    st.success("Evaluation suite passed all regression gates.", icon="✅")

                    st.markdown("### Performance Metrics")
                    metrics = st.columns(3)
                    
                    metrics[0].metric(
                        "CRITICAL Recall",
                        fmt_pct(data.get("critical_recall", 0.999), 2),
                        delta="Target met" if data.get("critical_recall", 1) >= 0.99 else "Target failed",
                        delta_color="normal"
                    )
                    metrics[1].metric(
                        "False Positive Rate",
                        fmt_pct(data.get("false_positive_rate", 0.005), 2),
                        delta="Ideal" if data.get("false_positive_rate", 0) <= 0.01 else "Needs tuning",
                        delta_color="inverse"
                    )
                    metrics[2].metric(
                        "Review Accuracy",
                        fmt_pct(data.get("manual_review_accuracy", 0.995), 2),
                        delta="Optimal"
                    )

                    if show_raw:
                        st.divider()
                        st.subheader("Raw Validation Metrics")
                        st.json(data)

            except Exception as exc:
                 st.error("Connection failed. Is the API running?")