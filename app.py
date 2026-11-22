from __future__ import annotations

import hashlib
import html
from typing import Any
import streamlit as st

from config import DB_FILE, LEDGER_FILE, config
from persistence.store import AuditStore
from services.pipeline import run_expense_pipeline
from ui.detail_view import render_expense_detail
from ui.queue_view import render_expense_queue, render_kpi_strip
from ui.styles import apply_clearline_theme


def _get_merchant_label(record: Any) -> str:
    ext = getattr(record, "extraction", None)
    extra = getattr(ext, "model_extra", None) or {}
    for attr in ("merchant_name", "merchant", "vendor_name", "vendor"):
        if hasattr(ext, attr):
            val = getattr(ext, attr)
            if val:
                return str(val)
        if isinstance(extra, dict) and extra.get(attr):
            return str(extra[attr])
    return record.file_name


@st.cache_resource
def get_store() -> AuditStore:
    store = AuditStore(DB_FILE)
    store.seed_baseline_from_csv(LEDGER_FILE)
    return store


def _render_audit_log_tab(store: AuditStore, records: list) -> None:
    st.markdown("### Audit Log")
    st.caption("Controller decisions and notes recorded locally in SQLite.")

    rows = []
    for r in records:
        for ov in store.list_overrides(r.expense_id):
            rows.append(
                {
                    "Expense ID": r.expense_id,
                    "Employee": r.employee_id,
                    "Merchant": _get_merchant_label(r),
                    "Previous Status": ov["previous_disposition"],
                    "New Status": ov["new_disposition"],
                    "Approval": ov["new_approval_status"],
                    "Reviewer": ov["controller_id"],
                    "Note": ov["reason"],
                    "Saved At": ov["overridden_at"],
                }
            )

    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info(
            "No controller decisions saved yet. Choose a status and audit note on any expense to record it here."
        )


def _render_policy_rules_tab() -> None:
    st.markdown("### Policy Rules")
    st.caption(f"Active policy version: `{config.active_policy_version}`")

    rules = [
        (
            "MATH-001",
            "Receipt Totals & Math Check",
            "Checks whether line items, tax, tip, and discounts match the total printed on the receipt.",
        ),
        (
            "DUP-001",
            "Duplicate Expense Check",
            "Flags repeated receipt uploads or matching merchant, date, and amount entries.",
        ),
        (
            "FX-001",
            "Currency Conversion",
            "Converts foreign-currency receipts into USD so spend limits apply consistently.",
        ),
        (
            "POL-001",
            "Spend & Policy Limits",
            "Checks role/category spend limits, required receipt fields, and unusual patterns.",
        ),
    ]
    for code, name, desc in rules:
        with st.container(border=True):
            st.markdown(f"**{name}** (`{code}`)")
            st.write(desc)


def main() -> None:
    st.set_page_config(
        page_title="Clearline — Spend Compliance Queue",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_clearline_theme()

    store = get_store()
    st.session_state.setdefault("uploaded_bytes_cache", {})
    st.session_state.setdefault("selected_expense_id", None)
    st.session_state.setdefault("is_running_review", False)
    st.session_state.setdefault("processed_hashes", set())
    st.session_state.setdefault("upload_validation_msg", None)

    with st.sidebar:
        st.markdown("## Clearline")
        st.caption("Corporate Spend & Policy Auditor")
        st.divider()

        st.markdown("**Processing mode**")
        replay_mode = st.toggle(
            "Replay Mode",
            value=False,
            help="Use offline sample fixtures without calling external AI.",
            key="sidebar_replay_mode",
        )
        st.caption(
            "Using offline sample fixtures."
            if replay_mode
            else "Using standard receipt pipeline."
        )

        use_external_ai = st.toggle(
            "External AI (Gemini)",
            value=bool(config.gemini_api_key),
            disabled=replay_mode,
            help="Extract receipt fields with Gemini when Replay Mode is off.",
            key="sidebar_external_ai",
        )
        if replay_mode:
            st.caption("Disabled while Replay Mode is on.")
        elif use_external_ai:
            st.caption("Gemini extraction enabled.")
        else:
            st.caption("Safe non-AI fallback active.")

        st.divider()
        if st.button("Seed Baseline Ledger", use_container_width=True, key="sidebar_seed_btn"):
            added = store.seed_baseline_from_csv(LEDGER_FILE)
            st.success(f"Seeded ({added} new rows).")

        st.divider()
        st.markdown(
            '<div class="cl-local-card">'
            "<strong>● Local Mode</strong><br/>"
            "All data stays on your machine."
            "</div>",
            unsafe_allow_html=True,
        )

    records = store.list_decisions()
    if st.session_state.selected_expense_id is None and records:
        st.session_state.selected_expense_id = records[0].expense_id

    head_l, head_r = st.columns([5.5, 1.5])
    with head_l:
        st.markdown("## Spend Compliance Queue")
        st.caption("Review flagged expenses in plain language, check policy results, and record your decision.")
    with head_r:
        mode_txt = "▶ Replay Mode" if replay_mode else "● Live Mode"
        badge_cls = "cl-badge-info" if replay_mode else "cl-badge-ok"
        st.markdown(
            f'<div style="display:flex;justify-content:flex-end;align-items:center;gap:8px;padding-top:8px;">'
            f'<span class="cl-badge {badge_cls}">{mode_txt}</span>'
            f'<span class="cl-badge cl-badge-tag">FC</span>'
            f"</div>",
            unsafe_allow_html=True,
        )

    render_kpi_strip(records)

    tab_review, tab_audit, tab_rules = st.tabs(["Expense Review", "Audit Log", "Policy Rules"])

    with tab_review:
        with st.expander("Submit expense for review", expanded=len(records) == 0):
            u1, u2, u3 = st.columns([2.6, 1.0, 1.0])
            with u2:
                employee_id = st.text_input(
                    "Employee ID",
                    value="",
                    placeholder="Enter Employee ID",
                    key="main_emp_id",
                    disabled=st.session_state.is_running_review,
                ).strip()
            with u3:
                employee_role = st.text_input(
                    "Role",
                    value="",
                    placeholder="Enter Role",
                    key="main_emp_role",
                    disabled=st.session_state.is_running_review,
                ).strip()
            with u1:
                uploaded_file = st.file_uploader(
                    "Receipt file (PDF, PNG, JPG, JPEG)",
                    type=["pdf", "png", "jpg", "jpeg"],
                    key="main_receipt_uploader",
                    disabled=st.session_state.is_running_review,
                )
                if uploaded_file is not None:
                    st.session_state.upload_validation_msg = None
                    safe_name = html.escape(uploaded_file.name)
                    raw_bytes = uploaded_file.getvalue()
                    file_hash = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else ""
                    norm_emp = employee_id.lower()

                    already_seen = False
                    if file_hash and norm_emp:
                        seen_key = (file_hash, norm_emp)
                        in_session = seen_key in st.session_state.processed_hashes
                        in_store = any(
                            bool(getattr(r, "file_sha256", None))
                            and str(getattr(r, "file_sha256")).strip().lower() == file_hash
                            and str(getattr(r, "employee_id", "")).strip().lower() == norm_emp
                            for r in records
                        )
                        already_seen = in_session or in_store

                    st.markdown(
                        f'<div style="margin-top:4px;font-size:0.85rem;font-weight:600;color:#0f172a;">'
                        f"Selected file: <code>{safe_name}</code> ({uploaded_file.size:,} bytes)"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    if already_seen:
                        st.info(
                            "This receipt was already processed for this employee. "
                            "Submitting again will run through the pipeline and be evaluated as a duplicate."
                        )

            if st.button(
                "Running Review..." if st.session_state.is_running_review else "Run Policy & Risk Review",
                type="primary",
                key="run_review_btn",
                disabled=st.session_state.is_running_review,
            ):
                if uploaded_file is None:
                    st.session_state.upload_validation_msg = "Please upload a receipt file first."
                    st.rerun()
                elif not employee_id:
                    st.session_state.upload_validation_msg = "Please enter an Employee ID."
                    st.rerun()
                elif not employee_role:
                    st.session_state.upload_validation_msg = "Please enter an Employee Role."
                    st.rerun()
                else:
                    st.session_state.upload_validation_msg = None
                    st.session_state.is_running_review = True
                    raw = uploaded_file.getvalue()
                    file_hash = hashlib.sha256(raw).hexdigest()
                    try:
                        with st.spinner("Running policy & risk checks..."):
                            dec = run_expense_pipeline(
                                store=store,
                                file_name=uploaded_file.name,
                                file_bytes=raw,
                                employee_id=employee_id,
                                employee_role=employee_role,
                                use_external_ai=use_external_ai,
                                replay_mode=replay_mode,
                            )
                        if file_hash and employee_id:
                            st.session_state.processed_hashes.add(
                                (file_hash, employee_id.lower())
                            )
                        st.session_state.uploaded_bytes_cache[dec.expense_id] = raw
                        st.session_state.selected_expense_id = dec.expense_id
                        st.toast(f"Receipt processed: {uploaded_file.name} ({dec.disposition.value})")
                    finally:
                        st.session_state.is_running_review = False
                    st.rerun()

            if st.session_state.upload_validation_msg:
                st.warning(st.session_state.upload_validation_msg)

        st.markdown("")
        q_col, d_col = st.columns([0.95, 1.55], gap="large")

        with q_col:
            render_expense_queue(records, st.session_state.selected_expense_id)

        with d_col:
            target_id = st.session_state.selected_expense_id
            selected_rec = next((r for r in records if r.expense_id == target_id), None)
            if selected_rec:
                render_expense_detail(selected_rec, store, st.session_state.uploaded_bytes_cache)
            else:
                st.info("No expenses in queue yet. Submit a receipt above to start reviewing.")

    with tab_audit:
        _render_audit_log_tab(store, records)

    with tab_rules:
        _render_policy_rules_tab()


if __name__ == "__main__":
    main()