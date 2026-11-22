from __future__ import annotations

import base64
import html
from pathlib import Path
from typing import Any
import streamlit as st

from config import SAMPLES_DIR
from models.domain import ApprovalStatus, ControllerOverride, DecisionRecord, Disposition
from persistence.store import AuditStore


def _get_attr(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    extra = getattr(obj, "model_extra", None) or {}
    for name in names:
        if hasattr(obj, name):
            val = getattr(obj, name)
            if val is not None:
                return val
        if isinstance(extra, dict) and name in extra and extra[name] is not None:
            return extra[name]
    return default


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _disp_matches(disp: Disposition, *candidates: str) -> bool:
    name_upper = disp.name.upper()
    val_upper = str(disp.value).upper()
    targets = {c.upper() for c in candidates}
    return name_upper in targets or val_upper in targets


def _is_clear(disp: Disposition) -> bool:
    return _disp_matches(disp, "CLEAR", "APPROVE", "APPROVED", "AUTO_CLEAR")


def _is_blocked(disp: Disposition) -> bool:
    return _disp_matches(disp, "BLOCK", "BLOCKED", "REJECT", "REJECTED", "DENY", "DENIED")


def _safe_text(val: Any) -> str:
    if val is None or val == "":
        return ""
    return html.escape(str(val).replace("$", "&#36;"))


def _finding_code(finding: Any) -> str:
    val = _get_attr(finding, "code", "rule_code", "rule_id", "id", default="POLICY")
    return str(val).upper()


def _plain_language_finding(
    finding: Any,
    subtotal: float | None,
    tax_amt: float | None,
    tip_amt: float | None,
    disc_amt: float | None,
    total_amt: float | None,
    currency_str: str,
) -> tuple[str, str, str]:
    code = _finding_code(finding)
    raw_msg = str(
        _get_attr(
            finding,
            "message",
            "description",
            "detail",
            "details",
            "reason",
            "explanation",
            "summary",
            "title",
            "name",
            default="",
        )
        or ""
    ).strip()

    calc_note = ""
    if subtotal is not None and total_amt is not None and code.startswith("MATH"):
        calc_sum = (
            subtotal
            + (tax_amt or 0.0)
            + (tip_amt or 0.0)
            - (disc_amt or 0.0)
        )
        cur = _safe_text(currency_str)
        calc_note = (
            f"Line items add up to <strong>{cur} {calc_sum:,.2f}</strong>, "
            f"whereas the receipt total shows <strong>{cur} {total_amt:,.2f}</strong>."
        )

    if code.startswith("MATH"):
        headline = "Receipt total doesn't match line items"
        plain = (
            raw_msg
            if raw_msg and not raw_msg.startswith("{")
            else "The individual amounts on this receipt do not add up cleanly to the final total. Double-check taxes, tips, or discounts before reimbursing."
        )
        return headline, plain, calc_note

    if code.startswith("DUP"):
        headline = "Possible duplicate receipt or expense"
        plain = (
            raw_msg
            if raw_msg and not raw_msg.startswith("{")
            else "A matching receipt or similar expense (same merchant, date, or amount) already appears in the records. Confirm this isn't being submitted twice."
        )
        return headline, plain, ""

    if code.startswith("FX"):
        headline = "Foreign currency converted for policy check"
        plain = (
            raw_msg
            if raw_msg and not raw_msg.startswith("{")
            else "This expense was billed in a foreign currency and converted to USD to check spend limits."
        )
        return headline, plain, ""

    if code.startswith("POL"):
        headline = "Outside standard spend or receipt policy"
        plain = (
            raw_msg
            if raw_msg and not raw_msg.startswith("{")
            else "This claim triggered a company policy check—such as a role/category spend limit or missing receipt details."
        )
        return headline, plain, ""

    headline = "Needs a quick controller check"
    plain = (
        raw_msg
        if raw_msg and not raw_msg.startswith("{")
        else "Something on this expense needs a human look before final approval."
    )
    return headline, plain, ""


def _resolve_receipt_bytes(
    record: DecisionRecord,
    uploaded_bytes_cache: dict[str, bytes],
) -> tuple[bytes | None, str]:
    if record.expense_id in uploaded_bytes_cache:
        return uploaded_bytes_cache[record.expense_id], record.file_name

    file_path = getattr(record, "file_path", None)
    if file_path:
        p = Path(file_path)
        if p.exists() and p.is_file():
            return p.read_bytes(), p.name

    sample_path = SAMPLES_DIR / record.file_name
    if sample_path.exists() and sample_path.is_file():
        return sample_path.read_bytes(), sample_path.name

    return None, record.file_name


def _render_pdf_preview(pdf_bytes: bytes, file_name: str, expense_id: str) -> None:
    if hasattr(st, "pdf"):
        try:
            st.pdf(pdf_bytes, height=440, key=f"pdf_viewer_{expense_id}")
        except Exception:
            pass
    else:
        rendered_page = False
        try:
            import pypdfium2 as pdfium  # type: ignore

            pdf = pdfium.PdfDocument(pdf_bytes)
            if len(pdf) > 0:
                page = pdf[0]
                bitmap = page.render(scale=1.5)
                pil_img = bitmap.to_pil()
                st.image(
                    pil_img,
                    caption=f"{file_name} (Page 1 of {len(pdf)})",
                    width="stretch",
                )
                rendered_page = True
        except Exception:
            rendered_page = False

        if not rendered_page:
            b64_pdf = base64.b64encode(pdf_bytes).decode("ascii")
            st.markdown(
                f'<iframe src="data:application/pdf;base64,{b64_pdf}" '
                f'width="100%" height="420px" '
                f'style="border:1px solid #cbd5e1;border-radius:8px;background:#ffffff;"></iframe>',
                unsafe_allow_html=True,
            )

    st.download_button(
        label=f"Download {file_name}",
        data=pdf_bytes,
        file_name=file_name,
        mime="application/pdf",
        key=f"download_pdf_{expense_id}",
        width="stretch",
    )


def render_expense_detail(
    record: DecisionRecord,
    store: AuditStore,
    uploaded_bytes_cache: dict[str, bytes],
) -> None:
    ext = record.extraction
    merchant_raw = _get_attr(
        ext, "merchant_name", "merchant", "vendor_name", "vendor", default=record.file_name
    )
    merchant = _safe_text(merchant_raw)
    emp_id = _safe_text(record.employee_id)
    emp_role = _safe_text(record.employee_role)
    exp_id = _safe_text(record.expense_id)

    subtotal = _to_float(_get_attr(ext, "subtotal", "sub_total", default=None))
    tax_amt = _to_float(_get_attr(ext, "tax_amount", "tax", default=None))
    tip_amt = _to_float(_get_attr(ext, "tip_amount", "tip", default=None))
    disc_amt = _to_float(_get_attr(ext, "discount_amount", "discount", default=None))
    total_amt = _to_float(
        _get_attr(
            ext,
            "total_amount",
            "total",
            "amount",
            "grand_total",
            "receipt_total",
            default=None,
        )
    )
    currency_str = str(_get_attr(ext, "currency", "currency_code", default="USD") or "USD")
    converted_usd = _to_float(_get_attr(record, "converted_amount_usd", "amount_usd", default=None))
    anomaly_score = _to_float(_get_attr(record, "anomaly_score", "risk_score", default=None))

    with st.container(border=True):
        h_left, h_right = st.columns([3.8, 1.4])
        with h_left:
            st.markdown(
                f'<div style="font-size:1.35rem;font-weight:700;color:#0f172a;">{merchant}</div>'
                f'<div style="font-size:0.84rem;color:#64748b;margin-top:2px;">'
                f"Expense <strong>{exp_id}</strong> · Submitted by <strong>{emp_id}</strong> ({emp_role})"
                f"</div>",
                unsafe_allow_html=True,
            )
        with h_right:
            if _is_blocked(record.disposition):
                disp_cls = "cl-badge-err"
            elif _is_clear(record.disposition):
                disp_cls = "cl-badge-ok"
            else:
                disp_cls = "cl-badge-warn"
            st.markdown(
                f'<div style="text-align:right;padding-top:4px;">'
                f'<span class="cl-badge {disp_cls}">● {_safe_text(record.disposition.value)}</span>'
                f"</div>",
                unsafe_allow_html=True,
            )

        st.divider()

        # Receipt preview + Review findings side by side
        left_pane, right_pane = st.columns([1.0, 1.25], gap="large")

        with left_pane:
            st.markdown("#### Receipt preview")
            raw_bytes, resolved_name = _resolve_receipt_bytes(record, uploaded_bytes_cache)
            lower_name = (resolved_name or record.file_name or "").lower()
            is_pdf = lower_name.endswith(".pdf") or (
                raw_bytes is not None and raw_bytes.startswith(b"%PDF-")
            )

            if raw_bytes and is_pdf:
                _render_pdf_preview(raw_bytes, resolved_name or record.file_name, record.expense_id)
            elif raw_bytes:
                st.image(raw_bytes, caption=resolved_name, width="stretch")
            else:
                st.info("Receipt preview unavailable for this seeded record.")

        with right_pane:
            st.markdown("#### Review findings")
            st.caption("Plain-English summary of what Clearline flagged on this expense.")

            if record.findings:
                primary = record.findings[0]
                p_code = _finding_code(primary)
                headline, plain_msg, calc_note = _plain_language_finding(
                    primary, subtotal, tax_amt, tip_amt, disc_amt, total_amt, currency_str
                )
                sev_obj = _get_attr(primary, "severity", "level", default="REVIEW")
                sev_raw = str(getattr(sev_obj, "value", sev_obj)).upper()
                is_high = sev_raw in ("HIGH", "BLOCK", "ERROR", "CRITICAL")
                sev_label = "Needs close look" if is_high else "Worth checking"
                sev_badge = (
                    f'<span class="cl-badge cl-badge-err">● {_safe_text(sev_label)}</span>'
                    if is_high
                    else f'<span class="cl-badge cl-badge-warn">● {_safe_text(sev_label)}</span>'
                )
                calc_html = (
                    f'<div class="cl-formula-strip">{calc_note}</div>' if calc_note else ""
                )

                st.markdown(
                    f'<div class="cl-finding-card">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;">'
                    f'<span style="font-weight:700;font-size:0.98rem;color:#0f172a;">{_safe_text(headline)}</span>'
                    f"{sev_badge}"
                    f"</div>"
                    f'<div style="font-size:0.9rem;line-height:1.45;color:#1e293b;">{_safe_text(plain_msg)}</div>'
                    f'<div style="font-size:0.76rem;color:#64748b;margin-top:6px;">Rule reference: {_safe_text(p_code)}</div>'
                    f"{calc_html}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                for extra in record.findings[1:]:
                    e_code = _finding_code(extra)
                    e_head, e_plain, _ = _plain_language_finding(
                        extra, subtotal, tax_amt, tip_amt, disc_amt, total_amt, currency_str
                    )
                    st.markdown(
                        f"- **{_safe_text(e_head)}** (`{_safe_text(e_code)}`): {_safe_text(e_plain)}",
                        unsafe_allow_html=True,
                    )
            else:
                st.success("Everything looks clean—no policy, math, or duplicate issues found.")

            follow_up = _get_attr(record, "follow_up_draft", "follow_up", "chaser_draft", default=None)
            if follow_up:
                st.markdown("#### Recommended follow-up")
                st.markdown(
                    f'<div class="cl-action-banner">{_safe_text(follow_up)}</div>',
                    unsafe_allow_html=True,
                )

        st.divider()

        # Full-width Checks section (matches Technical details width)
        st.markdown("#### Checks")
        st.caption("Detailed check results across receipt reading, policy rules, duplicates, math, and currency.")

        finding_codes = [_finding_code(f) for f in record.findings]
        has_pol = any(c.startswith("POL") for c in finding_codes)
        has_dup = any(c.startswith("DUP") for c in finding_codes)
        has_math = any(c.startswith("MATH") for c in finding_codes)
        has_fx = any(c.startswith("FX") for c in finding_codes)

        read_detail = (
            f"Read total {currency_str} {total_amt:,.2f} on {merchant_raw}."
            if total_amt is not None
            else "Could not verify a printed total on this receipt."
        )
        pol_detail = (
            "Flagged against spend or policy limits."
            if has_pol
            else ("Minor review item noted." if finding_codes else "Within standard policy limits.")
        )
        dup_detail = (
            "Matched an existing receipt or prior submission."
            if has_dup
            else "No matching prior submission found."
        )
        math_detail = (
            "Line items and total do not reconcile."
            if has_math
            else (
                "Line items reconcile with total."
                if subtotal is not None and total_amt is not None
                else "No line-item breakdown to compare."
            )
        )

        checks = [
            (
                "Receipt details read",
                "OK" if total_amt is not None else "CHECK",
                read_detail,
            ),
            (
                "Spend & policy rules",
                "ISSUE" if has_pol else ("REVIEW" if finding_codes else "PASSED"),
                pol_detail,
            ),
            (
                "Duplicate check",
                "POSSIBLE DUP" if has_dup else "NO DUP",
                dup_detail,
            ),
            (
                "Totals & math check",
                "MISMATCH" if has_math else "MATCHES",
                math_detail,
            ),
        ]

        chk_cols = st.columns(2)
        for idx, (lbl, status_txt, detail_txt) in enumerate(checks):
            with chk_cols[idx % 2]:
                if status_txt in ("MISMATCH", "ISSUE"):
                    cls = "cl-badge-err"
                elif status_txt in ("CHECK", "REVIEW", "POSSIBLE DUP"):
                    cls = "cl-badge-warn"
                else:
                    cls = "cl-badge-ok"
                st.markdown(
                    f'<div style="padding:10px 12px;border:1px solid #e2e8f0;border-radius:10px;'
                    f'margin-bottom:10px;background:#f8fafc;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">'
                    f'<span style="font-size:0.86rem;font-weight:600;color:#0f172a;">{_safe_text(lbl)}</span>'
                    f'<span class="cl-badge {cls}">{_safe_text(status_txt)}</span>'
                    f"</div>"
                    f'<div style="font-size:0.78rem;color:#475569;margin-top:5px;line-height:1.35;">'
                    f"{_safe_text(detail_txt)}"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        if converted_usd is not None or has_fx or currency_str.upper() != "USD":
            fx_parts = [f"Currency: <strong>{_safe_text(currency_str.upper())}</strong>"]
            if total_amt is not None:
                fx_parts.append(f"Original: <strong>{total_amt:,.2f}</strong>")
            if converted_usd is not None:
                fx_parts.append(f"USD equivalent: <strong>&#36;{converted_usd:,.2f}</strong>")
            st.markdown(
                f'<div class="cl-formula-strip" style="margin-top:0;margin-bottom:10px;">'
                f'<strong>Currency &amp; FX Check:</strong> {" · ".join(fx_parts)}'
                f"</div>",
                unsafe_allow_html=True,
            )

        st.divider()

        # Full-width Controller decision section (matches Technical details width)
        st.markdown("#### Controller decision")
        st.caption("Review the current decision state, choose a new status if needed, and save a required audit note.")

        current_app_val = str(
            getattr(record.approval_status, "value", record.approval_status)
        )
        risk_part = (
            f" · Risk score: <strong>{anomaly_score:.2f}</strong>"
            if anomaly_score is not None
            else ""
        )
        st.markdown(
            f'<div class="cl-formula-strip" style="margin-top:0;margin-bottom:12px;">'
            f"<strong>Current state:</strong> Queue status <strong>{_safe_text(record.disposition.value)}</strong>"
            f" · Approval <strong>{_safe_text(current_app_val)}</strong>{risk_part}"
            f"</div>",
            unsafe_allow_html=True,
        )

        disp_options = [d.value for d in Disposition]
        cur_disp_idx = (
            disp_options.index(record.disposition.value)
            if record.disposition.value in disp_options
            else 0
        )

        app_options = [a.value for a in ApprovalStatus]
        cur_app_idx = (
            app_options.index(record.approval_status.value)
            if record.approval_status.value in app_options
            else 0
        )

        with st.form(key=f"controller_decision_form_{record.expense_id}"):
            f_c1, f_c2 = st.columns(2)
            with f_c1:
                new_disp_val = st.selectbox(
                    "Queue status",
                    options=disp_options,
                    index=cur_disp_idx,
                    key=f"disp_select_{record.expense_id}",
                )
            with f_c2:
                new_app_val = st.selectbox(
                    "Approval decision",
                    options=app_options,
                    index=cur_app_idx,
                    key=f"app_select_{record.expense_id}",
                )

            reason_txt = st.text_input(
                "Audit note (required)",
                placeholder="Briefly note why you are approving, holding, or blocking this expense...",
                key=f"reason_input_{record.expense_id}",
            )

            saved = st.form_submit_button("Save decision", type="primary")
            if saved:
                if not reason_txt.strip():
                    st.error("Please enter a short audit note before saving your decision.")
                else:
                    override = ControllerOverride(
                        expense_id=record.expense_id,
                        controller_id="CTRL-01",
                        previous_disposition=record.disposition,
                        new_disposition=Disposition(new_disp_val),
                        new_approval_status=ApprovalStatus(new_app_val),
                        reason=reason_txt.strip(),
                    )
                    store.record_override(override)
                    st.toast("Decision saved to Audit Log.")
                    st.rerun()

        overrides = store.list_overrides(record.expense_id)
        if overrides:
            st.markdown("**Decision history**")
            for ov in overrides:
                st.markdown(
                    f'<div class="cl-formula-strip" style="margin-top:4px;margin-bottom:6px;">'
                    f"<strong>{_safe_text(ov['controller_id'])}</strong> · {_safe_text(ov['overridden_at'])}<br/>"
                    f"Status: <strong>{_safe_text(ov['previous_disposition'])}</strong> → "
                    f"<strong>{_safe_text(ov['new_disposition'])}</strong> "
                    f"({_safe_text(ov['new_approval_status'])})<br/>"
                    f"Note: {_safe_text(ov['reason'])}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        with st.expander("Technical details"):
            st.json(record.model_dump(mode="json"))