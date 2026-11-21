from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from config import config
from models.domain import (
    ApprovalStatus,
    DecisionRecord,
    Disposition,
    ExtractedReceipt,
    Finding,
    Severity,
)
from persistence.store import AuditStore
from services.decision_engine import decide_disposition
from services.extraction import (
    GeminiReceiptExtractor,
    ManualReviewExtractor,
    ReceiptExtractor,
    ReplayReceiptExtractor,
)
from services.intake import validate_and_ingest
from services.policy_engine import evaluate_policy
from services.risk_engine import evaluate_risk
from services.validation import validate_receipt_financials


def run_expense_pipeline(
    store: AuditStore,
    file_name: str,
    file_bytes: bytes,
    employee_id: str,
    employee_role: str = "Employee",
    use_external_ai: bool = True,
    replay_mode: bool = False,
    extractor_override: Optional[ReceiptExtractor] = None,
) -> DecisionRecord:
    expense_id = f"EXP-{uuid.uuid4().hex[:8].upper()}"
    submitted_at = datetime.now(timezone.utc).isoformat()

    intake = validate_and_ingest(file_name=file_name, file_bytes=file_bytes)
    if not intake.valid:
        invalid_extraction = ExtractedReceipt(
            extraction_complete=False,
            extraction_source="intake_rejected",
            notes=intake.error,
        )
        finding = Finding(
            code="INVALID_UPLOAD",
            rule_id="INT-001",
            severity=Severity.HIGH,
            disposition_impact=Disposition.NEEDS_REVIEW,
            title="Uploaded file failed intake checks",
            observed=file_name,
            expected="Valid PDF/PNG/JPG under size and page limits",
            evidence=intake.error or "Intake validation failed.",
        )
        record = DecisionRecord(
            expense_id=expense_id,
            file_name=file_name,
            file_sha256=intake.file_sha256,
            employee_id=employee_id.strip() or "UNKNOWN",
            employee_role=employee_role.strip() or "Employee",
            mode_used="replay" if replay_mode else ("live_ai" if use_external_ai else "manual_fallback"),
            policy_version=config.active_policy_version,
            engine_version=config.engine_version,
            disposition=Disposition.NEEDS_REVIEW,
            approval_status=ApprovalStatus.PENDING,
            reason_codes=["INVALID_UPLOAD"],
            summary=intake.error or "File rejected during intake; routed to manual review.",
            chaser_draft=None,
            anomaly_score=0.0,
            anomaly_note="Skipped due to invalid file upload.",
            conversion=None,
            extraction=invalid_extraction,
            findings=[finding],
            created_at=submitted_at,
        )
        store.save_decision(record)
        return record

    if extractor_override is not None:
        extractor = extractor_override
        mode_used = "custom_test"
    elif replay_mode:
        extractor = ReplayReceiptExtractor()
        mode_used = "replay"
    elif use_external_ai:
        extractor = GeminiReceiptExtractor()
        mode_used = "live_ai"
    else:
        extractor = ManualReviewExtractor("External AI processing turned off by user.")
        mode_used = "manual_fallback"

    extraction = extractor.extract(
        file_name=intake.file_name,
        mime_type=intake.mime_type,
        file_bytes=intake.file_bytes,
    )

    validation = validate_receipt_financials(extraction=extraction)
    policy = evaluate_policy(extraction=extraction, conversion=validation.conversion)
    risk = evaluate_risk(
        store=store,
        expense_id=expense_id,
        file_sha256=intake.file_sha256,
        employee_id=employee_id.strip() or "UNKNOWN",
        extraction=extraction,
        conversion=validation.conversion,
        submitted_at=submitted_at,
    )

    disposition, approval_status, reason_codes, summary, chaser = decide_disposition(
        extraction=extraction,
        validation=validation,
        policy=policy,
        risk=risk,
    )
    if chaser:
        chaser = chaser.replace("Hi Employee,", f"Hi {employee_id.strip() or 'there'},", 1)

    all_findings = validation.findings + policy.findings + risk.findings

    record = DecisionRecord(
        expense_id=expense_id,
        file_name=intake.file_name,
        file_sha256=intake.file_sha256,
        employee_id=employee_id.strip() or "UNKNOWN",
        employee_role=employee_role.strip() or "Employee",
        mode_used=mode_used,
        policy_version=policy.policy_version,
        engine_version=config.engine_version,
        disposition=disposition,
        approval_status=approval_status,
        reason_codes=reason_codes,
        summary=summary,
        chaser_draft=chaser,
        anomaly_score=risk.anomaly_score,
        anomaly_note=risk.anomaly_note,
        conversion=validation.conversion,
        extraction=extraction,
        findings=all_findings,
        created_at=submitted_at,
    )
    store.save_decision(record)
    return record