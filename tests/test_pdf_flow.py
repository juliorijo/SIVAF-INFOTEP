import io
import secrets
import tempfile
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
from packages.validation.dominican_cedula import is_dominican_cedula_checksum_valid
from packages.validation.cedula_verification import assess_cedula_pair


class FakeOCRProvider(OCRProvider):
    def extract_text(self, pdf_path: str) -> OCRDocumentText:
        return OCRDocumentText(
            pages=[OCRPageText(page_number=1, text="Texto detectado", confidence=0.98)],
            provider="test-provider",
        )

    def extract_document_images(self, pdf_path: str) -> list[dict]:
        return []


class CandidateOCRProvider(FakeOCRProvider):
    def extract_text(self, pdf_path: str) -> OCRDocumentText:
        return OCRDocumentText(
            pages=[OCRPageText(
                page_number=1,
                text="CEDULA: 222-2222222-1",
                confidence=0.98,
            )],
            provider="test-provider",
        )


class RosterAndDocumentOCRProvider(FakeOCRProvider):
    def extract_text(self, pdf_path: str) -> OCRDocumentText:
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

    def test_upload_pdf_job_and_detect_metadata(self):
        pdf_bytes = self._make_pdf_bytes()

        response = self.client.post(
            "/api/v1/jobs/upload",
            files={"file": ("2026-001234.pdf", pdf_bytes, "application/pdf")},
            data={"created_by": "tester", "metadata": '{"batch": "pdf-flow"}'},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["status"], "QUEUED")
        self.assertEqual(payload["metadata"]["requested_by"], self.username)
        self.assertTrue(payload["evidence_available"])
        self.assertEqual(payload["metadata"]["action_code"], "2026-001234")
        self.assertGreaterEqual(payload["metadata"]["page_count"], 1)
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

        job_id = payload["id"]
        process_response = self.client.post(f"/api/v1/jobs/{job_id}/process", json={"force": True})
        self.assertEqual(process_response.status_code, 200)
        self.assertEqual(process_response.json()["status"], "REQUIRES_REVIEW")
        self.assertIn("OCR no está configurado", process_response.json()["results"][0]["message"])

    def test_scanned_pdf_uses_injected_ocr_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "scanned.pdf"
            pdf_path.write_bytes(self._make_pdf_bytes())

            extraction = PdfIngestionService(directory).extract_text(pdf_path, FakeOCRProvider())

        self.assertEqual(extraction.source, "ocr")
        self.assertEqual(extraction.provider, "test-provider")
        self.assertEqual(extraction.full_text, "Texto detectado")

    def test_dominican_cedula_control_digit(self):
        self.assertTrue(is_dominican_cedula_checksum_valid("111-1111111-5"))
        self.assertTrue(is_dominican_cedula_checksum_valid("22222222220"))
        self.assertFalse(is_dominican_cedula_checksum_valid("111-1111111-6"))
        self.assertFalse(is_dominican_cedula_checksum_valid("1111111111"))
        self.assertFalse(is_dominican_cedula_checksum_valid("1111111111A"))

    def test_cedula_pair_requires_valid_checksums_match_and_visual_confirmation(self):
        match_without_visual_review = assess_cedula_pair(
            "111-1111111-5",
            "111 1111111 5",
            False,
        )
        self.assertEqual(match_without_visual_review.outcome, "REVISION")
        self.assertEqual(match_without_visual_review.reason_code, "ASOCIACION_PENDIENTE")

        confirmed_match = assess_cedula_pair(
            "111-1111111-5",
            "11111111115",
            True,
        )
        self.assertEqual(confirmed_match.outcome, "CORRECTO")
        self.assertEqual(confirmed_match.reason_code, "VERIFICACION_MANUAL_COMPLETA")

        mismatch = assess_cedula_pair("11111111115", "22222222220", True)
        self.assertEqual(mismatch.outcome, "REVISION")
        self.assertEqual(mismatch.reason_code, "NUMERO_DOCUMENTO_NO_COINCIDE")

        invalid_control_digit = assess_cedula_pair("11111111116", "11111111115", True)
        self.assertEqual(invalid_control_digit.outcome, "REVISION")
        self.assertEqual(invalid_control_digit.reason_code, "DIGITO_CONTROL_NO_COINCIDE")

        unreadable = assess_cedula_pair("1111111111A", "11111111115", True)
        self.assertEqual(unreadable.outcome, "NO_VERIFICABLE")
        self.assertEqual(unreadable.reason_code, "CEDULA_NO_LEGIBLE")

    def test_manual_cedula_verification_is_server_checked_and_does_not_persist_numbers(self):
        uploaded = self.client.post(
            "/api/v1/jobs/upload",
            files={"file": ("verification.pdf", self._make_pdf_bytes(), "application/pdf")},
        )
        self.assertEqual(uploaded.status_code, 201)
        job_id = uploaded.json()["id"]
        base_payload = {
            "participant_reference": "Fila 12",
            "roster_page": 1,
            "document_page": 1,
            "roster_cedula": "111-1111111-5",
            "document_cedula": "11111111115",
            "visual_identity_confirmed": False,
        }

        pending = self.client.post(
            f"/api/v1/jobs/{job_id}/cedula-verifications",
            json=base_payload,
        )
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["outcome"], "REVISION")
        self.assertEqual(pending.json()["reason_code"], "ASOCIACION_PENDIENTE")
        self.assertNotIn("11111111115", str(pending.json()))

        mismatch = self.client.post(
            f"/api/v1/jobs/{job_id}/cedula-verifications",
            json={**base_payload, "document_cedula": "22222222220", "visual_identity_confirmed": True},
        )
        self.assertEqual(mismatch.status_code, 200)
        self.assertEqual(mismatch.json()["outcome"], "REVISION")
        self.assertEqual(mismatch.json()["reason_code"], "NUMERO_DOCUMENTO_NO_COINCIDE")

        confirmed = self.client.post(
            f"/api/v1/jobs/{job_id}/cedula-verifications",
            json={**base_payload, "visual_identity_confirmed": True},
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["outcome"], "CORRECTO")

        results = self.client.get(f"/api/v1/jobs/{job_id}/results").json()
        manual_results = [result for result in results if result["rule_id"] == "CEDULA_MANUAL"]
        self.assertEqual(len(manual_results), 1)
        self.assertEqual(manual_results[0]["outcome"], "CORRECTO")
        self.assertNotIn("11111111115", str(manual_results))
        job = self.client.get(f"/api/v1/jobs/{job_id}").json()
        self.assertEqual(job["metadata"]["verified_identities"], 1)
        audit = self.client.get(f"/api/v1/jobs/{job_id}/audit").json()
        self.assertNotIn("11111111115", str(audit))
        self.assertEqual(len([event for event in audit if event["action"] == "CEDULA_MANUAL_VERIFICATION_RECORDED"]), 3)

        invalid_page = self.client.post(
            f"/api/v1/jobs/{job_id}/cedula-verifications",
            json={**base_payload, "document_page": 2},
        )
        self.assertEqual(invalid_page.status_code, 422)

    def test_reprocessing_invalidates_manual_cedula_verifications(self):
        uploaded = self.client.post(
            "/api/v1/jobs/upload",
            files={"file": ("reprocess-verification.pdf", self._make_pdf_bytes(), "application/pdf")},
        )
        self.assertEqual(uploaded.status_code, 201)
        job_id = uploaded.json()["id"]
        verified = self.client.post(
            f"/api/v1/jobs/{job_id}/cedula-verifications",
            json={
                "participant_reference": "Fila 2",
                "roster_page": 1,
                "document_page": 1,
                "roster_cedula": "11111111115",
                "document_cedula": "11111111115",
                "visual_identity_confirmed": True,
            },
        )
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/v1/jobs/{job_id}").json()["metadata"]["verified_identities"],
            1,
        )

        reprocessed = self.client.post(
            f"/api/v1/jobs/{job_id}/process",
            json={"force": True},
        )
        self.assertEqual(reprocessed.status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/v1/jobs/{job_id}").json()["metadata"]["verified_identities"],
            0,
        )
        results = self.client.get(f"/api/v1/jobs/{job_id}/results").json()
        self.assertFalse(any(item["rule_id"] == "CEDULA_MANUAL" for item in results))
        audit = self.client.get(f"/api/v1/jobs/{job_id}/audit").json()
        self.assertTrue(any(
            item["action"] == "CEDULA_VERIFICATIONS_INVALIDATED_BY_REPROCESS"
            for item in audit
        ))

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
        self.assertIn("no confirman la identidad", response.json()["results"][0]["message"])
        job = self.client.get(f"/api/v1/jobs/{uploaded.json()['id']}").json()
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
        job = self.client.get(f"/api/v1/jobs/{uploaded.json()['id']}").json()
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
        self.assertNotIn("11111111115", str(metadata))
        self.assertEqual(response.json()["results"][0]["outcome"], "NO_VERIFICABLE")

    def test_checksum_valid_candidate_match_requires_confident_ocr_on_both_pages(self):
        class ConfidentRosterAndDocumentProvider(FakeOCRProvider):
            def extract_text(self, pdf_path: str) -> OCRDocumentText:
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
        metadata = self.client.get(f"/api/v1/jobs/{uploaded.json()['id']}").json()["metadata"]
        self.assertEqual(metadata["cedula_checksum_valid_count"], 1)
        self.assertEqual(metadata["roster_checksum_valid_count"], 1)
        self.assertEqual(metadata["evidence_checksum_valid_count"], 1)
        self.assertEqual(metadata["candidate_matches"], 1)
        self.assertEqual(metadata["verified_identities"], 0)
        self.assertIn("no confirman la identidad", response.json()["message"])
        self.assertNotIn("11111111115", str(metadata))

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
