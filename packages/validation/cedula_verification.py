from __future__ import annotations

import re
from dataclasses import dataclass

from packages.shared.normalization import normalize_document_number
from packages.validation.dominican_cedula import is_dominican_cedula_checksum_valid


@dataclass(frozen=True)
class CedulaVerificationAssessment:
    outcome: str
    reason_code: str
    message: str


def assess_cedula_pair(
    roster_value: str,
    document_value: str,
    visual_identity_confirmed: bool,
) -> CedulaVerificationAssessment:
    roster_number = normalize_document_number(roster_value)
    document_number = normalize_document_number(document_value)
    if (
        roster_number is None
        or document_number is None
        or re.fullmatch(r"\d{11}", roster_number) is None
        or re.fullmatch(r"\d{11}", document_number) is None
    ):
        return CedulaVerificationAssessment(
            "NO_VERIFICABLE",
            "CEDULA_NO_LEGIBLE",
            "No se verificó: ambos valores deben contener 11 dígitos. Revisa los originales.",
        )

    if not is_dominican_cedula_checksum_valid(roster_number) or not is_dominican_cedula_checksum_valid(document_number):
        return CedulaVerificationAssessment(
            "REVISION",
            "DIGITO_CONTROL_NO_COINCIDE",
            "No se verificó: al menos un dígito de control no coincide. Puede ser un error de lectura o digitación.",
        )

    if roster_number != document_number:
        return CedulaVerificationAssessment(
            "REVISION",
            "NUMERO_DOCUMENTO_NO_COINCIDE",
            "Los números no coinciden. Revisa la transcripción y ambos documentos; no se rechaza automáticamente.",
        )

    if not visual_identity_confirmed:
        return CedulaVerificationAssessment(
            "REVISION",
            "ASOCIACION_PENDIENTE",
            "Los números coinciden, pero falta confirmar visualmente nombre, foto y asociación con el participante.",
        )

    return CedulaVerificationAssessment(
        "CORRECTO",
        "VERIFICACION_MANUAL_COMPLETA",
        "Verificación confirmada por el revisor: números coincidentes y asociación visual declarada.",
    )
