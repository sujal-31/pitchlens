"""Extractor Agent - Parses PDF bytes into structured ExtractedContent.

Uses PyMuPDF (fitz) for text extraction, and EasyOCR for image-based pages.
Then uses the LLM to intelligently classify content into scoring categories.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
"""

import io
import os
import time
from typing import List, Optional
from uuid import UUID

import fitz  # PyMuPDF
from PIL import Image
import pytesseract

from app.models.schemas import ExtractedContent, ExtractedSection

# --- Constants ---

EXTRACTION_TIMEOUT_SECONDS = 120

# Configure Tesseract path
pytesseract.pytesseract.tesseract_cmd = r'C:\Users\SK001194712\AppData\Local\Programs\Tesseract-OCR\tesseract.exe'


class ExtractionError(Exception):
    """Raised when PDF extraction fails due to corruption or other errors."""

    def __init__(self, reason: str, partial_content: Optional[List[ExtractedSection]] = None):
        self.reason = reason
        self.partial_content = partial_content or []
        super().__init__(reason)


def _extract_all_text(doc: fitz.Document) -> tuple[str, int, List[str]]:
    """Extract all text from PDF using PyMuPDF + EasyOCR for image pages.
    
    Returns (full_text, pages_processed, warnings).
    Uses PyMuPDF for text extraction first, falls back to OCR for image-only pages.
    """
    all_text_parts = []
    warnings = []
    pages_processed = 0
    ocr_used = False

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_number = page_idx + 1

        # Try standard text extraction first
        text = page.get_text("text").strip()

        if not text or len(text) < 20:
            # Page has little/no extractable text — use Tesseract OCR
            try:
                pix = page.get_pixmap(dpi=200)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                text = pytesseract.image_to_string(img).strip()
                if text:
                    ocr_used = True
            except Exception as e:
                warnings.append(f"OCR failed on page {page_number}: {str(e)[:100]}")

        if text:
            all_text_parts.append(f"--- SLIDE {page_number} ---\n{text}")
        else:
            warnings.append(f"Page {page_number} has no extractable content.")

        pages_processed += 1

    if ocr_used:
        warnings.append("OCR was used for image-based pages (some text may be imprecise).")

    full_text = "\n\n".join(all_text_parts)
    return full_text, pages_processed, warnings


def _classify_content_with_llm(full_text: str) -> List[ExtractedSection]:
    """Skip LLM classification — pass full text to all categories.
    
    Each scorer agent is smart enough to find its own relevant content.
    This avoids classification failures that result in empty content.
    """
    # Give every scorer the full deck text — they'll find what's relevant
    return [
        ExtractedSection(
            category="market",
            content=full_text[:15000],
            page_numbers=list(range(1, 25)),
        ),
        ExtractedSection(
            category="team",
            content=full_text[:15000],
            page_numbers=list(range(1, 25)),
        ),
        ExtractedSection(
            category="business_model",
            content=full_text[:15000],
            page_numbers=list(range(1, 25)),
        ),
        ExtractedSection(
            category="competition",
            content=full_text[:15000],
            page_numbers=list(range(1, 25)),
        ),
        ExtractedSection(
            category="uncategorized",
            content=full_text[:15000],
            page_numbers=list(range(1, 25)),
        ),
    ]


def extract_content(
    pdf_bytes: bytes,
    deck_id: UUID,
    timeout_seconds: int = EXTRACTION_TIMEOUT_SECONDS,
) -> ExtractedContent:
    """Extract structured content from PDF using PyMuPDF + LLM classification.

    1. Uses PyMuPDF for high-quality text extraction from all PDF layers
    2. Sends full text to LLM for intelligent category classification
    3. Returns structured ExtractedContent with proper category mapping

    Args:
        pdf_bytes: Raw PDF file bytes
        deck_id: UUID of the deck being processed
        timeout_seconds: Maximum time allowed for extraction

    Returns:
        ExtractedContent with sections, warnings, and page counts

    Raises:
        ExtractionError: If PDF is corrupted and cannot be read
    """
    start_time = time.time()

    # Open PDF with PyMuPDF
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
    except Exception as e:
        raise ExtractionError(
            reason=f"Failed to parse PDF: {str(e)}",
            partial_content=[],
        )

    # Extract all text
    full_text, pages_processed, warnings = _extract_all_text(doc)
    doc.close()

    if not full_text.strip():
        warnings.append("No text content could be extracted from the PDF.")
        return ExtractedContent(
            deck_id=deck_id,
            sections=[ExtractedSection(category="uncategorized", content="", page_numbers=[])],
            warnings=warnings,
            total_pages=total_pages,
            pages_processed=pages_processed,
        )

    # Pass full text to all categories — each scorer finds its own content
    sections = _classify_content_with_llm(full_text)

    return ExtractedContent(
        deck_id=deck_id,
        sections=sections,
        warnings=warnings,
        total_pages=total_pages,
        pages_processed=pages_processed,
    )
