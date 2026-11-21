from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Optional

from config import config
from models.domain import Disposition, ExtractedReceipt, Finding, MoneyConversion, Severity


@dataclass
class ValidationOutcome:
    financial_fields_valid: bool
    has_financial_discrepancy: bool
    has_low_critical_confidence: bool
    conversion: Optional[MoneyConversion]
    findings: list[Finding]


def load_fx_table(fx_path: Path = config.FX_RATES_FILE) -> dict:
    with fx_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _to_decimal(val: Optional[Decimal | float | int | str]) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        d = Decimal(str(val).strip())
        if d.is_nan() or d.is_infinite():
            return None
        return d
    except (InvalidOperation, ValueError):
        return None


def convert_to_usd(amount: Decimal, currency: Optional[str], fx_data: dict) -> tuple[Optional[MoneyConversion], Optional[Finding]]:
    rates: dict[str, str] = fx_data.get("rates_to_usd", {})
    fx_date: str = fx_data.get("fx_rate_date", "2026-11-21")
    fx_source: str = fx_data.get("fx_source", "bundled_synthetic_fx_table")

    if not currency:
        return None, Finding(
            code="MISSING_CURRENCY",
            rule_id="FX-001",
            severity=Severity.HIGH,
            disposition_impact=Disposition.NEEDS_REVIEW,
            title="Currency not identified",
            observed="Missing currency",
            expected="Supported currency code (e.g., USD, GBP, EUR, MXN, INR)",
            evidence="Receipt currency could not be determined for FX conversion.",
        )

    curr_code = currency.strip().upper()
    rate_str = rates.get(curr_code)
    if rate_str is None:
        return None, Finding(
            code="UNSUPPORTED_CURRENCY",
            rule_id="FX-002",
            severity=Severity.HIGH,
            disposition_impact=Disposition.NEEDS_REVIEW,
            title=f"FX rate unavailable for {curr_code}",
            observed=f"{amount} {curr_code}",
            expected=f"Rate in {', '.join(sorted(rates.keys()))}",
            evidence=f"No FX conversion rate available in {fx_source} for {curr_code}.",
        )

    rate = Decimal(rate_str)
    converted = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    conversion = MoneyConversion(
        original_amount=amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        original_currency=curr_code,
        converted_amount=converted,
        converted_currency="USD",
        fx_rate=rate,
        fx_rate_date=fx_date,
        fx_source=fx_source,
    )
    return conversion, None


def validate_receipt_financials(
    extraction: ExtractedReceipt,
    fx_data: Optional[dict] = None,
) -> ValidationOutcome:
    fx_data = fx_data or load_fx_table()
    findings: list[Finding] = []

    total = _to_decimal(extraction.total)
    subtotal = _to_decimal(extraction.subtotal)
    tax = _to_decimal(extraction.tax) or Decimal("0.00")
    tip = _to_decimal(extraction.tip) or Decimal("0.00")
    discount = _to_decimal(extraction.discount) or Decimal("0.00")

    financial_fields_valid = True
    has_financial_discrepancy = False

    if not extraction.merchant_name or not extraction.merchant_name.strip():
        financial_fields_valid = False
        findings.append(
            Finding(
                code="MISSING_MERCHANT",
                rule_id="VAL-001",
                severity=Severity.HIGH,
                disposition_impact=Disposition.NEEDS_REVIEW,
                title="Merchant name missing",
                observed="Blank or missing merchant",
                expected="Non-empty merchant name",
                evidence="Receipt extraction did not identify a merchant name.",
            )
        )

    if total is None:
        financial_fields_valid = False
        findings.append(
            Finding(
                code="MISSING_TOTAL",
                rule_id="VAL-002",
                severity=Severity.CRITICAL,
                disposition_impact=Disposition.NEEDS_REVIEW,
                title="Receipt total missing",
                observed="None",
                expected="Valid numeric total",
                evidence="No final total amount was extracted from the receipt.",
            )
        )
    elif total <= Decimal("0.00"):
        financial_fields_valid = False
        findings.append(
            Finding(
                code="NON_POSITIVE_AMOUNT",
                rule_id="VAL-003",
                severity=Severity.HIGH,
                disposition_impact=Disposition.NEEDS_REVIEW,
                title="Non-positive or refund/zero amount",
                observed=f"{total} {extraction.currency or ''}".strip(),
                expected="Positive expense total (> 0.00)",
                evidence="Zero or negative amounts require manual review or refund verification.",
            )
        )

    conversion: Optional[MoneyConversion] = None
    if total is not None and total > Decimal("0.00"):
        conversion, fx_finding = convert_to_usd(total, extraction.currency, fx_data)
        if fx_finding:
            financial_fields_valid = False
            findings.append(fx_finding)

    # Arithmetic check when subtotal is present
    if subtotal is not None and total is not None:
        expected_total = (subtotal + tax + tip - discount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        actual_total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        diff = abs(actual_total - expected_total)
        if diff > config.math_tolerance_local:
            has_financial_discrepancy = True
            curr = (extraction.currency or "").upper()
            findings.append(
                Finding(
                    code="ARITHMETIC_DISCREPANCY",
                    rule_id="MATH-001",
                    severity=Severity.HIGH,
                    disposition_impact=Disposition.NEEDS_REVIEW,
                    title="Receipt arithmetic mismatch",
                    observed=f"Printed total {actual_total} {curr} vs calculated {expected_total} {curr} (diff {diff})",
                    expected=f"Difference within +/- {config.math_tolerance_local} {curr}",
                    evidence=(
                        f"Subtotal ({subtotal}) + Tax ({tax}) + Tip ({tip}) - Discount ({discount}) "
                        f"= {expected_total}, which differs from printed total {actual_total}. "
                        "May reflect OCR misread, uncaptured fee, or receipt calculation error."
                    ),
                )
            )

    low_conf_fields: list[str] = []
    if extraction.merchant_confidence < config.low_confidence_threshold:
        low_conf_fields.append(f"merchant ({extraction.merchant_confidence:.2f})")
    if extraction.total_confidence < config.low_confidence_threshold:
        low_conf_fields.append(f"total ({extraction.total_confidence:.2f})")
    if extraction.currency_confidence < config.low_confidence_threshold:
        low_conf_fields.append(f"currency ({extraction.currency_confidence:.2f})")

    has_low_critical_confidence = len(low_conf_fields) > 0
    if has_low_critical_confidence:
        findings.append(
            Finding(
                code="LOW_EXTRACTION_CONFIDENCE",
                rule_id="QUAL-001",
                severity=Severity.WARNING,
                disposition_impact=Disposition.NEEDS_REVIEW,
                title="Low confidence on critical receipt fields",
                observed=", ".join(low_conf_fields),
                expected=f"Confidence >= {config.low_confidence_threshold:.2f}",
                evidence="Low legibility or uncertain extraction on key fields requires controller verification.",
            )
        )

    return ValidationOutcome(
        financial_fields_valid=financial_fields_valid,
        has_financial_discrepancy=has_financial_discrepancy,
        has_low_critical_confidence=has_low_critical_confidence,
        conversion=conversion,
        findings=findings,
    )