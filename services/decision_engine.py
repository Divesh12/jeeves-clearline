from __future__ import annotations

from typing import Optional

from config import config
from models.domain import ApprovalStatus, Disposition, ExtractedReceipt, Finding
from services.policy_engine import PolicyOutcome
from services.risk_engine import RiskOutcome
from services.validation import ValidationOutcome


def build_chaser_draft(
    employee_id: str,
    extraction: ExtractedReceipt,
    findings: list[Finding],
) -> Optional[str]:
    codes = {f.code for f in findings}
    merchant = extraction.merchant_name or "the merchant"
    exp_date = extraction.expense_date or "recent submission"

    needed: list[str] = []
    if "MISSING_MERCHANT" in codes or "MISSING_TOTAL" in codes or "LOW_EXTRACTION_CONFIDENCE" in codes:
        needed.append("a clearer, legible itemized receipt")
    if "POSSIBLE_SPLIT_TRANSACTION" in codes:
        needed.append("clarification on the back-to-back charges at the same merchant and their business purpose")
    if "ARITHMETIC_DISCREPANCY" in codes:
        needed.append("confirmation of the itemized subtotal, taxes, tips, and final charged total")

    if not needed:
        return None

    joined = " and ".join(needed)
    return (
        f"Hi {employee_id}, we're reviewing your expense at {merchant} ({exp_date}) "
        f"and need {joined} before finalizing review. Thanks, Finance."
    )


def decide_disposition(
    extraction: ExtractedReceipt,
    validation: ValidationOutcome,
    policy: PolicyOutcome,
    risk: RiskOutcome,
) -> tuple[Disposition, ApprovalStatus, list[str], str, Optional[str]]:
    all_findings = validation.findings + policy.findings + risk.findings
    reason_codes: list[str] = []

    def add_code(code: str) -> None:
        if code not in reason_codes:
            reason_codes.append(code)

    for f in all_findings:
        add_code(f.code)

    # Deterministic priority order
    if not extraction.extraction_complete:
        add_code("EXTRACTION_INCOMPLETE")
        disp = Disposition.NEEDS_REVIEW
    elif not validation.financial_fields_valid:
        add_code("INVALID_FINANCIAL_FIELDS")
        disp = Disposition.NEEDS_REVIEW
    elif risk.confirmed_duplicate:
        disp = Disposition.BLOCKED
    elif policy.has_hard_policy_violation:
        disp = Disposition.BLOCKED
    elif validation.has_financial_discrepancy:
        disp = Disposition.NEEDS_REVIEW
    elif risk.has_split_suspicion:
        disp = Disposition.NEEDS_REVIEW
    elif risk.has_high_risk_signal:
        disp = Disposition.NEEDS_REVIEW
    elif validation.has_low_critical_confidence:
        disp = Disposition.NEEDS_REVIEW
    elif any(f.disposition_impact == Disposition.BLOCKED for f in all_findings):
        disp = Disposition.BLOCKED
    elif any(f.disposition_impact == Disposition.NEEDS_REVIEW for f in all_findings):
        disp = Disposition.NEEDS_REVIEW
    else:
        add_code("ALL_CLEARANCE_CHECKS_PASSED")
        disp = Disposition.CLEAR

    approval_status = ApprovalStatus.NOT_REQUIRED if disp == Disposition.CLEAR else ApprovalStatus.PENDING

    if disp == Disposition.CLEAR:
        summary = "Eligible for streamlined clearance: extraction complete, math reconciled, no policy or risk flags."
    elif disp == Disposition.BLOCKED:
        summary = f"Blocked by deterministic control ({', '.join(reason_codes[:3])}). Controller review required."
    else:
        summary = f"Routed for controller review ({', '.join(reason_codes[:3]) or 'verification required'})."

    chaser = build_chaser_draft(employee_id="Employee", extraction=extraction, findings=all_findings) if disp != Disposition.CLEAR else None
    return disp, approval_status, reason_codes, summary, chaser