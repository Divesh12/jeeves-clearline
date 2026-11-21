from __future__ import annotations

import streamlit as st

from config import config
from models.domain import DecisionRecord, Disposition

SEVERITY_RANK = {
    Disposition.BLOCKED: 0,
    Disposition.NEEDS_REVIEW: 1,
    Disposition.CLEAR: 2,
}


def render_kpi_strip(records: list[DecisionRecord]) -> None:
    total = len(records)
    clear_cnt = sum(1 for r in records if r.disposition == Disposition.CLEAR)
    review_cnt = sum(1 for r in records if r.disposition == Disposition.NEEDS_REVIEW)
    blocked_cnt = sum(1 for r in records if r.disposition == Disposition.BLOCKED)
    est_mins_saved = clear_cnt * config.estimated_minutes_saved_per_clear

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Reviewed Submissions", total)
    c2.metric("Streamlined Clear", clear_cnt)
    c3.metric("Needs Review", review_cnt)
    c4.metric("Blocked", blocked_cnt)
    c5.metric("Est. Review Time Saved", f"{est_mins_saved} min")


def render_expense_queue(records: list[DecisionRecord], selected_id: str | None) -> str | None:
    st.subheader("Exception-First Review Queue")

    if not records:
        st.info("No expenses audited yet. Upload a receipt or run a sample scenario to populate the queue.")
        return None

    col_filter, col_sort = st.columns([2, 2])
    with col_filter:
        disp_filter = st.selectbox(
            "Filter by disposition",
            options=["ALL_EXCEPTIONS_FIRST", "BLOCKED", "NEEDS_REVIEW", "CLEAR", "ALL"],
            index=0,
        )
    with col_sort:
        sort_by = st.selectbox(
            "Sort queue by",
            options=["Exception Priority", "Anomaly Risk (High to Low)", "Amount USD (High to Low)"],
            index=0,
        )

    filtered = list(records)
    if disp_filter == "ALL_EXCEPTIONS_FIRST":
        filtered = [r for r in filtered if r.disposition != Disposition.CLEAR] or list(records)
    elif disp_filter != "ALL":
        filtered = [r for r in filtered if r.disposition.value == disp_filter]

    def _amt(r: DecisionRecord) -> float:
        return float(r.conversion.converted_amount) if r.conversion else -1.0

    if sort_by == "Exception Priority":
        filtered.sort(key=lambda r: (SEVERITY_RANK.get(r.disposition, 9), -_amt(r)))
    elif sort_by == "Anomaly Risk (High to Low)":
        filtered.sort(key=lambda r: (-r.anomaly_score, SEVERITY_RANK.get(r.disposition, 9)))
    else:
        filtered.sort(key=lambda r: (-_amt(r), SEVERITY_RANK.get(r.disposition, 9)))

    chosen_id = selected_id or filtered[0].expense_id

    for rec in filtered:
        amt_label = (
            f"${rec.conversion.converted_amount} USD ({rec.conversion.original_amount} {rec.conversion.original_currency})"
            if rec.conversion
            else "Amount N/A"
        )
        top_finding = rec.findings[0].title if rec.findings else "All clearance checks passed"
        label = (
            f"**{rec.disposition.value}** | `{rec.expense_id}` | Emp `{rec.employee_id}` | "
            f"{rec.extraction.merchant_name or rec.file_name} — **{amt_label}** | {top_finding}"
        )
        is_selected = rec.expense_id == chosen_id
        btn_type = "primary" if is_selected else "secondary"
        if st.button(label, key=f"row_{rec.expense_id}", type=btn_type, use_container_width=True):
            chosen_id = rec.expense_id

    return chosen_id