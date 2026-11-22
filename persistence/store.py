from __future__ import annotations
from config import DB_FILE, LEDGER_FILE

import csv
import json
import sqlite3
from pathlib import Path
from typing import Optional

from config import config
from models.domain import (
    ApprovalStatus,
    ControllerOverride,
    DecisionRecord,
    Disposition,
)


class AuditStore:
    def __init__(self, db_path: Path = DB_FILE) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    expense_id TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    file_sha256 TEXT NOT NULL,
                    employee_id TEXT NOT NULL,
                    employee_role TEXT NOT NULL,
                    merchant_normalized TEXT,
                    expense_date TEXT,
                    submitted_at TEXT NOT NULL,
                    amount_usd TEXT,
                    mode_used TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    engine_version TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    approval_status TEXT NOT NULL,
                    anomaly_score REAL NOT NULL,
                    record_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_decisions_sha256
                    ON decisions(file_sha256);

                CREATE INDEX IF NOT EXISTS idx_decisions_emp_merchant_time
                    ON decisions(employee_id, merchant_normalized, submitted_at);

                CREATE TABLE IF NOT EXISTS controller_overrides (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expense_id TEXT NOT NULL,
                    previous_disposition TEXT NOT NULL,
                    new_disposition TEXT NOT NULL,
                    new_approval_status TEXT NOT NULL,
                    controller_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    overridden_at TEXT NOT NULL,
                    FOREIGN KEY (expense_id) REFERENCES decisions(expense_id)
                );

                CREATE TABLE IF NOT EXISTS baseline_ledger (
                    txn_id TEXT PRIMARY KEY,
                    employee_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    merchant TEXT NOT NULL,
                    merchant_normalized TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    hour_of_day INTEGER NOT NULL,
                    is_weekend INTEGER NOT NULL,
                    timestamp TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def normalize_merchant(name: Optional[str]) -> str:
        if not name:
            return ""
        cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in name)
        return " ".join(cleaned.split())

    def seed_baseline_from_csv(self, csv_path: Path = LEDGER_FILE) -> int:
        if not csv_path.exists():
            return 0
        self._init_db()
        inserted = 0
        with self._connect() as conn, csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO baseline_ledger (
                        txn_id, employee_id, role, merchant, merchant_normalized,
                        category, amount_usd, hour_of_day, is_weekend, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["txn_id"],
                        row["employee_id"],
                        row["role"],
                        row["merchant"],
                        self.normalize_merchant(row["merchant"]),
                        row["category"],
                        float(row["amount_usd"]),
                        int(row["hour_of_day"]),
                        int(row["is_weekend"]),
                        row["timestamp"],
                    ),
                )
                inserted += cur.rowcount
        return inserted

    def save_decision(self, record: DecisionRecord) -> None:
        merchant_norm = self.normalize_merchant(record.extraction.merchant_name)
        amount_usd_str = str(record.conversion.converted_amount) if record.conversion else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO decisions (
                    expense_id, file_name, file_sha256, employee_id, employee_role,
                    merchant_normalized, expense_date, submitted_at, amount_usd,
                    mode_used, policy_version, engine_version, disposition,
                    approval_status, anomaly_score, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.expense_id,
                    record.file_name,
                    record.file_sha256,
                    record.employee_id,
                    record.employee_role,
                    merchant_norm,
                    record.extraction.expense_date,
                    record.created_at,
                    amount_usd_str,
                    record.mode_used,
                    record.policy_version,
                    record.engine_version,
                    record.disposition.value,
                    record.approval_status.value,
                    record.anomaly_score,
                    record.model_dump_json(),
                ),
            )

    def get_decision(self, expense_id: str) -> Optional[DecisionRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT record_json FROM decisions WHERE expense_id = ?",
                (expense_id,),
            ).fetchone()
            if not row:
                return None
            return DecisionRecord.model_validate_json(row["record_json"])

    def list_decisions(self) -> list[DecisionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT record_json FROM decisions ORDER BY submitted_at DESC"
            ).fetchall()
            return [DecisionRecord.model_validate_json(r["record_json"]) for r in rows]

    def find_exact_hash_matches(self, file_sha256: str, exclude_expense_id: Optional[str] = None) -> list[DecisionRecord]:
        with self._connect() as conn:
            if exclude_expense_id:
                rows = conn.execute(
                    "SELECT record_json FROM decisions WHERE file_sha256 = ? AND expense_id != ?",
                    (file_sha256, exclude_expense_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT record_json FROM decisions WHERE file_sha256 = ?",
                    (file_sha256,),
                ).fetchall()
            return [DecisionRecord.model_validate_json(r["record_json"]) for r in rows]

    def find_recent_employee_decisions(
        self,
        employee_id: str,
        merchant_normalized: Optional[str],
        exclude_expense_id: Optional[str] = None,
    ) -> list[DecisionRecord]:
        if not merchant_normalized:
            return []
        with self._connect() as conn:
            if exclude_expense_id:
                rows = conn.execute(
                    """
                    SELECT record_json FROM decisions
                    WHERE employee_id = ? AND merchant_normalized = ? AND expense_id != ?
                    ORDER BY submitted_at DESC
                    """,
                    (employee_id, merchant_normalized, exclude_expense_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT record_json FROM decisions
                    WHERE employee_id = ? AND merchant_normalized = ?
                    ORDER BY submitted_at DESC
                    """,
                    (employee_id, merchant_normalized),
                ).fetchall()
            return [DecisionRecord.model_validate_json(r["record_json"]) for r in rows]

    def record_override(self, override: ControllerOverride) -> None:
        if not override.reason or not override.reason.strip():
            raise ValueError("Controller override requires a non-empty reason.")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO controller_overrides (
                    expense_id, previous_disposition, new_disposition,
                    new_approval_status, controller_id, reason, overridden_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    override.expense_id,
                    override.previous_disposition.value,
                    override.new_disposition.value,
                    override.new_approval_status.value,
                    override.controller_id,
                    override.reason.strip(),
                    override.overridden_at,
                ),
            )
            conn.execute(
                """
                UPDATE decisions
                SET disposition = ?, approval_status = ?
                WHERE expense_id = ?
                """,
                (
                    override.new_disposition.value,
                    override.new_approval_status.value,
                    override.expense_id,
                ),
            )
            row = conn.execute(
                "SELECT record_json FROM decisions WHERE expense_id = ?",
                (override.expense_id,),
            ).fetchone()
            if row:
                rec = DecisionRecord.model_validate_json(row["record_json"])
                rec.disposition = override.new_disposition
                rec.approval_status = override.new_approval_status
                conn.execute(
                    "UPDATE decisions SET record_json = ? WHERE expense_id = ?",
                    (rec.model_dump_json(), override.expense_id),
                )

    def list_overrides(self, expense_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT previous_disposition, new_disposition, new_approval_status,
                       controller_id, reason, overridden_at
                FROM controller_overrides
                WHERE expense_id = ?
                ORDER BY id DESC
                """,
                (expense_id,),
            ).fetchall()
            return [dict(r) for r in rows]