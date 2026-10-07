from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import csv
import io
import json
import os
from pathlib import Path
import re
import secrets
import time
import unicodedata
from zipfile import BadZipFile
from typing import Any, Dict, List
from uuid import UUID, uuid4, uuid5

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import pypdfium2 as pdfium
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from starlette.concurrency import run_in_threadpool

from apps.api.auth import verify_password
from apps.api.database import (
    AuditEventORM,
    FormativeActionORM,
    FormativeActionImportORM,
    HumanReviewORM,
    ProcessingJobORM,
    SessionLocal,
    UserORM,
    UserSessionORM,
    ValidationResultORM,
    init_db,
)
from packages.document_processing.pdf_service import (
    MAX_PDF_RASTER_PIXELS,
    PdfIngestionService,
    PdfUploadLimitError,
)
from packages.domain.enums import JobStatus, ResultOutcome, RuleCode
from packages.ocr.registry import load_ocr_provider
from packages.shared.normalization import normalize_document_number
from packages.validation.dominican_cedula import is_dominican_cedula_checksum_valid
from packages.validation.cedula_verification import assess_cedula_pair

app = FastAPI(
    title="SIVAF | Sistema de Verificación de Acciones Formativas",
    version="0.1.0",
    description="API de SIVAF para la verificación documental de acciones formativas.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

pdf_service = PdfIngestionService()
ocr_provider = None
AUTH_COOKIE_NAME = "sivaf_session"
AUTH_SESSION_SECONDS = 8 * 60 * 60
AUTH_COOKIE_SECURE = os.getenv("SIVAF_COOKIE_SECURE", "false").lower() == "true"
MAX_ACTION_IMPORT_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_METADATA_BYTES = 16 * 1024
MAX_ACTION_IMPORT_ROWS = 50_000
ACTION_FIELD_ALIASES = {
    "action_code": {
        "codigo", "codigo accion", "codigo de accion", "codigo accion formativa",
        "numero accion", "numero de accion", "no accion", "nro accion",
        "num accion", "id accion", "codigo c",
    },
    "name": {
        "accion formativa", "nombre accion", "nombre de accion", "nombre",
        "nombre actividad", "nombre del curso", "curso", "denominacion",
        "denominacion accion", "accion f",
    },
    "start_date": {"fecha inicio", "fecha de inicio", "inicio", "fecha inicial", "fecha ini"},
    "status": {"estado", "estatus", "situacion", "status"},
}


@app.on_event("startup")
def startup_db() -> None:
    global ocr_provider
    init_db()
    ocr_provider = load_ocr_provider()


init_db()


class CreateJobRequest(BaseModel):
    source_pdf_path: str = Field(..., min_length=1, description="Ruta del PDF a procesar")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos adicionales del trabajo")


class ProcessJobRequest(BaseModel):
    force: bool = Field(default=False, description="Forzar el re-procesamiento del PDF")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos del procesamiento")


class HumanReviewRequest(BaseModel):
    comments: str = Field(default="", max_length=4000)
    final_status: str | None = Field(default=None)


class CedulaVerificationRequest(BaseModel):
    participant_reference: str = Field(..., min_length=1, max_length=32)
    roster_page: int = Field(..., ge=1)
    document_page: int = Field(..., ge=1)
    roster_cedula: str = Field(..., min_length=1, max_length=32)
    document_cedula: str = Field(..., min_length=1, max_length=32)
    visual_identity_confirmed: bool = False


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=1, max_length=1024)


FINAL_STATUSES = {"APROBADA", "DEVUELTA", "MODIFICACION", "OTRO"}


def get_current_user(request: Request) -> UserORM:
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with SessionLocal() as session:
        auth_session = session.get(UserSessionORM, token_hash)
        if auth_session is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")
        if auth_session.expires_at <= time.time():
            session.delete(auth_session)
            session.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")

        user = session.get(UserORM, auth_session.user_id)
        if user is None or not user.is_active:
            session.delete(auth_session)
            session.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")
        return user


def require_admin(current_user: UserORM = Depends(get_current_user)) -> UserORM:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    return current_user


def get_accessible_job(session, job_id: str, current_user: UserORM) -> ProcessingJobORM:
    job = session.get(ProcessingJobORM, job_id)
    if job is None or (
        current_user.role != "admin"
        and job.created_by != current_user.id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processing job not found")
    return job


def audit_evidence_access(job_id: str, actor: str, action: str, details: Dict[str, Any]) -> None:
    with SessionLocal() as session:
        session.add(AuditEventORM(
            id=str(uuid4()),
            job_id=job_id,
            actor=actor,
            action=action,
            details=sanitize_json(details),
            created_at=datetime.now(timezone.utc),
        ))
        session.commit()


def normalize_action_header(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", text.lower()).split())


def normalize_spreadsheet_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def parse_action_import(filename: str, content: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        try:
            rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"), newline="")))
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="El CSV debe estar guardado como UTF-8.") from exc
    elif suffix == ".xlsx":
        try:
            from openpyxl import load_workbook
            from openpyxl.utils.exceptions import InvalidFileException

            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            worksheet = workbook.active
            rows = list(worksheet.iter_rows(values_only=True))
            workbook.close()
        except ImportError as exc:
            raise HTTPException(status_code=500, detail="Falta instalar la dependencia openpyxl para leer Excel.") from exc
        except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="No se pudo leer el archivo Excel .xlsx.") from exc
    else:
        raise HTTPException(status_code=400, detail="Usa un archivo .xlsx o .csv exportado desde Drive.")

    if not rows:
        raise HTTPException(status_code=400, detail="El archivo no contiene filas.")

    def locate_header(values: Any) -> tuple[list[str], dict[str, int], dict[str, int]] | None:
        candidate_headers = [str(value).strip().strip('"') if value is not None else "" for value in values]
        header_indexes = {
            normalize_action_header(header): index
            for index, header in enumerate(candidate_headers)
            if normalize_action_header(header)
        }
        mapped = {}
        for field, aliases in ACTION_FIELD_ALIASES.items():
            exact = next((header_indexes[alias] for alias in aliases if alias in header_indexes), None)
            if exact is None:
                partial_matches = [
                    index for normalized, index in header_indexes.items()
                    if len(normalized) >= 5 and any(alias.startswith(normalized) or normalized.startswith(alias) for alias in aliases)
                ]
                exact = partial_matches[0] if len(set(partial_matches)) == 1 else None
            mapped[field] = exact
        if mapped["action_code"] is not None:
            return candidate_headers, header_indexes, mapped
        return None

    header_location = None
    for row_index, values in enumerate(rows[:50]):
        header_location = locate_header(values)
        if header_location:
            break
    if header_location is None:
        raise HTTPException(
            status_code=400,
            detail="No se encontró la fila de encabezados con un código de acción. Revisa que el CSV incluya sus columnas.",
        )
    headers, _, mapped_indexes = header_location
    if mapped_indexes["action_code"] is None:
        raise HTTPException(
            status_code=400,
            detail="No se encontró una columna de código de acción (por ejemplo: Código de acción o No. Acción).",
        )

    records: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for row_number, values in enumerate(rows[row_index + 1:], start=row_index + 2):
        if not any(value is not None and str(value).strip() for value in values):
            continue
        if len(records) >= MAX_ACTION_IMPORT_ROWS:
            raise HTTPException(status_code=400, detail=f"El archivo supera el máximo de {MAX_ACTION_IMPORT_ROWS} registros.")

        fields = {
            header: normalize_spreadsheet_value(values[index] if index < len(values) else None)
            for index, header in enumerate(headers)
            if header
        }
        code_index = mapped_indexes["action_code"]
        action_code = str(values[code_index] if code_index < len(values) else "").strip()
        if not action_code:
            raise HTTPException(status_code=400, detail=f"Falta el código de acción en la fila {row_number}.")
        if action_code in seen_codes:
            raise HTTPException(status_code=400, detail=f"El código de acción {action_code} está duplicado en el archivo.")
        seen_codes.add(action_code)

        def mapped_value(field: str) -> str | None:
            index = mapped_indexes[field]
            if index is None or index >= len(values) or values[index] is None:
                return None
            return str(normalize_spreadsheet_value(values[index])).strip() or None

        records.append({
            "action_code": action_code,
            "name": mapped_value("name") or "",
            "start_date": mapped_value("start_date"),
            "status": mapped_value("status"),
            "fields": fields,
        })
    if not records:
        raise HTTPException(status_code=400, detail="No se encontraron registros de acciones formativas.")
    columns = [header for header in headers if header]
    return records, columns


def is_managed_evidence_available(source_pdf_path: str) -> bool:
    evidence_path = Path(source_pdf_path).resolve()
    try:
        evidence_path.relative_to(pdf_service.storage_dir.resolve())
    except ValueError:
        return False
    return evidence_path.is_file()


def render_pdf_page_preview(source_pdf_path: str, page_number: int) -> tuple[bytes, int]:
    with pdfium.PdfDocument(source_pdf_path) as document:
        page_count = len(document)
        if page_number < 1 or page_number > page_count:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"PDF page must be between 1 and {page_count}.",
            )
        page = document[page_number - 1]
        scale = 1.5
        if page.get_width() * page.get_height() * scale**2 > MAX_PDF_RASTER_PIXELS:
            page.close()
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="PDF page exceeds the safe preview raster limit.",
            )
        bitmap = page.render(scale=scale)
        try:
            with bitmap.to_pil() as image:
                output = io.BytesIO()
                image.save(output, format="PNG", optimize=True)
                return output.getvalue(), page_count
        finally:
            bitmap.close()
            page.close()


def serialize_processing_job(row: ProcessingJobORM, review: HumanReviewORM | None = None) -> Dict[str, Any]:
    return {
        "id": row.id,
        "source_pdf_name": Path(row.source_pdf_path).name,
        "original_file_hash": row.original_file_hash,
        "status": row.status,
        "queued_at": row.queued_at.isoformat() if row.queued_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "created_by": row.created_by,
        "metadata": row.payload_metadata or {},
        "evidence_available": is_managed_evidence_available(row.source_pdf_path),
        "human_review": {
            "reviewer": review.reviewer,
            "comments": review.comments,
            "final_status": review.final_status,
            "reviewed_at": review.reviewed_at.isoformat(),
        } if review else None,
    }


def serialize_validation_result(row: ValidationResultORM) -> Dict[str, Any]:
    evidence_ref = row.evidence_ref
    if evidence_ref and re.match(r"^(?:[A-Za-z]:[\\/]|/)", evidence_ref):
        evidence_ref = Path(evidence_ref).name
    return {
        "id": row.id,
        "job_id": row.job_id,
        "participant_id": row.participant_id,
        "identity_document_id": row.identity_document_id,
        "rule_id": row.rule_id,
        "outcome": row.outcome,
        "reason_code": row.reason_code,
        "message": row.message,
        "evidence_ref": evidence_ref,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def find_cedula_candidates(text: str) -> list[str]:
    return sorted(set(re.findall(r"(?<!\d)\d{3}[-\s]?\d{7}[-\s]?\d(?!\d)", text)))


def summarize_document_candidates(pages) -> Dict[str, Any]:
    roster_by_page: dict[int, set[str]] = {}
    evidence_by_page: dict[int, set[str]] = {}
    low_confidence_evidence_candidates: set[str] = set()
    confident_roster_numbers: set[str] = set()
    confident_evidence_numbers: set[str] = set()
    roster_checksum_valid_numbers: set[str] = set()
    evidence_checksum_valid_numbers: set[str] = set()
    roster_checksum_invalid_numbers: set[str] = set()
    evidence_checksum_invalid_numbers: set[str] = set()

    for page in pages:
        numbers = {
            normalized
            for candidate in find_cedula_candidates(page.text)
            if (normalized := normalize_document_number(candidate))
        }
        if not numbers:
            continue

        text = page.text.upper()
        has_document_label = bool(re.search(r"C[EÉ]DULA|DOCUMENTO|IDENTIDAD", text))
        has_list_label = bool(re.search(r"LISTA|N[ÓO]MINA|RELACI[ÓO]N", text))
        has_participant_label = bool(re.search(r"PARTICIPANTE|ALUMNO|ESTUDIANTE", text))
        has_name_label = bool(re.search(r"NOMBRE|APELLIDO", text))
        is_roster_page = has_document_label and (
            (has_list_label and has_participant_label)
            or (has_participant_label and has_name_label and len(numbers) > 1)
        )

        if is_roster_page:
            roster_by_page[page.page_number] = numbers
            for number in numbers:
                if is_dominican_cedula_checksum_valid(number):
                    roster_checksum_valid_numbers.add(number)
                    if page.confidence is not None and page.confidence >= 0.8:
                        confident_roster_numbers.add(number)
                else:
                    roster_checksum_invalid_numbers.add(number)
        else:
            evidence_by_page[page.page_number] = numbers
            for number in numbers:
                if is_dominican_cedula_checksum_valid(number):
                    evidence_checksum_valid_numbers.add(number)
                    if page.confidence is not None and page.confidence >= 0.8:
                        confident_evidence_numbers.add(number)
                else:
                    evidence_checksum_invalid_numbers.add(number)
            if page.confidence is None or page.confidence < 0.8:
                low_confidence_evidence_candidates.update(numbers)

    roster_numbers = set().union(*roster_by_page.values()) if roster_by_page else set()
    evidence_numbers = set().union(*evidence_by_page.values()) if evidence_by_page else set()
    confident_matches = confident_roster_numbers & confident_evidence_numbers
    return {
        "cedula_candidate_count": len(roster_numbers | evidence_numbers),
        "cedula_candidate_pages": sorted(roster_by_page.keys() | evidence_by_page.keys()),
        "roster_candidate_count": len(roster_numbers),
        "roster_candidate_pages": sorted(roster_by_page),
        "evidence_candidate_count": len(evidence_numbers),
        "evidence_candidate_pages": sorted(evidence_by_page),
        "cedula_checksum_valid_count": len(roster_checksum_valid_numbers | evidence_checksum_valid_numbers),
        "cedula_checksum_invalid_count": len(roster_checksum_invalid_numbers | evidence_checksum_invalid_numbers),
        "roster_checksum_valid_count": len(roster_checksum_valid_numbers),
        "roster_checksum_invalid_count": len(roster_checksum_invalid_numbers),
        "evidence_checksum_valid_count": len(evidence_checksum_valid_numbers),
        "evidence_checksum_invalid_count": len(evidence_checksum_invalid_numbers),
        "candidate_matches": len(confident_matches),
        "roster_candidates_without_document_candidate": len(confident_roster_numbers - confident_evidence_numbers),
        "evidence_candidates_without_roster_candidate": len(confident_evidence_numbers - confident_roster_numbers),
        "low_confidence_evidence_candidates": len(low_confidence_evidence_candidates),
        "verified_identities": 0,
        "identity_association_requires_human_review": True,
    }


def sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_json(val) for key, val in value.items()}
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json(item) for item in value]
    if isinstance(value, set):
        return [sanitize_json(item) for item in value]
    return value


@app.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/auth/login")
async def login(payload: LoginRequest, response: Response) -> Dict[str, str]:
    username = payload.username.strip().lower()
    with SessionLocal() as session:
        user = session.scalar(select(UserORM).where(UserORM.username == username))
        if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuario o contraseña incorrectos.",
            )

        now = time.time()
        session.execute(delete(UserSessionORM).where(UserSessionORM.expires_at <= now))
        token = secrets.token_urlsafe(32)
        session.add(UserSessionORM(
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            user_id=user.id,
            expires_at=now + AUTH_SESSION_SECONDS,
        ))
        session.commit()
        response.set_cookie(
            key=AUTH_COOKIE_NAME,
            value=token,
            httponly=True,
            secure=AUTH_COOKIE_SECURE,
            samesite="lax",
            max_age=AUTH_SESSION_SECONDS,
            path="/",
        )
        return {"username": user.username, "role": user.role}


@app.get("/api/v1/auth/me")
async def current_user_profile(current_user: UserORM = Depends(get_current_user)) -> Dict[str, str]:
    return {"username": current_user.username, "role": current_user.role}


@app.post("/api/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    current_user: UserORM = Depends(get_current_user),
) -> Response:
    del current_user
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if token:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with SessionLocal() as session:
            auth_session = session.get(UserSessionORM, token_hash)
            if auth_session is not None:
                session.delete(auth_session)
                session.commit()
    logout_response = Response(status_code=status.HTTP_204_NO_CONTENT)
    logout_response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        secure=AUTH_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return logout_response


@app.post("/api/v1/jobs", status_code=status.HTTP_410_GONE)
async def create_job(
    payload: CreateJobRequest,
    current_user: UserORM = Depends(get_current_user),
) -> Dict[str, str]:
    del payload, current_user
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Creating jobs by server path is disabled. Upload the PDF through /api/v1/jobs/upload.",
    )


@app.post("/api/v1/jobs/upload", status_code=status.HTTP_201_CREATED)
async def upload_pdf_job(
    file: UploadFile = File(...),
    metadata: str = Form(default='{}'),
    current_user: UserORM = Depends(get_current_user),
) -> Dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported")

    if len(metadata.encode("utf-8")) > MAX_UPLOAD_METADATA_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Upload metadata exceeds the 16 KB limit.")
    try:
        payload_metadata = json.loads(metadata) if metadata else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="metadata must be valid JSON") from exc
    if not isinstance(payload_metadata, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="metadata must be a JSON object")

    job_id = str(uuid4())
    try:
        stored = pdf_service.store_pdf(job_id, file.filename, file.file)
    except PdfUploadLimitError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    payload_metadata = sanitize_json({
        **payload_metadata,
        "requested_by": current_user.username,
        "page_count": stored["page_count"],
        "action_code": stored["action_code"],
        "file_size": stored["file_size"],
    })
    with SessionLocal() as session:
        job = ProcessingJobORM(
            id=job_id,
            source_pdf_path=stored["storage_path"],
            original_file_hash=str(stored["sha256"]),
            status=JobStatus.QUEUED.value,
            created_by=current_user.id,
            payload_metadata=payload_metadata,
            queued_at=datetime.now(timezone.utc),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return serialize_processing_job(job)


@app.get("/api/v1/jobs")
async def list_jobs(current_user: UserORM = Depends(get_current_user)) -> List[Dict[str, Any]]:
    with SessionLocal() as session:
        statement = (
            select(ProcessingJobORM, HumanReviewORM)
            .outerjoin(HumanReviewORM, HumanReviewORM.job_id == ProcessingJobORM.id)
            .order_by(ProcessingJobORM.queued_at.desc())
        )
        if current_user.role != "admin":
            statement = statement.where(ProcessingJobORM.created_by == current_user.id)
        rows = session.execute(statement).all()
        return [serialize_processing_job(job, review) for job, review in rows]


@app.get("/api/v1/dashboard/summary")
async def dashboard_summary(current_user: UserORM = Depends(get_current_user)) -> Dict[str, int]:
    with SessionLocal() as session:
        statement = (
            select(ProcessingJobORM, HumanReviewORM)
            .outerjoin(HumanReviewORM, HumanReviewORM.job_id == ProcessingJobORM.id)
        )
        if current_user.role != "admin":
            statement = statement.where(ProcessingJobORM.created_by == current_user.id)
        rows = session.execute(statement).all()
        available_jobs = [
            (job, review)
            for job, review in rows
            if is_managed_evidence_available(job.source_pdf_path)
        ]
        job_ids = [job.id for job, _ in available_jobs]
        results = session.scalars(
            select(ValidationResultORM).where(ValidationResultORM.job_id.in_(job_ids))
        ).all() if job_ids else []

        return {
            "total": len(available_jobs),
            "pending": sum(job.status in {JobStatus.QUEUED.value, JobStatus.PROCESSING.value} for job, _ in available_jobs),
            "in_review": sum(
                job.status == JobStatus.REQUIRES_REVIEW.value and review is None
                for job, review in available_jobs
            ),
            "incidents": sum(result.outcome == ResultOutcome.INCIDENCIA.value for result in results),
            "not_verifiable": sum(result.outcome == ResultOutcome.NO_VERIFICABLE.value for result in results),
            "processed": sum(job.status == JobStatus.COMPLETED.value for job, _ in available_jobs),
        }


@app.get("/api/v1/formative-actions")
async def list_formative_actions(
    q: str = "",
    limit: int = 25,
    offset: int = 0,
    current_user: UserORM = Depends(get_current_user),
) -> Dict[str, Any]:
    del current_user
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    statement = select(FormativeActionORM)
    count_statement = select(func.count()).select_from(FormativeActionORM)
    query = q.strip()
    if query:
        pattern = f"%{query.lower()}%"
        condition = (
            func.lower(FormativeActionORM.action_code).like(pattern)
            | func.lower(FormativeActionORM.name).like(pattern)
        )
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)

    with SessionLocal() as session:
        total = session.scalar(count_statement) or 0
        rows = session.scalars(
            statement.order_by(FormativeActionORM.action_code).offset(offset).limit(limit)
        ).all()
        latest_import = session.scalar(
            select(FormativeActionImportORM).order_by(FormativeActionImportORM.imported_at.desc()).limit(1)
        )
        return {
            "items": [{
                "action_code": row.action_code,
                "name": row.name,
                "start_date": row.start_date,
                "status": row.status,
                "fields": row.fields or {},
                "imported_at": row.imported_at.isoformat(),
                "imported_by": row.imported_by,
            } for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "latest_import": {
                "filename": latest_import.filename,
                "imported_by": latest_import.imported_by,
                "imported_at": latest_import.imported_at.isoformat(),
                "total_rows": latest_import.total_rows,
                "inserted_rows": latest_import.inserted_rows,
                "updated_rows": latest_import.updated_rows,
                "columns": latest_import.columns or [],
            } if latest_import else None,
        }


@app.post("/api/v1/formative-actions/import")
async def import_formative_actions(
    file: UploadFile = File(...),
    current_user: UserORM = Depends(require_admin),
) -> Dict[str, Any]:
    filename = Path(file.filename or "").name
    content = await file.read(MAX_ACTION_IMPORT_BYTES + 1)
    if len(content) > MAX_ACTION_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el límite de 20 MB.")
    records, columns = await run_in_threadpool(parse_action_import, filename, content)
    inserted = 0
    updated = 0
    imported_at = datetime.now(timezone.utc)
    with SessionLocal() as session:
        existing_by_code: dict[str, FormativeActionORM] = {}
        action_codes = [record["action_code"] for record in records]
        for start in range(0, len(action_codes), 500):
            existing_rows = session.scalars(
                select(FormativeActionORM).where(
                    FormativeActionORM.action_code.in_(action_codes[start:start + 500])
                )
            ).all()
            existing_by_code.update({row.action_code: row for row in existing_rows})

        for record in records:
            row = existing_by_code.get(record["action_code"])
            if row is None:
                row = FormativeActionORM(
                    action_code=record["action_code"],
                    name=record["name"],
                    start_date=record["start_date"],
                    status=record["status"],
                    fields=record["fields"],
                    imported_at=imported_at,
                    imported_by=current_user.username,
                )
                session.add(row)
                inserted += 1
            else:
                row.name = record["name"]
                row.start_date = record["start_date"]
                row.status = record["status"]
                row.fields = record["fields"]
                row.imported_at = imported_at
                row.imported_by = current_user.username
                updated += 1

        session.add(FormativeActionImportORM(
            id=str(uuid4()),
            filename=filename,
            file_hash=hashlib.sha256(content).hexdigest(),
            imported_by=current_user.username,
            imported_at=imported_at,
            total_rows=len(records),
            inserted_rows=inserted,
            updated_rows=updated,
            columns=columns,
        ))
        session.commit()
    return {
        "filename": filename,
        "total_rows": len(records),
        "inserted_rows": inserted,
        "updated_rows": updated,
        "imported_at": imported_at.isoformat(),
    }


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: UUID, current_user: UserORM = Depends(get_current_user)) -> Dict[str, Any]:
    with SessionLocal() as session:
        row = get_accessible_job(session, str(job_id), current_user)
        return serialize_processing_job(row, session.get(HumanReviewORM, str(job_id)))


@app.post("/api/v1/jobs/{job_id}/process")
async def process_job(
    job_id: UUID,
    payload: ProcessJobRequest,
    current_user: UserORM = Depends(get_current_user),
) -> Dict[str, Any]:
    with SessionLocal() as session:
        row = get_accessible_job(session, str(job_id), current_user)

        previous_review = session.get(HumanReviewORM, str(job_id))
        if previous_review is not None:
            reviewed_at = datetime.now(timezone.utc)
            session.add(AuditEventORM(
                id=str(uuid4()),
                job_id=str(job_id),
                actor=current_user.username,
                action="HUMAN_REVIEW_INVALIDATED_BY_REPROCESS",
                details=sanitize_json({
                    "previous_reviewer": previous_review.reviewer,
                    "previous_final_status": previous_review.final_status,
                }),
                created_at=reviewed_at,
            ))
            session.delete(previous_review)

        previous_verifications = session.scalars(
            select(ValidationResultORM).where(
                ValidationResultORM.job_id == str(job_id),
                ValidationResultORM.participant_id.is_not(None),
            )
        ).all()
        if previous_verifications:
            session.add(AuditEventORM(
                id=str(uuid4()),
                job_id=str(job_id),
                actor=current_user.username,
                action="CEDULA_VERIFICATIONS_INVALIDATED_BY_REPROCESS",
                details={"invalidated_count": len(previous_verifications)},
                created_at=datetime.now(timezone.utc),
            ))
            for verification in previous_verifications:
                session.delete(verification)

        row.status = JobStatus.PROCESSING.value
        row.started_at = datetime.now(timezone.utc)

        pdf_metadata: Dict[str, Any] = {}
        pdf_text_source = "source_unavailable"
        text_extraction = None
        if row.source_pdf_path and is_managed_evidence_available(row.source_pdf_path):
            try:
                pdf_metadata = pdf_service.inspect_existing_pdf(row.source_pdf_path)
                text_extraction = await run_in_threadpool(
                    pdf_service.extract_text,
                    row.source_pdf_path,
                    ocr_provider,
                )
                pdf_text_source = text_extraction.source
            except PdfUploadLimitError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"PDF exceeds safe processing limits: {exc}",
                ) from exc
            except FileNotFoundError:
                pdf_metadata = {}

        candidate_summary = summarize_document_candidates(
            text_extraction.pages if text_extraction else []
        )
        row.payload_metadata = sanitize_json({
            **(row.payload_metadata or {}),
            **payload.metadata,
            "force_reprocess": payload.force,
            "page_count": pdf_metadata.get("page_count", (row.payload_metadata or {}).get("page_count")),
            "sha256": pdf_metadata.get("sha256", (row.payload_metadata or {}).get("sha256")),
            "action_code": pdf_metadata.get("action_code", (row.payload_metadata or {}).get("action_code")),
            "text_extraction_source": pdf_text_source,
            "ocr_provider": text_extraction.provider if text_extraction else None,
            "extracted_text_characters": len(text_extraction.full_text) if text_extraction else 0,
            "text_pages_detected": sum(bool(page.text.strip()) for page in text_extraction.pages) if text_extraction else 0,
            **candidate_summary,
        })

        row.status = JobStatus.REQUIRES_REVIEW.value
        row.finished_at = datetime.now(timezone.utc)

        if pdf_text_source == "ocr_not_configured":
            message = "PDF conservado y analizado. Es un escaneo sin texto digital; OCR no está configurado, por lo que no se validaron participantes ni documentos."
        elif pdf_text_source == "source_unavailable":
            message = "No se encontró el PDF original. El job requiere revisión y no se ejecutó la validación documental."
        elif pdf_text_source == "ocr":
            message = (
                f"OCR local ({text_extraction.provider}) extrajo texto de "
                f"{row.payload_metadata['text_pages_detected']} páginas. "
                f"Detectó {candidate_summary['roster_candidate_count']} candidatos en páginas de lista "
                f"y {candidate_summary['evidence_candidate_count']} en otras páginas. "
                f"{candidate_summary['cedula_checksum_valid_count']} pasan el control matemático "
                f"del dígito; {candidate_summary['cedula_checksum_invalid_count']} no lo pasan. "
                f"Coincidencias exactas entre páginas con lectura confiable: {candidate_summary['candidate_matches']}; "
                f"{candidate_summary['low_confidence_evidence_candidates']} candidatos de documento "
                "tienen baja confianza de OCR. El control de dígito y las coincidencias no confirman "
                "la identidad ni que el documento pertenezca a una persona; revisa los PDF originales."
            )
        else:
            message = (
                f"Se extrajo texto digital de {row.payload_metadata['text_pages_detected']} páginas. "
                f"Detectó {candidate_summary['roster_candidate_count']} candidatos en páginas de lista "
                f"y {candidate_summary['evidence_candidate_count']} en otras páginas. "
                f"{candidate_summary['cedula_checksum_valid_count']} pasan el control matemático "
                f"del dígito; {candidate_summary['cedula_checksum_invalid_count']} no lo pasan. "
                f"Coincidencias exactas entre páginas con lectura confiable: {candidate_summary['candidate_matches']}. "
                "El control no confirma identidad ni asociación; revisa los PDF originales."
            )
        if pdf_metadata.get("action_code"):
            message = f"{message} Código candidato detectado en el nombre del archivo: {pdf_metadata.get('action_code')}."

        summary_result = session.scalar(
            select(ValidationResultORM).where(
                ValidationResultORM.job_id == str(job_id),
                ValidationResultORM.participant_id.is_(None),
                ValidationResultORM.identity_document_id.is_(None),
                ValidationResultORM.rule_id.is_(None),
            ).limit(1)
        )
        if summary_result is None:
            summary_result = ValidationResultORM(
                id=str(uuid4()),
                job_id=str(job_id),
                participant_id=None,
                identity_document_id=None,
                rule_id=None,
                outcome=ResultOutcome.NO_VERIFICABLE.value,
                reason_code=RuleCode.DIFERENCIA_DETECTADA.value,
                message=message,
                evidence_ref=Path(row.source_pdf_path).name,
                created_at=datetime.now(timezone.utc),
            )
            session.add(summary_result)
        else:
            summary_result.outcome = ResultOutcome.NO_VERIFICABLE.value
            summary_result.reason_code = RuleCode.DIFERENCIA_DETECTADA.value
            summary_result.message = message
            summary_result.evidence_ref = Path(row.source_pdf_path).name
            summary_result.created_at = datetime.now(timezone.utc)
        session.commit()

        results = session.scalars(select(ValidationResultORM).where(ValidationResultORM.job_id == str(job_id))).all()
        return {
            "job_id": str(job_id),
            "status": row.status,
            "message": summary_result.message,
            "results": [serialize_validation_result(item) for item in results],
        }


@app.post("/api/v1/jobs/{job_id}/cedula-verifications")
async def verify_job_cedula(
    job_id: UUID,
    payload: CedulaVerificationRequest,
    current_user: UserORM = Depends(get_current_user),
) -> Dict[str, Any]:
    reference_match = re.fullmatch(r"fila\s+(\d{1,6})", payload.participant_reference.strip(), re.IGNORECASE)
    if reference_match is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Usa una referencia de fila, por ejemplo: Fila 12.",
        )
    participant_reference = f"Fila {int(reference_match.group(1))}"
    assessment = assess_cedula_pair(
        payload.roster_cedula,
        payload.document_cedula,
        payload.visual_identity_confirmed,
    )

    with SessionLocal() as session:
        job = get_accessible_job(session, str(job_id), current_user)
        if not is_managed_evidence_available(job.source_pdf_path):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El PDF original no está disponible para cotejo.")

        page_count = (job.payload_metadata or {}).get("page_count")
        if isinstance(page_count, int) and max(payload.roster_page, payload.document_page) > page_count:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Las páginas deben estar entre 1 y {page_count}.",
            )

        participant_id = str(uuid5(UUID(str(job_id)), participant_reference.casefold()))
        document_id = str(uuid5(UUID(str(job_id)), f"{participant_reference.casefold()}:{payload.document_page}"))
        result = session.scalar(
            select(ValidationResultORM).where(
                ValidationResultORM.job_id == str(job_id),
                ValidationResultORM.participant_id == participant_id,
                ValidationResultORM.rule_id == "CEDULA_MANUAL",
            )
        )
        reviewed_at = datetime.now(timezone.utc)
        evidence_ref = f"Lista: página {payload.roster_page}; documento: página {payload.document_page}"
        message = f"{participant_reference}: {assessment.message}"
        if result is None:
            result = ValidationResultORM(
                id=str(uuid4()),
                job_id=str(job_id),
                participant_id=participant_id,
                identity_document_id=document_id,
                rule_id="CEDULA_MANUAL",
                outcome=assessment.outcome,
                reason_code=assessment.reason_code,
                message=message,
                evidence_ref=evidence_ref,
                created_at=reviewed_at,
            )
            session.add(result)
        else:
            result.identity_document_id = document_id
            result.outcome = assessment.outcome
            result.reason_code = assessment.reason_code
            result.message = message
            result.evidence_ref = evidence_ref
            result.created_at = reviewed_at

        session.add(AuditEventORM(
            id=str(uuid4()),
            job_id=str(job_id),
            actor=current_user.username,
            action="CEDULA_MANUAL_VERIFICATION_RECORDED",
            details={
                "participant_reference": participant_reference,
                "outcome": assessment.outcome,
                "reason_code": assessment.reason_code,
                "roster_page": payload.roster_page,
                "document_page": payload.document_page,
            },
            created_at=reviewed_at,
        ))
        verification_rows = session.scalars(
            select(ValidationResultORM).where(
                ValidationResultORM.job_id == str(job_id),
                ValidationResultORM.rule_id == "CEDULA_MANUAL",
            )
        ).all()
        verified_by_participant = {
            item.participant_id: item.outcome
            for item in verification_rows
            if item.participant_id is not None
        }
        verified_by_participant[participant_id] = assessment.outcome
        verified_count = sum(
            outcome == ResultOutcome.CORRECTO.value
            for outcome in verified_by_participant.values()
        )
        metadata = dict(job.payload_metadata or {})
        metadata["verified_identities"] = verified_count
        metadata["verification_requires_human_visual_review"] = True
        job.payload_metadata = metadata
        session.commit()

        return {
            "participant_reference": participant_reference,
            "outcome": assessment.outcome,
            "reason_code": assessment.reason_code,
            "message": message,
            "evidence_ref": evidence_ref,
            "created_at": reviewed_at.isoformat(),
        }


@app.get("/api/v1/jobs/{job_id}/results")
async def get_job_results(
    job_id: UUID,
    current_user: UserORM = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    with SessionLocal() as session:
        get_accessible_job(session, str(job_id), current_user)
        results = session.scalars(select(ValidationResultORM).where(ValidationResultORM.job_id == str(job_id))).all()
        return [serialize_validation_result(result) for result in results]


@app.get("/api/v1/jobs/{job_id}/review")
async def get_job_review(
    job_id: UUID,
    current_user: UserORM = Depends(get_current_user),
) -> Dict[str, Any] | None:
    with SessionLocal() as session:
        get_accessible_job(session, str(job_id), current_user)
        review = session.get(HumanReviewORM, str(job_id))
        if review is None:
            return None
        return {
            "job_id": review.job_id,
            "reviewer": review.reviewer,
            "comments": review.comments,
            "final_status": review.final_status,
            "reviewed_at": review.reviewed_at.isoformat(),
        }


@app.put("/api/v1/jobs/{job_id}/review")
async def save_job_review(
    job_id: UUID,
    payload: HumanReviewRequest,
    current_user: UserORM = Depends(get_current_user),
) -> Dict[str, Any]:
    reviewer = current_user.username
    if payload.final_status is not None and payload.final_status not in FINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"final_status must be one of: {', '.join(sorted(FINAL_STATUSES))}",
        )

    with SessionLocal() as session:
        get_accessible_job(session, str(job_id), current_user)

        reviewed_at = datetime.now(timezone.utc)
        review = session.get(HumanReviewORM, str(job_id))
        if review is None:
            review = HumanReviewORM(job_id=str(job_id), reviewer=reviewer)
            session.add(review)

        review.reviewer = reviewer
        review.comments = payload.comments.strip()
        review.final_status = payload.final_status
        review.reviewed_at = reviewed_at
        audit_event = AuditEventORM(
            id=str(uuid4()),
            job_id=str(job_id),
            actor=reviewer,
            action="HUMAN_REVIEW_SAVED",
            details=sanitize_json({
                "comments": review.comments,
                "final_status": review.final_status,
            }),
            created_at=reviewed_at,
        )
        session.add(audit_event)
        session.commit()
        return {
            "job_id": review.job_id,
            "reviewer": review.reviewer,
            "comments": review.comments,
            "final_status": review.final_status,
            "reviewed_at": review.reviewed_at.isoformat(),
        }


@app.get("/api/v1/jobs/{job_id}/evidence")
async def get_job_evidence(
    job_id: UUID,
    current_user: UserORM = Depends(get_current_user),
) -> FileResponse:
    with SessionLocal() as session:
        job = get_accessible_job(session, str(job_id), current_user)
        evidence_path = job.source_pdf_path

    path = Path(evidence_path).resolve()
    try:
        path.relative_to(pdf_service.storage_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Evidence is outside the managed PDF storage") from exc
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Original PDF evidence not found")
    audit_evidence_access(
        str(job_id),
        current_user.username,
        "EVIDENCE_PDF_REQUESTED",
        {"resource": "original_pdf"},
    )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/v1/jobs/{job_id}/preview")
async def get_job_evidence_preview(
    job_id: UUID,
    page: int = 1,
    current_user: UserORM = Depends(get_current_user),
) -> Response:
    if page < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Page must be 1 or greater.")
    with SessionLocal() as session:
        job = get_accessible_job(session, str(job_id), current_user)
        evidence_path = Path(job.source_pdf_path).resolve()

    try:
        evidence_path.relative_to(pdf_service.storage_dir.resolve())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Evidence is outside the managed PDF storage",
        ) from exc
    if not evidence_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Original PDF evidence not found")

    image, page_count = await run_in_threadpool(render_pdf_page_preview, str(evidence_path), page)
    audit_evidence_access(
        str(job_id),
        current_user.username,
        "EVIDENCE_PREVIEW_GENERATED",
        {"page": page},
    )
    return Response(
        content=image,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Page-Count": str(page_count),
        },
    )


@app.get("/api/v1/jobs/{job_id}/audit")
async def get_job_audit(
    job_id: UUID,
    current_user: UserORM = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    with SessionLocal() as session:
        get_accessible_job(session, str(job_id), current_user)
        events = session.scalars(
            select(AuditEventORM)
            .where(AuditEventORM.job_id == str(job_id))
            .order_by(AuditEventORM.created_at.desc())
        ).all()
        return [{
            "id": event.id,
            "job_id": event.job_id,
            "actor": event.actor,
            "action": event.action,
            "details": event.details or {},
            "created_at": event.created_at.isoformat(),
        } for event in events]


@app.delete("/api/v1/jobs/{job_id}")
async def delete_job(
    job_id: UUID,
    current_user: UserORM = Depends(get_current_user),
) -> Dict[str, str]:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    with SessionLocal() as session:
        row = session.get(ProcessingJobORM, str(job_id))
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processing job not found")
        session.delete(row)
        session.query(ValidationResultORM).filter(ValidationResultORM.job_id == str(job_id)).delete()
        session.commit()
        return {"status": "deleted", "job_id": str(job_id)}
