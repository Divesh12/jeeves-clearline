from __future__ import annotations

import io
from pathlib import Path
import streamlit as st
from PIL import Image

from config import config
from models.domain import (
    ApprovalStatus,
    ControllerOverride,
    DecisionRecord,
    Disposition,
)
from persistence.store import AuditStore


def _render_receipt_preview(rec: DecisionRecord, uploaded_bytes_cache: dict[str, bytes]) -> None:
    raw_bytes = uploaded_bytes_cache.get(rec.expense_id)
    sample_candidate = config.SAMPLES_DIR / rec.file_name

    if raw_bytes is None and sample_candidate.exists():
        raw_bytes = sample_candidate.read_bytes()

    if not raw_bytes:
        st.caption(f"File: `{rec.file_name}` (SHA-256: `{rec.file_sha256[:12]}...`)")
        return

    lower_name = rec.file_name.lower()
    if lower_name.endswith((".png", ".jpg", ".jpeg")):
        try:
            img = Image.open(io.BytesIO(raw_bytes))
            st.image(img, caption=f"{rec.file_name} (Best-effort card/text PII rules applied)", use_container_width=True)
        except Exception:
            st.caption(f"Image preview unavailable for `{rec.file_name}`.")
    else:
        st.caption(f"Document: `{rec.file_name}` ({len(raw_bytes)} bytes, SHA-256: `{rec.file_sha256[:12]}...`)")


def render_expense_detail(
    rec: DecisionRecord,
    store: AuditStore,
    uploaded_bytes_cache: dict[str, bytes],
) -> None:
    st.subheader(f"Investigation: {rec.expense_id}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Engine Disposition", rec.disposition.value)
    m2.metric("Approval Status", rec.approval_status.value)
    m3.metric("Anomaly Score", f"{rec.anomaly_score:.1f}/100")
    m4.metric("Policy Version", rec.policy_version)

    st.write(rec.summary)
    st.caption(
        f"Mode: `{rec.mode_used}` | Source: `{rec.extraction.extraction_source}` | "
        f"Employee: `{rec.employee_id}` ({rec.employee_role})"
    )

    left_col, right_col = st.columns([1.0, 1.3])

    with left_col:
        _render_receipt_preview(rec, uploaded_bytes_cache)

        st.markdown("#### Extracted Fields & Confidence")
        ext = rec.extraction
        st.write(f"**Merchant:** {ext.merchant_name or 'Missing'} (conf: {ext.merchant_confidence:.2f})")
        st.write(f"**Date:** {ext.expense_date or 'Missing'} (conf: {ext.date_confidence:.2f})")
        st.write(f"**Currency:** {ext.currency or 'Missing'} (conf: {ext.currency_confidence:.2f})")
        st.write(f"**Total:** {ext.total if ext.total is not None else 'Missing'} (conf: {ext.total_confidence:.2f})")
        if ext.subtotal is not None or ext.tax is not None or ext.tip is not None or ext.discount is not None:
            st.caption(
                f"Subtotal: {ext.subtotal} | Tax: {ext.tax} | Tip: {ext.tip} | Discount: {ext.discount}"
            )
        if rec.conversion:
            st.caption(
                f"FX: {rec.conversion.original_amount} {rec.conversion.original_currency} "
                f"-> ${rec.conversion.converted_amount} USD @ {rec.conversion.fx_rate} "
                f"({rec.conversion.fx_rate_date}, {rec.conversion.fx_source})"
            )
        st.caption(rec.anomaly_note)

    with right_col:
        st.markdown("#### Deterministic Findings & Evidence")
        if not rec.findings:
            st.success("No policy violations, arithmetic discrepancies, or duplicate/split flags detected.")
        else:
            for f in rec.findings:
                with st.container(border=True):
                    st.markdown(f"**[{f.rule_id}] {f.title}** — `{f.severity.value}` -> `{f.disposition_impact.value}`")
                    st.write(f"**Observed:** {f.observed} | **Expected:** {f.expected}")
                    st.caption(f.evidence)

        if rec.chaser_draft:
            st.markdown("#### Suggested Employee Follow-Up Draft (Not Sent Automatically)")
            st.text_area("Draft message", value=rec.chaser_draft, height=85, key=f"chaser_{rec.expense_id}")

        st.markdown("#### Controller Override (Requires Reason)")
        with st.form(key=f"override_form_{rec.expense_id}"):
            new_disp = st.selectbox(
                "Controller Disposition",
                options=[d.value for d in Disposition],
                index=[d.value for d in Disposition].index(rec.disposition.value),
            )
            new_appr = st.selectbox(
                "Approval Status",
                options=[a.value for a in ApprovalStatus],
                index=[a.value for a in ApprovalStatus].index(rec.approval_status.value),
            )
            controller_id = st.text_input("Controller ID", value="CTRL-01")
            reason = st.text_input("Override Reason (mandatory)", placeholder="e.g., Client meeting verified; receipt confirmed.")
            submitted = st.form_submit_button("Record Controller Decision")

            if submitted:
                if not reason.strip():
                    st.error("A non-empty reason is required to record a controller override.")
                else:
                    ov = ControllerOverride(
                        expense_id=rec.expense_id,
                        previous_disposition=rec.disposition,
                        new_disposition=Disposition(new_disp),
                        new_approval_status=ApprovalStatus(new_appr),
                        controller_id=controller_id.strip() or "CTRL-01",
                        reason=reason.strip(),
                    )
                    store.record_override(ov)
                    st.success("Controller decision recorded in immutable audit log.")
                    st.rerun()

        overrides = store.list_overrides(rec.expense_id)
        if overrides:
            st.markdown("#### Controller Override Audit Trail")
            for item in overrides:
                st.caption(
                    f"`{item['overridden_at']}` by `{item['controller_id']}`: "
                    f"{item['previous_disposition']} -> **{item['new_disposition']}** "
                    f"(Approval: `{item['new_approval_status']}`) — *\"{item['reason']}\"* "
                    f"[Original engine verdict preserved in record]"
                )

    with st.expander("Raw Structured Audit Record (JSON)"):
        st.json(rec.model_dump(mode="json"))