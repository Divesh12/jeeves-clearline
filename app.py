from __future__ import annotations

import streamlit as st

from config import config
from persistence.store import AuditStore
from services.pipeline import run_expense_pipeline
from ui.detail_view import render_expense_detail
from ui.queue_view import render_expense_queue, render_kpi_strip


@st.cache_resource
def get_store() -> AuditStore:
    store = AuditStore(config.DB_FILE)
    store.seed_baseline_from_csv(config.LEDGER_FILE)
    return store


def main() -> None:
    st.set_page_config(
        page_title="Clearline — Exception-First Expense Review",
        layout="wide",
    )

    store = get_store()
    if "uploaded_bytes_cache" not in st.session_state:
        st.session_state.uploaded_bytes_cache = {}
    if "selected_expense_id" not in st.session_state:
        st.session_state.selected_expense_id = None

    st.title("Clearline")
    st.caption(
        "Exception-first expense review for Finance Controllers: routine compliant expenses can clear "
        "automatically while exceptions surface with evidence, policy rules, and audit trails."
    )

    with st.sidebar:
        st.header("Processing & Privacy Controls")
        replay_mode = st.toggle(
            "Replay Mode (Deterministic Demo Fixtures)",
            value=False,
            help="Uses pre-recorded sample extractions for reproducible offline/video demos. Clearly labeled.",
        )
        use_external_ai = st.toggle(
            "External AI Processing Enabled (Gemini)",
            value=bool(config.gemini_api_key),
            disabled=replay_mode,
            help="When enabled, receipt bytes are sent to Gemini for structured extraction. When disabled, routes safely to manual review.",
        )

        st.markdown("---")
        st.caption(
            f"**Model:** `{config.gemini_model}` | **Policy:** `{config.active_policy_version}`\n\n"
            "**Privacy Note:** SHA-256 hashes are for integrity and exact-duplicate checks only (not encryption). "
            "Text/card masking is best-effort; external AI calls transmit receipt data when enabled."
        )

        if st.button("Seed Baseline Ledger", use_container_width=True):
            added = store.seed_baseline_from_csv(config.LEDGER_FILE)
            st.success(f"Baseline ledger ready ({added} new rows inserted).")

    records = store.list_decisions()
    render_kpi_strip(records)

    st.markdown("---")
    st.subheader("Submit Expense for Review")

    with st.container(border=True):
        u_col1, u_col2, u_col3 = st.columns([2, 1, 1])
        with u_col1:
            uploaded_file = st.file_uploader(
                "Upload receipt (PDF, PNG, JPG, JPEG — max 10 MB, up to 5 PDF pages)",
                type=["pdf", "png", "jpg", "jpeg"],
            )
        with u_col2:
            employee_id = st.text_input("Employee ID", value="E104")
        with u_col3:
            employee_role = st.text_input("Role", value="Account Executive")

        if st.button("Run Policy & Risk Review", type="primary"):
            if uploaded_file is None:
                st.warning("Please upload a receipt file first.")
            else:
                file_bytes = uploaded_file.getvalue()
                with st.spinner("Running intake, extraction, deterministic validation, policy & risk checks..."):
                    decision = run_expense_pipeline(
                        store=store,
                        file_name=uploaded_file.name,
                        file_bytes=file_bytes,
                        employee_id=employee_id,
                        employee_role=employee_role,
                        use_external_ai=use_external_ai,
                        replay_mode=replay_mode,
                    )
                st.session_state.uploaded_bytes_cache[decision.expense_id] = file_bytes
                st.session_state.selected_expense_id = decision.expense_id
                st.rerun()

    st.markdown("---")
    q_col, d_col = st.columns([1.05, 1.35])

    with q_col:
        chosen = render_expense_queue(records, st.session_state.selected_expense_id)
        if chosen:
            st.session_state.selected_expense_id = chosen

    with d_col:
        current_records = store.list_decisions()
        target_id = st.session_state.selected_expense_id or (current_records[0].expense_id if current_records else None)
        selected_rec = next((r for r in current_records if r.expense_id == target_id), None)
        if selected_rec:
            render_expense_detail(selected_rec, store, st.session_state.uploaded_bytes_cache)
        else:
            st.info("Select an expense from the queue to inspect its evidence and audit trail.")


if __name__ == "__main__":
    main()