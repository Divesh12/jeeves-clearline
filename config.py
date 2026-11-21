from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
POLICIES_DIR = BASE_DIR / "policies"
SAMPLES_DIR = BASE_DIR / "sample_receipts"

POLICY_FILE = POLICIES_DIR / "synthetic_policies.json"
FX_RATES_FILE = DATA_DIR / "fx_rates.json"
LEDGER_FILE = DATA_DIR / "synthetic_ledger.csv"
DB_FILE = BASE_DIR / "clearline.db"


@dataclass(frozen=True)
class AppConfig:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    engine_version: str = "clearline-engine-1.0.0"
    active_policy_version: str = "GLOBAL-2026.01"
    max_file_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_pdf_pages: int = 5
    math_tolerance_local: Decimal = Decimal("0.05")
    split_window_minutes: int = 120
    low_confidence_threshold: float = 0.70
    high_anomaly_risk_threshold: float = 75.0
    estimated_minutes_saved_per_clear: int = 4


config = AppConfig()