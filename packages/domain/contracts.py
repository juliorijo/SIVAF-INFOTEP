from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional
from uuid import UUID

from .enums import ResultOutcome
from .models import FormativeAction, IdentityDocument, Participant, ProcessingJob, ValidationResult


@dataclass
class ExtractionContext:
    source_pdf_path: str
    job_id: UUID
    metadata: Dict[str, Any] | None = None


@dataclass(frozen=True)
class OCRPageText:
    page_number: int
    text: str
    confidence: float | None = None


@dataclass(frozen=True)
class OCRDocumentText:
    pages: List[OCRPageText]
    provider: str


class OCRProvider(ABC):
    @abstractmethod
    def extract_text(
        self,
        pdf_path: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> OCRDocumentText:
        raise NotImplementedError

    @abstractmethod
    def extract_document_images(self, pdf_path: str) -> List[Dict[str, Any]]:
        raise NotImplementedError


class PdfExtractionService(ABC):
    @abstractmethod
    def process(self, context: ExtractionContext) -> ProcessingJob:
        raise NotImplementedError


class FormativeActionIdentificationService(ABC):
    @abstractmethod
    def identify(self, raw_text: str, metadata: Optional[Dict[str, Any]] = None) -> FormativeAction:
        raise NotImplementedError


class ParticipantExtractionService(ABC):
    @abstractmethod
    def extract(self, raw_text: str, metadata: Optional[Dict[str, Any]] = None) -> List[Participant]:
        raise NotImplementedError


class DocumentExtractionService(ABC):
    @abstractmethod
    def extract(self, raw_text: str, metadata: Optional[Dict[str, Any]] = None) -> List[IdentityDocument]:
        raise NotImplementedError


class DocumentAssociationService(ABC):
    @abstractmethod
    def associate(
        self,
        participants: Iterable[Participant],
        documents: Iterable[IdentityDocument],
    ) -> Dict[str, Any]:
        raise NotImplementedError


class ValidationRuleEngine(ABC):
    @abstractmethod
    def evaluate(self, participant: Participant, document: Optional[IdentityDocument]) -> List[ValidationResult]:
        raise NotImplementedError


class ResultSummaryService(ABC):
    @abstractmethod
    def summarize(self, results: Iterable[ValidationResult]) -> Dict[str, Any]:
        raise NotImplementedError


class EvidenceStore(ABC):
    @abstractmethod
    def save_pdf_evidence(self, processing_job: ProcessingJob, file_path: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def save_page_image(self, page_number: int, image_path: str) -> str:
        raise NotImplementedError


class ReviewDecisionService(ABC):
    @abstractmethod
    def decide(self, participant: Participant, document: Optional[IdentityDocument], outcome: ResultOutcome) -> str:
        raise NotImplementedError
