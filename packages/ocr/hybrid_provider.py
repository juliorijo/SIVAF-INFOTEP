from __future__ import annotations

import os
from typing import Any

import pypdfium2 as pdfium

from packages.domain.contracts import OCRDocumentText, OCRPageText, OCRProvider
from packages.ocr.tesseract_provider import TesseractOCRProvider

try:
    import numpy as np
    from paddleocr import PaddleOCR
except ImportError:  # pragma: no cover - optional dependency
    np = None
    PaddleOCR = None


class HybridOCRProvider(OCRProvider):
    """
    OCR provider that prefers PaddleOCR and falls back to Tesseract page-by-page.

    Useful for local-network deployments where scanned documents vary a lot in quality.
    """

    def __init__(self) -> None:
        self.paddle_enabled = os.getenv("OCR_USE_PADDLE", "true").lower() != "false"
        self.paddle_min_confidence = float(os.getenv("PADDLE_MIN_CONFIDENCE", "0.72"))
        self.dpi = int(os.getenv("PADDLE_DPI", os.getenv("TESSERACT_DPI", "260")))
        self.max_pages = int(os.getenv("OCR_MAX_PAGES", "0"))

        self._paddle = None
        if self.paddle_enabled and PaddleOCR is not None:
            paddle_lang = os.getenv("PADDLE_LANG", "es")
            self._paddle = PaddleOCR(
                lang=paddle_lang,
                use_angle_cls=False,
                show_log=False,
            )

        self._tesseract = TesseractOCRProvider()

    def extract_text(self, pdf_path: str, progress_callback=None) -> OCRDocumentText:
        pages: list[OCRPageText] = []
        with pdfium.PdfDocument(pdf_path) as document:
            total_pages = len(document)
            for page_number, page in enumerate(document, start=1):
                if self.max_pages > 0 and page_number > self.max_pages:
                    page.close()
                    break
                bitmap = page.render(scale=self.dpi / 72)
                with bitmap.to_pil() as image:
                    text, confidence, source = self._read_page_hybrid(image)
                pages.append(
                    OCRPageText(
                        page_number=page_number,
                        text=text.strip(),
                        confidence=confidence,
                    )
                )
                if progress_callback is not None and total_pages > 0:
                    progress_callback(page_number, total_pages)
                bitmap.close()
                page.close()

        provider_name = (
            "paddleocr-local+tesseract-fallback"
            if self._paddle is not None
            else "tesseract-local"
        )
        return OCRDocumentText(pages=pages, provider=provider_name)

    def extract_document_images(self, pdf_path: str) -> list[dict[str, Any]]:
        return []

    def _read_page_hybrid(self, image) -> tuple[str, float | None, str]:
        paddle_text, paddle_confidence = self._read_with_paddle(image)
        if (
            paddle_text
            and paddle_confidence is not None
            and paddle_confidence >= self.paddle_min_confidence
        ):
            return paddle_text, paddle_confidence, "paddle"

        tesseract_text, tesseract_confidence = self._tesseract._read_page(image)
        if tesseract_text:
            return tesseract_text, tesseract_confidence, "tesseract"
        return paddle_text, paddle_confidence, "paddle"

    def _read_with_paddle(self, image) -> tuple[str, float | None]:
        if self._paddle is None or np is None:
            return "", None
        result = self._paddle.ocr(np.array(image), cls=False)
        if not result:
            return "", None

        lines: list[str] = []
        scores: list[float] = []
        for block in result:
            if not block:
                continue
            for item in block:
                if not item or len(item) < 2:
                    continue
                text_info = item[1]
                if not text_info or len(text_info) < 2:
                    continue
                text = str(text_info[0]).strip()
                score = float(text_info[1])
                if not text:
                    continue
                lines.append(text)
                scores.append(score)

        if not lines:
            return "", None
        confidence = sum(scores) / len(scores) if scores else None
        return "\n".join(lines), confidence


def create_hybrid_provider() -> HybridOCRProvider:
    return HybridOCRProvider()
