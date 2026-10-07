from __future__ import annotations

import re
from typing import Optional


def normalize_document_number(raw: Optional[str]) -> Optional[str]:
    """Normaliza un número de documento: quita espacios, guiones y separadores."""
    if raw is None:
        return None

    normalized = re.sub(r"[^A-Z0-9]", "", str(raw).strip().upper())
    return normalized or None


def normalize_person_name(raw: Optional[str]) -> Optional[str]:
    """Normaliza nombres y apellidos para comparación y OCR."""
    if raw is None:
        return None

    cleaned = " ".join(str(raw).strip().split())
    return cleaned or None


def is_document_legible(raw: Optional[str]) -> bool:
    """Indica si el número de documento se puede leer con confianza suficiente."""
    return normalize_document_number(raw) is not None and normalize_document_number(raw) != ""
