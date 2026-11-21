from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from PIL import Image

from config import config

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_IMAGE_SIDE_PX = 8000

CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\w)")


@dataclass(frozen=True)
class IntakeResult:
    valid: bool
    file_name: str
    mime_type: str
    file_sha256: str
    file_bytes: bytes
    error: str | None = None


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mask_sensitive_text(text: str) -> str:
    """Best-effort text masking for known patterns (card numbers, emails, phones).
    Does not guarantee redaction of un-OCR'd pixels inside images.
    """
    if not text:
        return text

    def _mask_card(match: re.Match[str]) -> str:
        digits = "".join(ch for ch in match.group(0) if ch.isdigit())
        if len(digits) < 13:
            return match.group(0)
        return f"****-****-****-{digits[-4:]}"

    masked = CARD_PATTERN.sub(_mask_card, text)
    masked = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", masked)
    masked = PHONE_PATTERN.sub("[REDACTED_PHONE]", masked)
    return masked


def _count_pdf_pages_safely(data: bytes) -> int | None:
    if not data.startswith(b"%PDF-"):
        return None
    # Lightweight scan for /Type /Page objects without heavy external deps
    page_count = data.count(b"/Type/Page") + data.count(b"/Type /Page")
    return max(page_count, 1)


def validate_and_ingest(file_name: str, file_bytes: bytes) -> IntakeResult:
    sha = compute_sha256(file_bytes)
    ext = Path(file_name or "").suffix.lower()

    if not file_bytes:
        return IntakeResult(False, file_name, "application/octet-stream", sha, file_bytes, "Uploaded file is empty.")

    if len(file_bytes) > config.max_file_bytes:
        return IntakeResult(
            False,
            file_name,
            "application/octet-stream",
            sha,
            file_bytes,
            f"File exceeds maximum allowed size ({config.max_file_bytes // (1024 * 1024)} MB).",
        )

    if ext not in ALLOWED_EXTENSIONS:
        return IntakeResult(
            False,
            file_name,
            "application/octet-stream",
            sha,
            file_bytes,
            f"Unsupported file extension '{ext or 'none'}'. Allowed: PDF, PNG, JPG, JPEG.",
        )

    if ext == ".pdf":
        if not file_bytes.startswith(b"%PDF-"):
            return IntakeResult(
                False,
                file_name,
                "application/pdf",
                sha,
                file_bytes,
                "File does not appear to be a valid PDF document.",
            )
        pages = _count_pdf_pages_safely(file_bytes)
        if pages is not None and pages > config.max_pdf_pages:
            return IntakeResult(
                False,
                file_name,
                "application/pdf",
                sha,
                file_bytes,
                f"PDF has {pages} pages, exceeding the {config.max_pdf_pages}-page limit.",
            )
        return IntakeResult(True, file_name, "application/pdf", sha, file_bytes, None)

    # Image validation (.png, .jpg, .jpeg)
    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            img.verify()
        with Image.open(io.BytesIO(file_bytes)) as img_check:
            fmt = (img_check.format or "").upper()
            width, height = img_check.size
            if fmt not in {"PNG", "JPEG", "JPG"}:
                return IntakeResult(
                    False,
                    file_name,
                    "application/octet-stream",
                    sha,
                    file_bytes,
                    f"Disguised or unsupported image format: {fmt or 'unknown'}.",
                )
            if width <= 0 or height <= 0 or width > MAX_IMAGE_SIDE_PX or height > MAX_IMAGE_SIDE_PX:
                return IntakeResult(
                    False,
                    file_name,
                    "application/octet-stream",
                    sha,
                    file_bytes,
                    f"Image dimensions ({width}x{height}) are outside safe bounds.",
                )
            mime = "image/png" if fmt == "PNG" else "image/jpeg"
            return IntakeResult(True, file_name, mime, sha, file_bytes, None)
    except Exception as exc:
        return IntakeResult(False, file_name, "application/octet-stream", sha, file_bytes, f"Corrupted or unreadable image: {exc}")