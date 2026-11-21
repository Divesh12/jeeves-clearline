from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import numpy as np
from sklearn.ensemble import IsolationForest

from config import config
from models.domain import DecisionRecord, Disposition, ExtractedReceipt, Finding, MoneyConversion, Severity
from persistence.store import AuditStore


@dataclass
class RiskOutcome:
    confirmed_duplicate: bool
    has_split_suspicion: bool
    has_high_risk_signal: bool
    anomaly_score: float
    anomaly_note: str
    findings: list[Finding]


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _compute_anomaly_score(
    store: AuditStore,
    employee_id: str,
    amount_usd: Optional[Decimal],
    submitted_at: str,
) -> tuple[float, str]:
    """Supplementary behavioral risk signal using IsolationForest on baseline ledger."""
    if amount_usd is None:
        return 25.0, "Baseline score (25/100): USD amount unavailable for behavioral comparison."

    with store._connect() as conn:
        rows = conn.execute(
            "SELECT amount_usd, hour_of_day, is_weekend FROM baseline_ledger"
        ).fetchall()

    if len(rows) < 20:
        return 20.0, "Experimental baseline score (20/100): insufficient historical rows."

    X = np.array(
        [[float(r["amount_usd"]), float(r["hour_of_day"]), float(r["is_weekend"])] for r in rows],
        dtype=float,
    )
    model = IsolationForest(n_estimators=50, contamination=0.08, random_state=42)
    model.fit(X)

    dt = _parse_iso_dt(submitted_at) or datetime.now(timezone.utc)
    hour = float(dt.hour)
    is_weekend = 1.0 if dt.weekday() >= 5 else 0.0
    amt = float(amount_usd)

    # Normalize score_samples to a 0-100 risk index (higher = more unusual vs baseline)
    raw_norm = float(model.score_samples(np.array([[amt, hour, is_weekend]], dtype=float))[0])
    # Typical score_samples range is around [-0.8, -0.35]; map cleanly into [5, 95]
    risk = max(5.0, min(95.0, round((-raw_norm - 0.35) * 180.0 + 15.0, 1)))

    emp_row = conn.execute(
        "SELECT COUNT(*) AS cnt, AVG(amount_usd) AS avg_amt FROM baseline_ledger WHERE employee_id = ?",
        (employee_id,),
    ).fetchone()
    emp_cnt = int(emp_row["cnt"] or 0)
    emp_avg = emp_row["avg_amt"]

    if emp_cnt > 0 and emp_avg is not None:
        note = (
            f"Supplementary ML score ({risk}/100, experimental): ${amt:.2f} USD at {int(hour):02d}:00 "
            f"(employee baseline avg ${float(emp_avg):.2f} across {emp_cnt} historical txns)."
        )
    else:
        note = (
            f"Supplementary ML score ({risk}/100, experimental): ${amt:.2f} USD at {int(hour):02d}:00 "
            "(new employee in baseline; not a standalone rejection)."
        )
    return risk, note


def evaluate_risk(
    store: AuditStore,
    expense_id: str,
    file_sha256: str,
    employee_id: str,
    extraction: ExtractedReceipt,
    conversion: Optional[MoneyConversion],
    submitted_at: str,
) -> RiskOutcome:
    findings: list[Finding] = []
    confirmed_duplicate = False
    has_split_suspicion = False

    # 1. Exact file duplicate (SHA-256)
    exact_matches = store.find_exact_hash_matches(file_sha256, exclude_expense_id=expense_id)
    if exact_matches:
        confirmed_duplicate = True
        prev = exact_matches[0]
        findings.append(
            Finding(
                code="EXACT_FILE_DUPLICATE",
                rule_id="DUP-001",
                severity=Severity.CRITICAL,
                disposition_impact=Disposition.BLOCKED,
                title="Exact duplicate receipt file uploaded",
                observed=f"SHA-256 matches prior expense {prev.expense_id} ({prev.file_name})",
                expected="Unique receipt file per submission",
                evidence="Identical file content hash detected in local audit history.",
            )
        )

    # 2. Probable receipt duplicate (same employee + merchant + date + amount)
    merchant_norm = store.normalize_merchant(extraction.merchant_name)
    recent_same = store.find_recent_employee_decisions(employee_id, merchant_norm, exclude_expense_id=expense_id)
    if not confirmed_duplicate and recent_same and conversion is not None:
        for prev in recent_same:
            prev_amt = prev.conversion.converted_amount if prev.conversion else None
            same_date = (
                prev.extraction.expense_date is not None
                and extraction.expense_date is not None
                and prev.extraction.expense_date == extraction.expense_date
            )
            if same_date and prev_amt == conversion.converted_amount:
                findings.append(
                    Finding(
                        code="PROBABLE_EXPENSE_DUPLICATE",
                        rule_id="DUP-002",
                        severity=Severity.HIGH,
                        disposition_impact=Disposition.NEEDS_REVIEW,
                        title="Probable duplicate expense submission",
                        observed=f"Matching merchant, date ({extraction.expense_date}), and amount (${conversion.converted_amount} USD) as {prev.expense_id}",
                        expected="Distinct expense claim",
                        evidence="Expense details match an earlier submission for the same employee.",
                    )
                )
                break

    # 3. Possible split transaction (same employee + normalized merchant within window)
    current_dt = _parse_iso_dt(submitted_at) or datetime.now(timezone.utc)
    if recent_same and conversion is not None:
        for prev in recent_same:
            prev_dt = _parse_iso_dt(prev.created_at)
            prev_amt = prev.conversion.converted_amount if prev.conversion else None
            if prev_dt is not None and prev_amt is not None:
                mins_apart = abs((current_dt - prev_dt).total_seconds()) / 60.0
                combined_usd = conversion.converted_amount + prev_amt
                if mins_apart <= config.split_window_minutes and combined_usd > Decimal("75.00"):
                    has_split_suspicion = True
                    findings.append(
                        Finding(
                            code="POSSIBLE_SPLIT_TRANSACTION",
                            rule_id="SPL-001",
                            severity=Severity.HIGH,
                            disposition_impact=Disposition.NEEDS_REVIEW,
                            title="Potential split transaction near threshold",
                            observed=(
                                f"Combined ${combined_usd} USD across 2 submissions (${prev_amt} + ${conversion.converted_amount}) "
                                f"within {mins_apart:.0f} mins at '{extraction.merchant_name}'"
                            ),
                            expected=f"Combined spend <= $75.00 USD within {config.split_window_minutes}m window",
                            evidence=(
                                "Rule SPL-001: Close sequential charges at the same merchant may indicate split billing "
                                "or separate legitimate orders; requires controller verification."
                            ),
                        )
                    )
                    break

    anomaly_score, anomaly_note = _compute_anomaly_score(
        store=store,
        employee_id=employee_id,
        amount_usd=conversion.converted_amount if conversion else None,
        submitted_at=submitted_at,
    )
    has_high_risk_signal = anomaly_score >= config.high_anomaly_risk_threshold
    if has_high_risk_signal:
        findings.append(
            Finding(
                code="HIGH_ANOMALY_RISK",
                rule_id="ANOM-001",
                severity=Severity.WARNING,
                disposition_impact=Disposition.NEEDS_REVIEW,
                title="Elevated behavioral anomaly score",
                observed=f"Risk score {anomaly_score}/100",
                expected=f"< {config.high_anomaly_risk_threshold}/100",
                evidence=anomaly_note,
            )
        )

    return RiskOutcome(
        confirmed_duplicate=confirmed_duplicate,
        has_split_suspicion=has_split_suspicion,
        has_high_risk_signal=has_high_risk_signal,
        anomaly_score=anomaly_score,
        anomaly_note=anomaly_note,
        findings=findings,
    )