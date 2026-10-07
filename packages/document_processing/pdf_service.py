from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Sequence

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from packages.domain.contracts import OCRProvider, OCRPageText

MAX_PDF_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_PDF_RASTER_PIXELS = 40_000_000


class PdfUploadLimitError(ValueError):
    pass


@dataclass(frozen=True)
class PdfTextExtraction:
    pages: Sequence[OCRPageText]
    source: str
    provider: str | None = None

    @property
    def full_text(self) -> str:
        return "\n".join(page.text for page in self.pages if page.text.strip())


class PdfIngestionService:
    """Guarda un PDF original en almacenamiento local y extrae metadatos básicos."""

    def __init__(
        self,
        storage_dir: str | os.PathLike[str] | None = None,
        max_pdf_bytes: int = MAX_PDF_UPLOAD_BYTES,
        max_pdf_pages: int = MAX_PDF_PAGES,
        max_pdf_raster_pixels: int = MAX_PDF_RASTER_PIXELS,
    ):
        base_dir = storage_dir or os.getenv("INFOTEP_STORAGE_DIR", "./storage")
        self.storage_dir = Path(base_dir).expanduser().resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.max_pdf_bytes = max_pdf_bytes
        self.max_pdf_pages = max_pdf_pages
        self.max_pdf_raster_pixels = max_pdf_raster_pixels

    def store_pdf(self, job_id: str, file_name: str, file_obj: BinaryIO) -> dict[str, object]:
        file_bytes = file_obj.read(self.max_pdf_bytes + 1)
        if len(file_bytes) > self.max_pdf_bytes:
            raise PdfUploadLimitError(f"PDF exceeds the {self.max_pdf_bytes}-byte upload limit")
        if not file_bytes.startswith(b"%PDF-"):
            raise ValueError("Uploaded file does not have a valid PDF signature")
        sanitized_name = self._sanitize_filename(file_name)
        destination = self.storage_dir / f"{job_id}_{sanitized_name}"
        destination.write_bytes(file_bytes)
        try:
            page_count = self._read_page_count(destination)
        except (PdfReadError, ValueError) as exc:
            destination.unlink(missing_ok=True)
            if isinstance(exc, PdfUploadLimitError):
                raise
            raise ValueError("Uploaded file is not a readable PDF") from exc
        action_code = self._detect_action_code(file_name)
        return {
            "storage_path": str(destination),
            "file_name": sanitized_name,
            "file_size": len(file_bytes),
            "sha256": hashlib.sha256(file_bytes).hexdigest(),
            "page_count": page_count,
            "action_code": action_code,
        }

    def inspect_existing_pdf(self, pdf_path: str | os.PathLike[str]) -> dict[str, object]:
        file_path = Path(pdf_path)
        if not file_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        file_size = file_path.stat().st_size
        if file_size > self.max_pdf_bytes:
            raise PdfUploadLimitError(f"PDF exceeds the {self.max_pdf_bytes}-byte processing limit")
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "storage_path": str(file_path),
            "file_size": file_size,
            "sha256": digest.hexdigest(),
            "page_count": self._read_page_count(file_path),
            "action_code": self._detect_action_code(file_path.name),
        }

    def extract_text(
        self,
        pdf_path: str | os.PathLike[str],
        ocr_provider: OCRProvider | None = None,
    ) -> PdfTextExtraction:
        file_path = Path(pdf_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        with file_path.open("rb") as handle:
            reader = PdfReader(handle)
            pages = [
                OCRPageText(page_number=index, text=page.extract_text() or "")
                for index, page in enumerate(reader.pages, start=1)
            ]

        if any(page.text.strip() for page in pages):
            return PdfTextExtraction(pages=pages, source="embedded_text")

        if ocr_provider is None:
            return PdfTextExtraction(pages=pages, source="ocr_not_configured")

        ocr_result = ocr_provider.extract_text(str(file_path))
        if not ocr_result.pages:
            raise ValueError("OCR provider returned no page results")
        if any(page.page_number < 1 for page in ocr_result.pages):
            raise ValueError("OCR provider returned an invalid page number")
        if any(page.confidence is not None and not 0 <= page.confidence <= 1 for page in ocr_result.pages):
            raise ValueError("OCR provider confidence must be between 0 and 1")

        return PdfTextExtraction(
            pages=ocr_result.pages,
            source="ocr",
            provider=ocr_result.provider,
        )

    @staticmethod
    def _sanitize_filename(file_name: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", file_name.strip())
        return sanitized or "document.pdf"

    def _read_page_count(self, pdf_path: str | os.PathLike[str]) -> int:
        with open(pdf_path, "rb") as handle:
            reader = PdfReader(handle)
            page_count = len(reader.pages)
            if page_count > self.max_pdf_pages:
                raise PdfUploadLimitError(f"PDF exceeds the {self.max_pdf_pages}-page limit")
            for page in reader.pages:
                page_area = float(page.mediabox.width) * float(page.mediabox.height)
                if page_area * (400 / 72) ** 2 > self.max_pdf_raster_pixels:
                    raise PdfUploadLimitError(
                        "PDF contains a page too large to rasterize safely"
                    )
            return page_count

    @staticmethod
    def _detect_action_code(file_name: str) -> str | None:
        matches = re.findall(r"(?:ACCI(?:O|ÓN)\s*FORMATIVA[:\s-]*)?(\d{4}-\d{5,8})", file_name, flags=re.IGNORECASE)
        if matches:
            return matches[0]

        compact = re.sub(r"[^0-9-]", "", file_name)
        if re.search(r"\d{4}-\d{5,8}", compact):
            return compact[compact.rfind("20") :]

        return None
