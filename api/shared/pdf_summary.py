"""Bounded, text-only PDF extraction for LINE document summaries."""
from __future__ import annotations

from io import BytesIO
from typing import Any

from pypdf import PdfReader

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_EXTRACTED_PAGES = 40
MAX_EXTRACTED_CHARS = 18_000


class PdfSummaryError(ValueError):
    """A safe error whose message can be shown to the LINE user."""


def extract_pdf_text(raw: bytes) -> dict[str, Any]:
    """Extract bounded text without executing actions or following document instructions."""
    if not raw or len(raw) > MAX_PDF_BYTES:
        raise PdfSummaryError("PDF 必須小於 10 MB。")
    if not raw.lstrip().startswith(b"%PDF-"):
        raise PdfSummaryError("這個檔案不是有效的 PDF。")
    try:
        reader = PdfReader(BytesIO(raw), strict=False)
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = 0
            if not unlocked:
                raise PdfSummaryError("目前無法摘要有密碼保護的 PDF。")
        page_count = len(reader.pages)
        if page_count < 1:
            raise PdfSummaryError("PDF 沒有可讀取的頁面。")
        if page_count > MAX_PDF_PAGES:
            raise PdfSummaryError(f"PDF 共 {page_count} 頁，超過目前 100 頁的限制。")

        chunks: list[str] = []
        extracted_chars = 0
        pages_processed = 0
        for index in range(min(page_count, MAX_EXTRACTED_PAGES)):
            if extracted_chars >= MAX_EXTRACTED_CHARS:
                break
            pages_processed += 1
            text = str(reader.pages[index].extract_text() or "").replace("\x00", "").strip()
            if not text:
                continue
            remaining = MAX_EXTRACTED_CHARS - extracted_chars
            page_text = text[:remaining]
            chunks.append(f"[第 {index + 1} 頁]\n{page_text}")
            extracted_chars += len(page_text)
    except PdfSummaryError:
        raise
    except Exception as exc:
        raise PdfSummaryError("PDF 解析失敗，可能檔案已損壞或格式不受支援。") from exc

    extracted = "\n\n".join(chunks).strip()
    if not extracted:
        raise PdfSummaryError("PDF 沒有可擷取的文字；掃描型 PDF 目前需要先做 OCR。")
    return {
        "text": extracted,
        "page_count": page_count,
        "pages_processed": pages_processed,
        "truncated": page_count > pages_processed or extracted_chars >= MAX_EXTRACTED_CHARS,
    }
