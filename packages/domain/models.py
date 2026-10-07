from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from .enums import DocumentType, JobStatus, ResultOutcome, RuleCode, Severity


@dataclass
class FormativeAction:
    id: UUID = field(default_factory=uuid4)
    external_code: str = ""
    name: Optional[str] = None
    center: Optional[str] = None
    facilitator: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    schedule: Optional[str] = None
    participant_count: Optional[int] = None
    status: str = "PENDING"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Participant:
    id: UUID = field(default_factory=uuid4)
    formative_action_id: UUID | None = None
    position_number: Optional[int] = None
    list_document_number: Optional[str] = None
    list_full_name: Optional[str] = None
    extracted_name: Optional[str] = None
    extracted_last_names: Optional[str] = None
    nationality: Optional[str] = None
    is_foreign: bool = False
    status: str = "PENDING"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class IdentityDocument:
    id: UUID = field(default_factory=uuid4)
    participant_id: UUID | None = None
    document_type: DocumentType = DocumentType.OTRO
    document_number_normalized: Optional[str] = None
    document_number_raw: Optional[str] = None
    extracted_name: Optional[str] = None
    extracted_last_names: Optional[str] = None
    page_number: Optional[int] = None
    image_path: Optional[str] = None
    source_pdf_id: Optional[UUID] = None
    ocr_confidence: Optional[float] = None
    is_annotated: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ProcessingJob:
    id: UUID = field(default_factory=uuid4)
    source_pdf_path: str = ""
    original_file_hash: str = ""
    status: JobStatus = JobStatus.QUEUED
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationRule:
    id: UUID = field(default_factory=uuid4)
    code: RuleCode = RuleCode.DIFERENCIA_DETECTADA
    title: str = ""
    description: str = ""
    severity: Severity = Severity.MEDIUM
    enabled: bool = True
    version: str = "1.0"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ValidationResult:
    id: UUID = field(default_factory=uuid4)
    job_id: UUID | None = None
    participant_id: UUID | None = None
    identity_document_id: UUID | None = None
    rule_id: UUID | None = None
    outcome: ResultOutcome = ResultOutcome.CORRECTO
    reason_code: RuleCode | None = None
    message: str = ""
    evidence_ref: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Incident:
    id: UUID = field(default_factory=uuid4)
    formative_action_id: UUID | None = None
    participant_id: UUID | None = None
    document_id: UUID | None = None
    severity: Severity = Severity.MEDIUM
    reason_code: RuleCode | None = None
    description: str = ""
    page_number: Optional[int] = None
    evidence_ref: Optional[str] = None
    status: str = "OPEN"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Review:
    id: UUID = field(default_factory=uuid4)
    incident_id: UUID | None = None
    reviewer_user_id: UUID | None = None
    review_status: str = "PENDING"
    comments: str = ""
    reviewed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AuditLog:
    id: UUID = field(default_factory=uuid4)
    entity_type: str = ""
    entity_id: UUID | None = None
    action: str = ""
    user_id: Optional[UUID] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
