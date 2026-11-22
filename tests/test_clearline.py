from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import pytest
import io
from PIL import Image

from models.domain import (
    ApprovalStatus,
    ControllerOverride,
    Disposition,
    ExtractedReceipt,
)
from persistence.store import AuditStore
from scripts.seed_data import generate_synthetic_ledger
from services.extraction import ManualReviewExtractor, ReceiptExtractor
from services.pipeline import run_expense_pipeline


class StubExtractor(ReceiptExtractor):
    def __init__(self, payload: ExtractedReceipt) -> None:
        self.payload = payload

    def extract(self, file_name: str, mime_type: str, file_bytes: bytes) -> ExtractedReceipt:
        return self.payload.model_copy(deep=True)


@pytest.fixture()
def temp_store(tmp_path: Path) -> AuditStore:
    ledger_csv = tmp_path / "ledger.csv"
    generate_synthetic_ledger(output_path=ledger_csv, rows=250)
    store = AuditStore(db_path=tmp_path / "test_clearline.db")
    store.seed_baseline_from_csv(ledger_csv)
    return store


def test_clean_us_lunch_clears(temp_store: AuditStore) -> None:
    receipt = ExtractedReceipt(
        merchant_name="Sweetgreen",
        expense_date="2026-11-18",
        currency="USD",
        subtotal=Decimal("20.00"),
        tax=Decimal("1.80"),
        tip=Decimal("3.20"),
        discount=Decimal("0.00"),
        total=Decimal("25.00"),
        category_hint="MEALS",
        contains_alcohol_mention=False,
        has_itemized_lines=True,
        merchant_confidence=0.98,
        date_confidence=0.96,
        total_confidence=0.98,
        currency_confidence=0.99,
        extraction_complete=True,
        extraction_source="test",
    )
    rec = run_expense_pipeline(
        store=temp_store,
        file_name="lunch.png",
        file_bytes = _make_png_bytes((70, 80, 90)),
        employee_id="E104",
        extractor_override=StubExtractor(receipt),
    )
    assert rec.disposition == Disposition.CLEAR
    assert rec.approval_status == ApprovalStatus.NOT_REQUIRED
    assert rec.conversion is not None
    assert rec.conversion.converted_amount == Decimal("25.00")


def test_arithmetic_mismatch_routes_to_review(temp_store: AuditStore) -> None:
    receipt = ExtractedReceipt(
        merchant_name="Local Bistro",
        expense_date="2026-11-19",
        currency="USD",
        subtotal=Decimal("50.00"),
        tax=Decimal("4.00"),
        tip=Decimal("6.00"),
        discount=Decimal("0.00"),
        total=Decimal("72.00"),  # Should be 60.00
        category_hint="MEALS",
        merchant_confidence=0.95,
        date_confidence=0.95,
        total_confidence=0.95,
        currency_confidence=0.95,
        extraction_complete=True,
        extraction_source="test",
    )
    rec = run_expense_pipeline(
        store=temp_store,
        file_name="bad_math.png",
        file_bytes=_make_png_bytes((40, 50, 60)),
        employee_id="E107",
        extractor_override=StubExtractor(receipt),
    )
    assert rec.disposition == Disposition.NEEDS_REVIEW
    assert "ARITHMETIC_DISCREPANCY" in rec.reason_codes


def test_exact_duplicate_is_blocked(temp_store: AuditStore) -> None:
    receipt = ExtractedReceipt(
        merchant_name="Sweetgreen",
        expense_date="2026-11-18",
        currency="USD",
        subtotal=Decimal("18.00"),
        tax=Decimal("1.60"),
        tip=Decimal("2.40"),
        discount=Decimal("0.00"),
        total=Decimal("22.00"),
        category_hint="MEALS",
        merchant_confidence=0.95,
        date_confidence=0.95,
        total_confidence=0.95,
        currency_confidence=0.95,
        extraction_complete=True,
        extraction_source="test",
    )
    payload = _make_png_bytes((70, 80, 90))
    first = run_expense_pipeline(
        store=temp_store,
        file_name="dup.png",
        file_bytes=payload,
        employee_id="E104",
        extractor_override=StubExtractor(receipt),
    )
    second = run_expense_pipeline(
        store=temp_store,
        file_name="dup.png",
        file_bytes=payload,
        employee_id="E104",
        extractor_override=StubExtractor(receipt),
    )
    assert first.disposition == Disposition.CLEAR
    assert second.disposition == Disposition.BLOCKED
    assert "EXACT_FILE_DUPLICATE" in second.reason_codes


def test_failed_extraction_never_auto_clears(temp_store: AuditStore) -> None:
    rec = run_expense_pipeline(
        store=temp_store,
        file_name="blurry.png",
        file_bytes=_make_png_bytes((100, 110, 120)),
        employee_id="E105",
        extractor_override=ManualReviewExtractor("Unreadable receipt"),
    )
    assert rec.disposition == Disposition.NEEDS_REVIEW
    assert "EXTRACTION_INCOMPLETE" in rec.reason_codes


def test_override_requires_reason_and_persists(temp_store: AuditStore) -> None:
    rec = run_expense_pipeline(
        store=temp_store,
        file_name="review_me.png",
        file_bytes=b"\x89PNG\r\n\x1a\nreview_bytes",
        employee_id="E105",
        extractor_override=ManualReviewExtractor("Needs check"),
    )
    with pytest.raises(ValueError):
        temp_store.record_override(
            ControllerOverride(
                expense_id=rec.expense_id,
                previous_disposition=rec.disposition,
                new_disposition=Disposition.CLEAR,
                new_approval_status=ApprovalStatus.APPROVED,
                controller_id="CTRL-01",
                reason="   ",
            )
        )

    temp_store.record_override(
        ControllerOverride(
            expense_id=rec.expense_id,
            previous_disposition=rec.disposition,
            new_disposition=Disposition.CLEAR,
            new_approval_status=ApprovalStatus.APPROVED,
            controller_id="CTRL-01",
            reason="Verified original physical receipt with employee.",
        )
    )
    updated = temp_store.get_decision(rec.expense_id)
    assert updated is not None
    assert updated.disposition == Disposition.CLEAR
    assert updated.approval_status == ApprovalStatus.APPROVED
    assert len(temp_store.list_overrides(rec.expense_id)) == 1

def _make_png_bytes(color: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (32, 32), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()