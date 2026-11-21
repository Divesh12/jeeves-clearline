from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Disposition(str, Enum):
    CLEAR = "CLEAR"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NOT_REQUIRED = "NOT_REQUIRED"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MoneyConversion(BaseModel):
    original_amount: Decimal
    original_currency: str
    converted_amount: Decimal
    converted_currency: str = "USD"
    fx_rate: Decimal
    fx_rate_date: str
    fx_source: str = "bundled_synthetic_fx_table"


class ExtractedReceipt(BaseModel):
    merchant_name: Optional[str] = None
    expense_date: Optional[str] = None  # YYYY-MM-DD
    currency: Optional[str] = None
    subtotal: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    tip: Optional[Decimal] = None
    discount: Optional[Decimal] = None
    total: Optional[Decimal] = None
    category_hint: Optional[str] = None
    contains_alcohol_mention: bool = False
    has_itemized_lines: bool = False
    masked_card_hint: Optional[str] = None
    merchant_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    date_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    total_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    currency_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    extraction_complete: bool = False
    extraction_source: str = "none"  # gemini | replay | manual_fallback
    notes: Optional[str] = None


class Finding(BaseModel):
    code: str
    rule_id: str
    severity: Severity
    disposition_impact: Disposition
    title: str
    observed: str
    expected: str
    evidence: str


class DecisionRecord(BaseModel):
    expense_id: str
    file_name: str
    file_sha256: str
    employee_id: str
    employee_role: str
    mode_used: str  # live_ai | replay | manual_fallback
    policy_version: str
    engine_version: str
    disposition: Disposition
    approval_status: ApprovalStatus
    reason_codes: list[str]
    summary: str
    chaser_draft: Optional[str] = None
    anomaly_score: float = Field(ge=0.0, le=100.0)
    anomaly_note: str
    conversion: Optional[MoneyConversion] = None
    extraction: ExtractedReceipt
    findings: list[Finding]
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ControllerOverride(BaseModel):
    expense_id: str
    previous_disposition: Disposition
    new_disposition: Disposition
    new_approval_status: ApprovalStatus
    controller_id: str
    reason: str
    overridden_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())