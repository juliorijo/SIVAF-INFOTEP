from __future__ import annotations

import importlib
import os

from packages.domain.contracts import OCRProvider


DEFAULT_OCR_FACTORY = "packages.ocr.hybrid_provider:create_hybrid_provider"


def load_ocr_provider() -> OCRProvider | None:
    factory_path = os.getenv("OCR_PROVIDER_FACTORY", "").strip()
    if not factory_path or factory_path.lower() == "auto":
        factory_path = DEFAULT_OCR_FACTORY

    module_name, separator, factory_name = factory_path.partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError("OCR_PROVIDER_FACTORY must use the format 'module.path:factory_name'")

    try:
        factory = getattr(importlib.import_module(module_name), factory_name)
        provider = factory()
        if not isinstance(provider, OCRProvider):
            raise TypeError("Configured OCR factory must return an OCRProvider")
        return provider
    except Exception:
        if factory_path == DEFAULT_OCR_FACTORY:
            return None
        raise
