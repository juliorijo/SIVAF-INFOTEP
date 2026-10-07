from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional
from uuid import UUID, uuid4

from packages.domain.enums import DocumentType, ResultOutcome, RuleCode
from packages.domain.models import IdentityDocument, Participant, ValidationResult
from packages.shared.normalization import normalize_document_number


@dataclass(frozen=True)
class ValidationContext:
    job_id: Optional[UUID] = None
    participant_id: Optional[UUID] = None
    document_id: Optional[UUID] = None


class ValidationEngine:
    """Evalúa reglas principales de validación documental para una acción formativa."""

    def evaluate(
        self,
        participant: Optional[Participant],
        document: Optional[IdentityDocument] = None,
        *,
        context: Optional[ValidationContext] = None,
    ) -> List[ValidationResult]:
        if participant is None:
            return []

        context = context or ValidationContext()
        list_number = normalize_document_number(participant.list_document_number)
        document_number = normalize_document_number(document.document_number_normalized if document else None)

        if participant.is_foreign:
            return self._evaluate_foreign_participant(participant, document, context)

        if document is None:
            if list_number:
                return [
                    self._build_result(
                        outcome=ResultOutcome.INCIDENCIA,
                        reason_code=RuleCode.CEDULA_FALTANTE,
                        message="CÉDULA FALTANTE",
                        context=context,
                        participant_id=participant.id,
                    )
                ]
            return []

        if document_number is None:
            return [
                self._build_result(
                    outcome=ResultOutcome.NO_VERIFICABLE,
                    reason_code=RuleCode.CEDULA_NO_LEGIBLE,
                    message="CÉDULA NO LEGIBLE",
                    context=context,
                    participant_id=participant.id,
                    document_id=document.id,
                )
            ]

        if list_number and list_number != document_number:
            return [
                self._build_result(
                    outcome=ResultOutcome.INCIDENCIA,
                    reason_code=RuleCode.NUMERO_DOCUMENTO_NO_COINCIDE,
                    message=f"Número de cédula no coincide. Esperado: {list_number}; encontrado: {document_number}",
                    context=context,
                    participant_id=participant.id,
                    document_id=document.id,
                )
            ]

        if list_number and list_number == document_number:
            return [
                self._build_result(
                    outcome=ResultOutcome.CORRECTO,
                    reason_code=RuleCode.NUMERO_DOCUMENTO_NO_COINCIDE,
                    message="Cédula correcta",
                    context=context,
                    participant_id=participant.id,
                    document_id=document.id,
                )
            ]

        return [
            self._build_result(
                outcome=ResultOutcome.INCIDENCIA,
                reason_code=RuleCode.DOCUMENTO_NO_ASOCIADO,
                message="Documento detectado sin asociación clara a un participante",
                context=context,
                participant_id=participant.id,
                document_id=document.id,
            )
        ]

    def _evaluate_foreign_participant(
        self,
        participant: Participant,
        document: Optional[IdentityDocument],
        context: ValidationContext,
    ) -> List[ValidationResult]:
        if document is None:
            return [
                self._build_result(
                    outcome=ResultOutcome.INCIDENCIA,
                    reason_code=RuleCode.DOCUMENTO_NO_ASOCIADO,
                    message="Participante extranjero sin pasaporte asociado",
                    context=context,
                    participant_id=participant.id,
                )
            ]

        if document.document_type != DocumentType.PASAPORTE:
            return [
                self._build_result(
                    outcome=ResultOutcome.REVISION,
                    reason_code=RuleCode.DOCUMENTO_EXTRANJERO_NO_PASAPORTE,
                    message="PARTICIPANTE EXTRANJERO CON DOCUMENTO DISTINTO A PASAPORTE",
                    context=context,
                    participant_id=participant.id,
                    document_id=document.id,
                )
            ]

        if normalize_document_number(document.document_number_normalized) is None:
            return [
                self._build_result(
                    outcome=ResultOutcome.NO_VERIFICABLE,
                    reason_code=RuleCode.CEDULA_NO_LEGIBLE,
                    message="PASAPORTE NO LEGIBLE",
                    context=context,
                    participant_id=participant.id,
                    document_id=document.id,
                )
            ]

        expected = normalize_document_number(participant.list_document_number)
        actual = normalize_document_number(document.document_number_normalized)
        if expected and actual and expected != actual:
            return [
                self._build_result(
                    outcome=ResultOutcome.INCIDENCIA,
                    reason_code=RuleCode.NUMERO_DOCUMENTO_NO_COINCIDE,
                    message=f"Número de pasaporte no coincide. Esperado: {expected}; encontrado: {actual}",
                    context=context,
                    participant_id=participant.id,
                    document_id=document.id,
                )
            ]

        return [
            self._build_result(
                outcome=ResultOutcome.CORRECTO,
                reason_code=RuleCode.NUMERO_DOCUMENTO_NO_COINCIDE,
                message="Pasaporte correcto",
                context=context,
                participant_id=participant.id,
                document_id=document.id,
            )
        ]

    def detect_duplicate_documents(self, participants: Iterable[Participant]) -> List[ValidationResult]:
        seen: dict[str, Participant] = {}
        results: List[ValidationResult] = []

        for participant in participants:
            normalized = normalize_document_number(participant.list_document_number)
            if not normalized:
                continue
            if normalized in seen:
                results.append(
                    self._build_result(
                        outcome=ResultOutcome.INCIDENCIA,
                        reason_code=RuleCode.CEDULA_DUPLICADA,
                        message=f"Cédula duplicada detectada: {normalized}",
                        context=ValidationContext(),
                        participant_id=participant.id,
                    )
                )
                continue
            seen[normalized] = participant

        return results

    @staticmethod
    def _build_result(
        *,
        outcome: ResultOutcome,
        reason_code: RuleCode,
        message: str,
        context: ValidationContext,
        participant_id: Optional[UUID] = None,
        document_id: Optional[UUID] = None,
    ) -> ValidationResult:
        return ValidationResult(
            id=uuid4(),
            job_id=context.job_id,
            participant_id=participant_id,
            identity_document_id=document_id,
            reason_code=reason_code,
            outcome=outcome,
            message=message,
        )
