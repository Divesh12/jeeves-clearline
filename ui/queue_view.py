from __future__ import annotations

import html
from typing import Any
import streamlit as st

from models.domain import DecisionRecord, Disposition


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


def _finding_code(finding: Any) -> str:
    val = _get_attr(finding, "code", "rule_code", "rule_id", "id", default="RULE")
    return str(val)


def _disp_matches(disp: Disposition, *candidates: str) -> bool:
    name_upper = disp.name.upper()
    val_upper = str(disp.value).upper()
    targets = {c.upper() for c in candidates}
    return name_upper in targets or val_upper in targets


def _is_clear(disp: Disposition) -> bool:
    return _disp_matches(disp, "CLEAR", "APPROVE", "APPROVED", "AUTO_CLEAR")


def _is_blocked(disp: Disposition) -> bool:
    return _disp_matches(disp, "BLOCK", "BLOCKED", "REJECT", "REJECTED", "DENY", "DENIED")


def _extract_merchant(ext: Any, fallback_name: str) -> str:
    val = _get_attr(ext, "merchant_name", "merchant", "vendor_name", "vendor", default=None)
    return str(val) if val else fallback_name


def _extract_total(ext: Any) -> float | None:
    val = _get_attr(
        ext,
        "total_amount",
        "total",
        "amount",
        "grand_total",
        "receipt_total",
        default=None,
    )
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _extract_currency(ext: Any) -> str:
    val = _get_attr(ext, "currency", "currency_code", default="USD")
    return str(val) if val else "USD"


def _fmt_currency(amount: float | None, currency: str | None) -> str:
    if amount is None:
        return "N/A"
    cur = (currency or "USD").strip().upper()
    if cur == "USD":
        return f"${amount:,.2f}"
    if cur == "INR":
        return f"₹{amount:,.2f}"
    if cur == "EUR":
        return f"€{amount:,.2f}"
    if cur == "GBP":
        return f"£{amount:,.2f}"
    return f"{cur} {amount:,.2f}"


def _disposition_badge(disp: Disposition) -> str:
    esc = html.escape(str(disp.value))
    if _is_blocked(disp):
        return f'<span class="cl-badge cl-badge-err">● {esc}</span>'
    if _is_clear(disp):
        return f'<span class="cl-badge cl-badge-ok">● {esc}</span>'
    return f'<span class="cl-badge cl-badge-warn">● {esc}</span>'


def render_kpi_strip(records: list[DecisionRecord]) -> None:
    total = len(records)
    cleared = sum(1 for r in records if _is_clear(r.disposition))
    blocked = sum(1 for r in records if _is_blocked(r.disposition))
    needs_review = sum(
        1 for r in records if not _is_clear(r.disposition) and not _is_blocked(r.disposition)
    )

    c1, c2, c3, c4 = st.columns(4)
    kpis = [
        (c1, "TOTAL EXPENSES", total, "#0f172a"),
        (c2, "CLEARED", cleared, "#15803d"),
        (c3, "NEEDS REVIEW", needs_review, "#b45309"),
        (c4, "BLOCKED", blocked, "#b91c1c"),
    ]
    for col, label, val, color in kpis:
        with col:
            with st.container(border=True):
                st.markdown(
                    f'<div style="font-size:0.72rem;font-weight:700;letter-spacing:0.06em;color:#475569;">{label}</div>'
                    f'<div style="font-size:1.75rem;font-weight:700;line-height:1.15;color:{color};margin-top:4px;">{val}</div>',
                    unsafe_allow_html=True,
                )


def render_expense_queue(
    records: list[DecisionRecord],
    selected_id: str | None,
) -> str | None:
    st.markdown("### Queue")
    st.caption("Prioritized items needing controller attention")

    search_q = (
        st.text_input(
            "Search expenses",
            placeholder="Search merchant, employee, or ID...",
            key="queue_search_input",
        )
        .strip()
        .lower()
    )

    f_col, s_col = st.columns(2)
    with f_col:
        filter_choice = st.selectbox(
            "Filter by status",
            options=["All exceptions", "Needs review", "Blocked", "Cleared", "All items"],
            index=0,
            key="queue_filter_select",
        )
    with s_col:
        sort_choice = st.selectbox(
            "Sort by",
            options=["Priority (default)", "Highest amount", "Highest risk"],
            index=0,
            key="queue_sort_select",
        )

    if filter_choice == "All exceptions":
        filtered = [r for r in records if not _is_clear(r.disposition)]
    elif filter_choice == "Needs review":
        filtered = [
            r for r in records if not _is_clear(r.disposition) and not _is_blocked(r.disposition)
        ]
    elif filter_choice == "Blocked":
        filtered = [r for r in records if _is_blocked(r.disposition)]
    elif filter_choice == "Cleared":
        filtered = [r for r in records if _is_clear(r.disposition)]
    else:
        filtered = list(records)

    if search_q:
        filtered = [
            r
            for r in filtered
            if search_q in _extract_merchant(r.extraction, r.file_name).lower()
            or search_q in r.employee_id.lower()
            or search_q in r.expense_id.lower()
            or search_q in r.file_name.lower()
        ]

    def _prio_rank(disp: Disposition) -> int:
        if _is_blocked(disp):
            return 0
        if not _is_clear(disp):
            return 1
        return 2

    def _amount_sort_val(r: DecisionRecord) -> float:
        usd_val = getattr(r, "converted_amount_usd", None)
        if usd_val is not None:
            try:
                return float(usd_val)
            except (TypeError, ValueError):
                pass
        tot = _extract_total(r.extraction)
        return tot if tot is not None else 0.0

    if sort_choice == "Highest amount":
        filtered.sort(key=_amount_sort_val, reverse=True)
    elif sort_choice == "Highest risk":
        filtered.sort(key=lambda r: getattr(r, "anomaly_score", 0.0), reverse=True)
    else:
        filtered.sort(key=lambda r: (_prio_rank(r.disposition), -getattr(r, "anomaly_score", 0.0)))

    st.caption(f"Showing {len(filtered)} of {len(records)} items")

    if not filtered:
        st.info("No matching expenses for the current filter and search criteria.")
        return None

    chosen_id: str | None = None
    for r in filtered:
        is_selected = r.expense_id == selected_id
        merchant_raw = _extract_merchant(r.extraction, r.file_name)
        merchant = html.escape(merchant_raw)
        emp = html.escape(r.employee_id)
        role = html.escape(r.employee_role)
        exp_id = html.escape(r.expense_id)
        tot_amt = _extract_total(r.extraction)
        cur_code = _extract_currency(r.extraction)
        amt_str = html.escape(_fmt_currency(tot_amt, cur_code))

        with st.container(border=True):
            top_l, top_r = st.columns([3.2, 1.45])
            with top_l:
                st.markdown(
                    f'<div style="font-size:1.0rem;font-weight:700;color:#0f172a;">{merchant}</div>'
                    f'<div style="font-size:0.8rem;color:#64748b;margin-top:1px;">{emp} · {role} · {exp_id}</div>',
                    unsafe_allow_html=True,
                )
            with top_r:
                st.markdown(
                    f'<div style="text-align:right;font-size:1.0rem;font-weight:700;color:#0f172a;">{amt_str}</div>',
                    unsafe_allow_html=True,
                )

            mid_l, mid_r = st.columns([2.8, 1.45])
            with mid_l:
                badges = [_disposition_badge(r.disposition)]
                for f in r.findings[:2]:
                    f_code = _finding_code(f)
                    badges.append(f'<span class="cl-badge cl-badge-tag">{html.escape(f_code)}</span>')
                st.markdown(
                    f'<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">{"".join(badges)}</div>',
                    unsafe_allow_html=True,
                )
            with mid_r:
                st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
                btn_label = "Selected" if is_selected else "Inspect"
                btn_type = "primary" if is_selected else "secondary"
                if st.button(
                    btn_label,
                    key=f"inspect_btn_{r.expense_id}",
                    type=btn_type,
                    use_container_width=True,
                ):
                    chosen_id = r.expense_id

    return chosen_id