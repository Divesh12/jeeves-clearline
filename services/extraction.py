from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional

from google import genai
from google.genai import types

from config import config
from models.domain import ExtractedReceipt
from services.intake import mask_sensitive_text

EXTRACTION_PROMPT = """
You are a precise receipt data extractor for corporate expense auditing.
Extract fields strictly as shown on the receipt. Do not guess missing numbers.
- Use ISO currency codes (USD, GBP, EUR, MXN, INR) when identifiable.
- Use YYYY-MM-DD for expense_date if a date is visible.
- Return subtotal, tax, tip, discount, and total as numbers when clearly printed.
- Set contains_alcohol_mention=true if alcoholic drinks/bars/cocktails/beer/wine/spirits appear.
- Set has_itemized_lines=true if individual purchased items/services are listed rather than only a lump sum.
- Mask any card numbers you mention in notes or masked_card_hint (show only last 4 digits if visible).
- Rate merchant_confidence, date_confidence, total_confidence, and currency_confidence from 0.0 to 1.0
  based on visual legibility and clarity.
"""

REPLAY_FIXTURES: dict[str, ExtractedReceipt] = {
    "01_clean_us_lunch.png": ExtractedReceipt(
        merchant_name="Sweetgreen",
        expense_date="2026-11-18",
        currency="USD",
        subtotal=Decimal("24.50"),
        tax=Decimal("2.18"),
        tip=Decimal("4.00"),
        discount=Decimal("0.00"),
        total=Decimal("30.68"),
        category_hint="MEALS",
        contains_alcohol_mention=False,
        has_itemized_lines=True,
        masked_card_hint="****-****-****-4821",
        merchant_confidence=0.98,
        date_confidence=0.96,
        total_confidence=0.98,
        currency_confidence=0.99,
        extraction_complete=True,
        extraction_source="replay",
        notes="Replay fixture: clean US lunch within policy.",
    ),
    "02_uk_dinner_alcohol.pdf": ExtractedReceipt(
        merchant_name="The Ivy Soho Brasserie",
        expense_date="2026-11-18",
        currency="GBP",
        subtotal=Decimal("92.00"),
        tax=Decimal("18.40"),
        tip=Decimal("11.50"),
        discount=Decimal("0.00"),
        total=Decimal("121.90"),
        category_hint="MEALS",
        contains_alcohol_mention=True,
        has_itemized_lines=True,
        masked_card_hint="****-****-****-9012",
        merchant_confidence=0.96,
        date_confidence=0.95,
        total_confidence=0.96,
        currency_confidence=0.97,
        extraction_complete=True,
        extraction_source="replay",
        notes="Replay fixture: UK dinner above GBP/USD meal cap with alcohol line item.",
    ),
    "03_split_part_a.png": ExtractedReceipt(
        merchant_name="Blue Bottle Coffee",
        expense_date="2026-11-19",
        currency="USD",
        subtotal=Decimal("42.00"),
        tax=Decimal("3.73"),
        tip=Decimal("0.00"),
        discount=Decimal("0.00"),
        total=Decimal("45.73"),
        category_hint="MEALS",
        contains_alcohol_mention=False,
        has_itemized_lines=True,
        masked_card_hint="****-****-****-1104",
        merchant_confidence=0.95,
        date_confidence=0.94,
        total_confidence=0.96,
        currency_confidence=0.98,
        extraction_complete=True,
        extraction_source="replay",
        notes="Replay fixture: first part of potential split pair.",
    ),
    "03_split_part_b.png": ExtractedReceipt(
        merchant_name="Blue Bottle Coffee",
        expense_date="2026-11-19",
        currency="USD",
        subtotal=Decimal("41.50"),
        tax=Decimal("3.68"),
        tip=Decimal("0.00"),
        discount=Decimal("0.00"),
        total=Decimal("45.18"),
        category_hint="MEALS",
        contains_alcohol_mention=False,
        has_itemized_lines=True,
        masked_card_hint="****-****-****-1104",
        merchant_confidence=0.95,
        date_confidence=0.94,
        total_confidence=0.96,
        currency_confidence=0.98,
        extraction_complete=True,
        extraction_source="replay",
        notes="Replay fixture: second part of potential split pair (combined > $75).",
    ),
}


class ReceiptExtractor(ABC):
    @abstractmethod
    def extract(self, file_name: str, mime_type: str, file_bytes: bytes) -> ExtractedReceipt:
        raise NotImplementedError


class ManualReviewExtractor(ReceiptExtractor):
    """Safe fallback when AI extraction is disabled or unavailable.
    Never fabricates a CLEAR verdict—marks extraction_complete=False so it routes to NEEDS_REVIEW.
    """

    def __init__(self, reason: str = "External AI processing disabled or unavailable.") -> None:
        self.reason = reason

    def extract(self, file_name: str, mime_type: str, file_bytes: bytes) -> ExtractedReceipt:
        return ExtractedReceipt(
            extraction_complete=False,
            extraction_source="manual_fallback",
            notes=mask_sensitive_text(self.reason),
        )


class ReplayReceiptExtractor(ReceiptExtractor):
    """Clearly labeled replay extractor for deterministic offline/demo runs."""

    def extract(self, file_name: str, mime_type: str, file_bytes: bytes) -> ExtractedReceipt:
        fixture = REPLAY_FIXTURES.get(file_name)
        if fixture:
            return fixture.model_copy(deep=True)
        return ExtractedReceipt(
            extraction_complete=False,
            extraction_source="replay",
            notes=f"No replay fixture registered for '{file_name}'. Routing to manual review.",
        )


class GeminiReceiptExtractor(ReceiptExtractor):
    def __init__(
        self,
        api_key: str = config.gemini_api_key,
        model_name: str = config.gemini_model,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.max_retries = max_retries

    def extract(self, file_name: str, mime_type: str, file_bytes: bytes) -> ExtractedReceipt:
        if not self.api_key:
            return ManualReviewExtractor("GEMINI_API_KEY not configured; routed to manual review.").extract(
                file_name, mime_type, file_bytes
            )

        client = genai.Client(api_key=self.api_key)
        last_error: Optional[str] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=[
                        types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                        EXTRACTION_PROMPT,
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ExtractedReceipt,
                        temperature=0.0,
                    ),
                )
                raw_text = (response.text or "").strip()
                if not raw_text:
                    last_error = "Empty response returned by Gemini."
                    continue

                parsed = ExtractedReceipt.model_validate(json.loads(raw_text))
                parsed.extraction_complete = True
                parsed.extraction_source = "gemini"
                if parsed.notes:
                    parsed.notes = mask_sensitive_text(parsed.notes)
                if parsed.masked_card_hint:
                    parsed.masked_card_hint = mask_sensitive_text(parsed.masked_card_hint)
                return parsed
            except Exception as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(0.8 * (attempt + 1))

        return ExtractedReceipt(
            extraction_complete=False,
            extraction_source="manual_fallback",
            notes=mask_sensitive_text(f"Gemini extraction failed after retries ({last_error})."),
        )