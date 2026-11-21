from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

from config import config
from models.domain import Disposition, ExtractedReceipt, Finding, MoneyConversion, Severity


@dataclass
class PolicyOutcome:
    policy_version: str
    has_hard_policy_violation: bool
    findings: list[Finding]


def load_policy(policy_path: Path = config.POLICY_FILE) -> dict:
    with policy_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_policy(
    extraction: ExtractedReceipt,
    conversion: Optional[MoneyConversion],
    policy_data: Optional[dict] = None,
) -> PolicyOutcome:
    policy_data = policy_data or load_policy()
    version = policy_data.get("policy_version", config.active_policy_version)
    rules: list[dict] = policy_data.get("rules", [])

    findings: list[Finding] = []
    has_hard_violation = False

    category = (extraction.category_hint or "GENERAL").strip().upper()
    amount_usd = conversion.converted_amount if conversion else None

    for rule in rules:
        rule_id = rule.get("rule_id", "POL-UNK")
        rule_cat = (rule.get("category") or "ALL").upper()
        sev_raw = (rule.get("severity") or "WARNING").upper()
        disp_raw = (rule.get("disposition_on_breach") or "NEEDS_REVIEW").upper()

        severity = Severity(sev_raw) if sev_raw in Severity._value2member_map_ else Severity.WARNING
        disposition_impact = (
            Disposition(disp_raw) if disp_raw in Disposition._value2member_map_ else Disposition.NEEDS_REVIEW
        )

        # MEAL-001: Meal spend limit in USD
        if rule_id == "MEAL-001" and amount_usd is not None:
            limit_usd = Decimal(str(rule.get("limit_usd", "75.00")))
            if category in {"MEALS", "MEAL", "FOOD", "DINING"} and amount_usd > limit_usd:
                exceeded_by = amount_usd - limit_usd
                findings.append(
                    Finding(
                        code="MEAL_CAP_EXCEEDED",
                        rule_id=rule_id,
                        severity=severity,
                        disposition_impact=disposition_impact,
                        title="Meal expense exceeds policy limit",
                        observed=f"${amount_usd} USD (from {conversion.original_amount} {conversion.original_currency})",
                        expected=f"<= ${limit_usd} USD",
                        evidence=(
                            f"Rule {rule_id}: {rule.get('description')}. "
                            f"Converted total ${amount_usd} USD exceeds ${limit_usd} USD by ${exceeded_by}."
                        ),
                    )
                )
                if disposition_impact == Disposition.BLOCKED:
                    has_hard_violation = True

        # ALC-001: Alcohol mention on expense
        elif rule_id == "ALC-001" and extraction.contains_alcohol_mention:
            findings.append(
                Finding(
                    code="ALCOHOL_MENTIONED",
                    rule_id=rule_id,
                    severity=severity,
                    disposition_impact=disposition_impact,
                    title="Alcoholic item detected on receipt",
                    observed="Alcoholic beverage / bar item present",
                    expected="No alcohol unless explicitly approved under policy",
                    evidence=(
                        f"Rule {rule_id}: {rule.get('description')}. "
                        f"Merchant '{extraction.merchant_name or 'Unknown'}' flagged for alcohol mention."
                    ),
                )
            )
            if disposition_impact == Disposition.BLOCKED:
                has_hard_violation = True

        # HIGH-001: High-value single expense
        elif rule_id == "HIGH-001" and amount_usd is not None and rule_cat == "ALL":
            cap_usd = Decimal(str(rule.get("max_single_usd", "500.00")))
            if amount_usd > cap_usd:
                findings.append(
                    Finding(
                        code="HIGH_VALUE_EXPENSE",
                        rule_id=rule_id,
                        severity=severity,
                        disposition_impact=disposition_impact,
                        title="High-value expense requires verification",
                        observed=f"${amount_usd} USD",
                        expected=f"<= ${cap_usd} USD without secondary check",
                        evidence=f"Rule {rule_id}: {rule.get('description')}. Amount ${amount_usd} USD exceeds ${cap_usd} USD.",
                    )
                )
                if disposition_impact == Disposition.BLOCKED:
                    has_hard_violation = True

    return PolicyOutcome(
        policy_version=version,
        has_hard_policy_violation=has_hard_violation,
        findings=findings,
    )