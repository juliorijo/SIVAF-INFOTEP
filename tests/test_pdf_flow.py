import io
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

from pypdf import PdfWriter

from fastapi.testclient import TestClient

from apps.api import main as api_module
from apps.api.auth import hash_password
from apps.api.database import SessionLocal, UserORM
from apps.api.main import app
from packages.document_processing.pdf_service import PdfIngestionService
from packages.domain.contracts import OCRDocumentText, OCRPageText, OCRProvider
from packages.validation.dominican_cedula import (
    is_dominican_cedula_checksum_valid,
    normalize_dominican_cedula_candidate,
)


class FakeOCRProvider(OCRProvider):
    def extract_text(self, pdf_path: str, progress_callback=None) -> OCRDocumentText:
        return OCRDocumentText(
            pages=[OCRPageText(page_number=1, text="Texto detectado", confidence=0.98)],
            provider="test-provider",
        )

    def extract_document_images(self, pdf_path: str) -> list[dict]:
        return []


class CandidateOCRProvider(FakeOCRProvider):
    def extract_text(self, pdf_path: str, progress_callback=None) -> OCRDocumentText:
        return OCRDocumentText(
            pages=[OCRPageText(
                page_number=1,
                text="CEDULA: 222-2222222-1",
                confidence=0.98,
            )],
            provider="test-provider",
        )


class RosterAndDocumentOCRProvider(FakeOCRProvider):
    def extract_text(self, pdf_path: str, progress_callback=None) -> OCRDocumentText:
        return OCRDocumentText(
            pages=[
                OCRPageText(
                    page_number=1,
                    text="LISTA DE PARTICIPANTES NOMBRE CEDULA 111-1111111-5 222-2222222-0",
                    confidence=0.9,
                ),
                OCRPageText(
                    page_number=3,
                    text="CEDULA 11111111115",
                    confidence=0.4,
                ),
            ],
            provider="test-provider",
        )


class PdfFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.username = f"pdf-test-{uuid4().hex[:12]}"
        cls.password = secrets.token_urlsafe(24)
        with SessionLocal() as session:
            session.add(UserORM(
                id=str(uuid4()),
                username=cls.username,
                password_hash=hash_password(cls.password),
                role="analyst",
            ))
            session.commit()

    def setUp(self):
        self.client = TestClient(app)
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": self.username, "password": self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.storage_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage_dir.cleanup)
        api_module.pdf_service = PdfIngestionService(self.storage_dir.name)

    @staticmethod
    def _make_pdf_bytes():
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    def _wait_for_job_terminal(self, job_id: str, timeout_seconds: float = 8.0):
        deadline = time.time() + timeout_seconds
        last_status = None
        while time.time() < deadline:
            response = self.client.get(f"/api/v1/jobs/{job_id}")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            last_status = payload["status"]
            if last_status in {"REQUIRES_REVIEW", "COMPLETED", "FAILED"}:
                return payload
            time.sleep(0.05)
        self.fail(f"Job {job_id} did not reach a terminal state. Last status: {last_status}")

    def test_upload_pdf_job_and_detect_metadata(self):
        pdf_bytes = self._make_pdf_bytes()

        response = self.client.post(
            "/api/v1/jobs/upload",
            files={"file": ("2026-001234.pdf", pdf_bytes, "application/pdf")},
            data={"created_by": "tester", "metadata": '{"batch": "pdf-flow"}'},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertIn(payload["status"], {"QUEUED", "PROCESSING", "REQUIRES_REVIEW"})
        self.assertEqual(payload["metadata"]["requested_by"], self.username)
        self.assertTrue(payload["evidence_available"])
        self.assertEqual(payload["metadata"]["action_code"], "2026-001234")
        self.assertGreaterEqual(payload["metadata"]["page_count"], 1)
        self._wait_for_job_terminal(payload["id"])
        evidence_response = self.client.get(f"/api/v1/jobs/{payload['id']}/evidence")
        self.assertEqual(evidence_response.status_code, 200)
        self.assertTrue(evidence_response.content.startswith(b"%PDF-"))
        preview_response = self.client.get(f"/api/v1/jobs/{payload['id']}/preview?page=1")
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_response.headers["content-type"], "image/png")
        self.assertEqual(preview_response.headers["x-page-count"], "1")
        self.assertTrue(preview_response.content.startswith(b"\x89PNG\r\n\x1a\n"))
        out_of_range_preview = self.client.get(f"/api/v1/jobs/{payload['id']}/preview?page=2")
        self.assertEqual(out_of_range_preview.status_code, 404)
        results = self.client.get(f"/api/v1/jobs/{payload['id']}/results").json()
        self.assertTrue(results)
        self.assertIn("motor OCR no está disponible", results[0]["message"])

    def test_scanned_pdf_uses_injected_ocr_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "scanned.pdf"
            pdf_path.write_bytes(self._make_pdf_bytes())

            extraction = PdfIngestionService(directory).extract_text(pdf_path, FakeOCRProvider())

        self.assertEqual(extraction.source, "ocr")
        self.assertEqual(extraction.provider, "test-provider")
        self.assertEqual(extraction.full_text, "Texto detectado")

    def test_pdf_extraction_forwards_progress_updates_to_ocr_provider(self):
        progress_events: list[tuple[int, int]] = []

        class ProgressOCRProvider(FakeOCRProvider):
            def extract_text(self, pdf_path: str, progress_callback=None) -> OCRDocumentText:
                if progress_callback is not None:
                    progress_callback(1, 3)
                    progress_callback(2, 3)
                    progress_callback(3, 3)
                return OCRDocumentText(
                    pages=[OCRPageText(page_number=1, text="Texto detectado", confidence=0.98)],
                    provider="progress-provider",
                )

        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "scanned.pdf"
            pdf_path.write_bytes(self._make_pdf_bytes())

            extraction = PdfIngestionService(directory).extract_text(
                pdf_path,
                ProgressOCRProvider(),
                progress_callback=lambda page_number, total_pages: progress_events.append((page_number, total_pages)),
            )

        self.assertEqual(extraction.provider, "progress-provider")
        self.assertEqual(progress_events, [(1, 3), (2, 3), (3, 3)])

    def test_dominican_cedula_control_digit(self):
        self.assertTrue(is_dominican_cedula_checksum_valid("111-1111111-5"))
        self.assertTrue(is_dominican_cedula_checksum_valid("22222222220"))
        self.assertTrue(is_dominican_cedula_checksum_valid("111-1111111-S"))
        self.assertEqual(normalize_dominican_cedula_candidate("I11-1111111-S"), "11111111115")
        self.assertFalse(is_dominican_cedula_checksum_valid("111-1111111-6"))
        self.assertFalse(is_dominican_cedula_checksum_valid("1111111111"))
        self.assertFalse(is_dominican_cedula_checksum_valid("1111111111A"))

    def test_processing_reports_ocr_candidates_without_claiming_validation(self):
        previous_provider = api_module.ocr_provider
        api_module.ocr_provider = CandidateOCRProvider()
        self.addCleanup(setattr, api_module, "ocr_provider", previous_provider)
        uploaded = self.client.post(
            "/api/v1/jobs/upload",
            files={"file": ("candidate.pdf", self._make_pdf_bytes(), "application/pdf")},
        )
        self.assertEqual(uploaded.status_code, 201)

        response = self.client.post(
            f"/api/v1/jobs/{uploaded.json()['id']}/process",
            json={"force": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "PROCESSING")
        job = self._wait_for_job_terminal(uploaded.json()["id"])
        results = self.client.get(f"/api/v1/jobs/{uploaded.json()['id']}/results").json()
        self.assertIn("no confirman la identidad", results[0]["message"])
        self.assertEqual(job["metadata"]["cedula_candidate_count"], 1)
        self.assertEqual(job["metadata"]["cedula_candidate_pages"], [1])

    def test_processing_compares_candidate_sets_without_persisting_id_numbers(self):
        previous_provider = api_module.ocr_provider
        api_module.ocr_provider = RosterAndDocumentOCRProvider()
        self.addCleanup(setattr, api_module, "ocr_provider", previous_provider)
        uploaded = self.client.post(
            "/api/v1/jobs/upload",
            files={"file": ("roster.pdf", self._make_pdf_bytes(), "application/pdf")},
        )
        self.assertEqual(uploaded.status_code, 201)

        response = self.client.post(
            f"/api/v1/jobs/{uploaded.json()['id']}/process",
            json={"force": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "PROCESSING")
        job = self._wait_for_job_terminal(uploaded.json()["id"])
        metadata = job["metadata"]
        self.assertEqual(metadata["roster_candidate_count"], 2)
        self.assertEqual(metadata["evidence_candidate_count"], 1)
        self.assertEqual(metadata["cedula_checksum_valid_count"], 2)
        self.assertEqual(metadata["cedula_checksum_invalid_count"], 0)
        self.assertEqual(metadata["roster_checksum_valid_count"], 2)
        self.assertEqual(metadata["evidence_checksum_valid_count"], 1)
        self.assertEqual(metadata["candidate_matches"], 0)
        self.assertEqual(metadata["roster_candidates_without_document_candidate"], 2)
        self.assertEqual(metadata["low_confidence_evidence_candidates"], 1)
        self.assertEqual(metadata["verified_identities"], 0)
        self.assertTrue(metadata["identity_association_requires_human_review"])
        self.assertEqual(metadata["participants_requiring_review_count"], 2)
        self.assertEqual(metadata["participants_ok_automatic_count"], 0)
        self.assertEqual(len(metadata["participant_review_items"]), 2)
        self.assertTrue(all(item["review_status"] == "REQUIERE_REVISION" for item in metadata["participant_review_items"]))
        self.assertNotIn("11111111115", str(metadata))
        results = self.client.get(f"/api/v1/jobs/{uploaded.json()['id']}/results").json()
        self.assertEqual(results[0]["outcome"], "NO_VERIFICABLE")

    def test_checksum_valid_candidate_match_requires_confident_ocr_on_both_pages(self):
        class ConfidentRosterAndDocumentProvider(FakeOCRProvider):
            def extract_text(self, pdf_path: str, progress_callback=None) -> OCRDocumentText:
                return OCRDocumentText(
                    pages=[
                        OCRPageText(
                            page_number=1,
                            text="LISTA DE PARTICIPANTES NOMBRE CEDULA 111-1111111-5",
                            confidence=0.9,
                        ),
                        OCRPageText(
                            page_number=2,
                            text="CEDULA 11111111115",
                            confidence=0.9,
                        ),
                    ],
                    provider="test-provider",
                )

        previous_provider = api_module.ocr_provider
        api_module.ocr_provider = ConfidentRosterAndDocumentProvider()
        self.addCleanup(setattr, api_module, "ocr_provider", previous_provider)
        uploaded = self.client.post(
            "/api/v1/jobs/upload",
            files={"file": ("roster-confident.pdf", self._make_pdf_bytes(), "application/pdf")},
        )

        response = self.client.post(
            f"/api/v1/jobs/{uploaded.json()['id']}/process",
            json={"force": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "PROCESSING")
        self._wait_for_job_terminal(uploaded.json()["id"])
        metadata = self.client.get(f"/api/v1/jobs/{uploaded.json()['id']}").json()["metadata"]
        self.assertEqual(metadata["cedula_checksum_valid_count"], 1)
        self.assertEqual(metadata["roster_checksum_valid_count"], 1)
        self.assertEqual(metadata["evidence_checksum_valid_count"], 1)
        self.assertEqual(metadata["candidate_matches"], 1)
        self.assertEqual(metadata["verified_identities"], 0)
        self.assertEqual(metadata["participants_ok_automatic_count"], 1)
        self.assertEqual(metadata["participants_requiring_review_count"], 0)
        results = self.client.get(f"/api/v1/jobs/{uploaded.json()['id']}/results").json()
        self.assertIn("no confirman la identidad", results[0]["message"])
        self.assertNotIn("11111111115", str(metadata))

    def test_ocr_candidate_normalization_handles_common_letter_digit_confusions(self):
        class OCRNoiseProvider(FakeOCRProvider):
            def extract_text(self, pdf_path: str, progress_callback=None) -> OCRDocumentText:
                return OCRDocumentText(
                    pages=[
                        OCRPageText(
                            page_number=1,
                            text="LISTA DE PARTICIPANTES NOMBRE CEDULA I11-1111111-S",
                            confidence=0.92,
                        ),
                        OCRPageText(
                            page_number=2,
                            text="CEDULA I11 1111111 S",
                            confidence=0.91,
                        ),
                    ],
                    provider="test-provider",
                )

        previous_provider = api_module.ocr_provider
        api_module.ocr_provider = OCRNoiseProvider()
        self.addCleanup(setattr, api_module, "ocr_provider", previous_provider)
        uploaded = self.client.post(
            "/api/v1/jobs/upload",
            files={"file": ("ocr-noise.pdf", self._make_pdf_bytes(), "application/pdf")},
        )

        response = self.client.post(
            f"/api/v1/jobs/{uploaded.json()['id']}/process",
            json={"force": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "PROCESSING")
        self._wait_for_job_terminal(uploaded.json()["id"])
        metadata = self.client.get(f"/api/v1/jobs/{uploaded.json()['id']}").json()["metadata"]
        self.assertEqual(metadata["cedula_candidate_count"], 1)
        self.assertEqual(metadata["cedula_checksum_valid_count"], 1)
        self.assertEqual(metadata["candidate_matches"], 1)

    def test_upload_rejects_invalid_pdf_bytes(self):
        response = self.client.post(
            "/api/v1/jobs/upload",
            files={"file": ("not-a-pdf.pdf", b"not a pdf", "application/pdf")},
        )
        self.assertEqual(response.status_code, 400)

    def test_pdf_ingestion_rejects_documents_above_page_limit(self):
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        writer.write(buffer)
        with tempfile.TemporaryDirectory() as directory:
            service = PdfIngestionService(directory, max_pdf_pages=1)
            with self.assertRaisesRegex(ValueError, "page limit"):
                service.store_pdf("test-job", "too-many-pages.pdf", io.BytesIO(buffer.getvalue()))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_pdf_ingestion_rejects_pages_that_would_rasterize_excessively(self):
        writer = PdfWriter()
        writer.add_blank_page(width=20_000, height=20_000)
        buffer = io.BytesIO()
        writer.write(buffer)
        with tempfile.TemporaryDirectory() as directory:
            service = PdfIngestionService(directory)
            with self.assertRaisesRegex(ValueError, "too large to rasterize"):
                service.store_pdf("test-job", "huge-page.pdf", io.BytesIO(buffer.getvalue()))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
