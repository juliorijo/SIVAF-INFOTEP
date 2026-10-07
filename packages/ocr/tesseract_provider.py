from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
from typing import Any

import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from pytesseract import Output

from packages.domain.contracts import OCRDocumentText, OCRPageText, OCRProvider


class TesseractOCRProvider(OCRProvider):
    def __init__(self) -> None:
        executable = self._find_executable()
        if executable is None:
            raise RuntimeError(
                "Tesseract OCR is not installed; set TESSERACT_CMD to tesseract.exe"
            )
        pytesseract.pytesseract.tesseract_cmd = str(executable)
        self.languages = os.getenv("TESSERACT_LANGUAGES", "spa+eng")
        self.dpi = int(os.getenv("TESSERACT_DPI", "300"))
        self.page_segmentation_mode = int(os.getenv("TESSERACT_PSM", "3"))
        tessdata_dir = Path(os.getenv(
            "TESSERACT_TESSDATA_DIR",
            Path.home() / "AppData" / "Local" / "SIVAF" / "tessdata",
        )).expanduser()
        self.tessdata_config = (
            f"--tessdata-dir {tessdata_dir.resolve().as_posix()}"
            if tessdata_dir.is_dir()
            else ""
        )
        if not 100 <= self.dpi <= 400:
            raise ValueError("TESSERACT_DPI must be between 100 and 400")
        if not 3 <= self.page_segmentation_mode <= 13:
            raise ValueError("TESSERACT_PSM must be between 3 and 13")

    def extract_text(self, pdf_path: str) -> OCRDocumentText:
        pages: list[OCRPageText] = []
        with pdfium.PdfDocument(pdf_path) as document:
            for page_number, page in enumerate(document, start=1):
                bitmap = page.render(scale=self.dpi / 72)
                with bitmap.to_pil() as image:
                    text, confidence = self._read_page(image)
                pages.append(OCRPageText(
                    page_number=page_number,
                    text=text.strip(),
                    confidence=confidence,
                ))
                bitmap.close()
                page.close()

        return OCRDocumentText(pages=pages, provider="tesseract-local")

    def extract_document_images(self, pdf_path: str) -> list[dict[str, Any]]:
        return []

    def _read_page(self, image: Image.Image) -> tuple[str, float | None]:
        primary = self._read_with_mode(image, self.page_segmentation_mode)
        text, confidence = primary
        if confidence is not None and confidence >= 0.82 and (
            confidence >= 0.92 or not re.search(
                r"C[EÉ]DULA|DOCUMENTO|IDENTIDAD", text, re.IGNORECASE
            )
        ):
            return primary

        enhanced = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=1)
        enhanced = ImageEnhance.Contrast(enhanced).enhance(1.35)
        enhanced = enhanced.filter(ImageFilter.UnsharpMask(radius=1.2, percent=170, threshold=3))
        enhanced = enhanced.resize(
            (int(enhanced.width * 1.25), int(enhanced.height * 1.25)),
            Image.Resampling.LANCZOS,
        )
        with enhanced:
            alternatives = [
                self._read_with_mode(enhanced, mode)
                for mode in (6, 11)
            ]
        candidates = [primary, *alternatives]
        return max(candidates, key=self._page_read_score)

    def _read_with_mode(self, image: Image.Image, mode: int) -> tuple[str, float | None]:
        data = pytesseract.image_to_data(
            image,
            lang=self.languages,
            config=f"{self.tessdata_config} --oem 3 --psm {mode}".strip(),
            output_type=Output.DICT,
        )
        lines: dict[tuple[str, str, str], list[str]] = {}
        confidence_values: list[int] = []
        for index, raw_text in enumerate(data["text"]):
            text = raw_text.strip()
            raw_confidence = str(data["conf"][index])
            if not text:
                continue
            line_number = (
                str(data["block_num"][index]),
                str(data["par_num"][index]),
                str(data["line_num"][index]),
            )
            lines.setdefault(line_number, []).append(text)
            if raw_confidence.lstrip("-").isdigit() and int(raw_confidence) >= 0:
                confidence_values.append(int(raw_confidence))

        text = "\n".join(" ".join(words) for words in lines.values())
        if not confidence_values:
            return text, None
        confidence = sum(confidence_values) / (len(confidence_values) * 100)
        return text, confidence

    @staticmethod
    def _page_read_score(result: tuple[str, float | None]) -> tuple[int, int, int]:
        text, confidence = result
        candidate_count = len(re.findall(r"(?<!\d)\d{3}[-\s]?\d{7}[-\s]?\d(?!\d)", text))
        return int((confidence or 0.0) * 100), candidate_count, len(text)

    @staticmethod
    def _find_executable() -> Path | None:
        configured = os.getenv("TESSERACT_CMD")
        if configured:
            executable = Path(configured).expanduser()
            if executable.is_file():
                return executable
            raise RuntimeError(f"TESSERACT_CMD does not point to a file: {executable}")

        on_path = shutil.which("tesseract")
        if on_path:
            return Path(on_path)

        windows_install = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        return windows_install if windows_install.is_file() else None


def create_tesseract_provider() -> TesseractOCRProvider:
    return TesseractOCRProvider()
