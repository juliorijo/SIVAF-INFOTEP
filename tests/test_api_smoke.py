import unittest
from io import BytesIO
import os
from pathlib import Path
import secrets
import tempfile
from uuid import uuid4
from unittest.mock import patch

from openpyxl import Workbook
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

from apps.api.auth import hash_password
from apps.api.database import (
    FormativeActionImportORM,
    FormativeActionORM,
    ProcessingJobORM,
    SessionLocal,
    UserORM,
    UserSessionORM,
)
from apps.api import main as api_module
from apps.api.main import app
from packages.document_processing.pdf_service import PdfIngestionService


class ApiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.username = f"api-test-{uuid4().hex[:12]}"
        cls.password = secrets.token_urlsafe(24)
        cls.admin_username = f"api-admin-{uuid4().hex[:12]}"
        cls.admin_password = secrets.token_urlsafe(24)
        cls.other_username = f"api-other-{uuid4().hex[:12]}"
        cls.other_password = secrets.token_urlsafe(24)
        with SessionLocal() as session:
            session.add(UserORM(
                id=str(uuid4()),
                username=cls.username,
                password_hash=hash_password(cls.password),
                role="analyst",
            ))
            session.add(UserORM(
                id=str(uuid4()),
                username=cls.admin_username,
                password_hash=hash_password(cls.admin_password),
                role="admin",
            ))
            session.add(UserORM(
                id=str(uuid4()),
                username=cls.other_username,
                password_hash=hash_password(cls.other_password),
                role="analyst",
            ))
            session.commit()

    @classmethod
    def tearDownClass(cls):
        with SessionLocal() as session:
            users = session.scalars(
                select(UserORM).where(UserORM.username.in_([
                    cls.username, cls.admin_username, cls.other_username,
                ]))
            ).all()
            user_ids = [user.id for user in users]
            if user_ids:
                session.execute(delete(UserSessionORM).where(UserSessionORM.user_id.in_(user_ids)))
                session.execute(delete(UserORM).where(UserORM.id.in_(user_ids)))
            session.execute(delete(FormativeActionORM).where(
                FormativeActionORM.action_code.in_([
                    "SIVAF-TEST-A", "SIVAF-TEST-B", "SIVAF-XLSX-TEST",
                ])
            ))
            session.execute(delete(FormativeActionImportORM).where(
                FormativeActionImportORM.imported_by == cls.admin_username
            ))
            session.commit()

    def setUp(self):
        self.client = TestClient(app)
        self.storage_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage_directory.cleanup)
        previous_pdf_service = api_module.pdf_service
        api_module.pdf_service = PdfIngestionService(self.storage_directory.name)
        self.addCleanup(setattr, api_module, "pdf_service", previous_pdf_service)
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": self.username, "password": self.password},
        )
        self.assertEqual(response.status_code, 200)

    @staticmethod
    def _make_pdf_bytes():
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    def _upload_pdf(self, filename="test.pdf"):
        response = self.client.post(
            "/api/v1/jobs/upload",
            files={"file": (filename, self._make_pdf_bytes(), "application/pdf")},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_postgres_environment_url_escapes_reserved_password_characters(self):
        with patch.dict(os.environ, {
            "DATABASE_URL": "",
            "POSTGRES_USER": "sivaf",
            "POSTGRES_PASSWORD": "pa:ss/word@with?reserved#chars",
            "POSTGRES_HOST": "postgres",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "infotep",
        }):
            from apps.api.database import get_database_url

            parsed = make_url(get_database_url())

        self.assertEqual(parsed.username, "sivaf")
        self.assertEqual(parsed.password, "pa:ss/word@with?reserved#chars")
        self.assertEqual(parsed.host, "postgres")
        self.assertEqual(parsed.database, "infotep")

    def test_api_requires_login_and_login_sets_http_only_cookie(self):
        anonymous_client = TestClient(app)
        self.assertEqual(anonymous_client.get("/api/v1/jobs").status_code, 401)

        invalid_login = anonymous_client.post(
            "/api/v1/auth/login",
            json={"username": self.username, "password": "incorrecta"},
        )
        self.assertEqual(invalid_login.status_code, 401)

        valid_login = anonymous_client.post(
            "/api/v1/auth/login",
            json={"username": self.username, "password": self.password},
        )
        self.assertEqual(valid_login.status_code, 200)
        self.assertIn("httponly", valid_login.headers["set-cookie"].lower())
        self.assertEqual(anonymous_client.get("/api/v1/auth/me").json()["username"], self.username)

    def test_logout_revokes_session(self):
        response = self.client.post("/api/v1/auth/logout")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get("/api/v1/jobs").status_code, 401)

    def test_analyst_cannot_delete_jobs(self):
        response = self.client.delete(f"/api/v1/jobs/{uuid4()}")
        self.assertEqual(response.status_code, 403)

    def test_only_admin_can_import_formative_actions(self):
        response = self.client.post(
            "/api/v1/formative-actions/import",
            files={"file": ("actions.csv", b"Codigo de accion,Accion formativa\nA-TEST,Curso de prueba\n", "text/csv")},
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_import_updates_by_code_and_preserves_absent_actions(self):
        admin = TestClient(app)
        login = admin.post(
            "/api/v1/auth/login",
            json={"username": self.admin_username, "password": self.admin_password},
        )
        self.assertEqual(login.status_code, 200)
        first = b"Codigo de accion,Accion formativa,Fecha de inicio,Estado\nSIVAF-TEST-A,Curso A,2026-01-05,Iniciada\nSIVAF-TEST-B,Curso B,2026-02-05,Iniciada\n"
        imported = admin.post(
            "/api/v1/formative-actions/import",
            files={"file": ("inicios.csv", first, "text/csv")},
        )
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.json()["inserted_rows"], 2)
        self.assertEqual(imported.json()["updated_rows"], 0)

        update = b"Codigo de accion,Accion formativa,Fecha de inicio,Estado\nSIVAF-TEST-A,Curso A actualizado,2026-03-05,Actualizada\n"
        updated = admin.post(
            "/api/v1/formative-actions/import",
            files={"file": ("inicios.csv", update, "text/csv")},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["inserted_rows"], 0)
        self.assertEqual(updated.json()["updated_rows"], 1)

        listing = admin.get("/api/v1/formative-actions", params={"q": "SIVAF-TEST-", "limit": 10})
        self.assertEqual(listing.status_code, 200)
        records = {item["action_code"]: item for item in listing.json()["items"]}
        self.assertEqual(set(records), {"SIVAF-TEST-A", "SIVAF-TEST-B"})
        self.assertEqual(records["SIVAF-TEST-A"]["name"], "Curso A actualizado")
        self.assertEqual(records["SIVAF-TEST-B"]["name"], "Curso B")
        self.assertEqual(listing.json()["latest_import"]["updated_rows"], 1)

    def test_admin_imports_xlsx_from_first_worksheet(self):
        admin = TestClient(app)
        admin.post(
            "/api/v1/auth/login",
            json={"username": self.admin_username, "password": self.admin_password},
        )
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Código de acción", "Acción formativa", "Fecha de inicio", "Estado"])
        sheet.append(["SIVAF-XLSX-TEST", "Acción en Excel", "2026-04-01", "Iniciada"])
        buffer = BytesIO()
        workbook.save(buffer)

        response = admin.post(
            "/api/v1/formative-actions/import",
            files={"file": ("inicios.xlsx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["inserted_rows"], 1)
        listing = admin.get("/api/v1/formative-actions", params={"q": "SIVAF-XLSX-TEST"})
        self.assertEqual(listing.json()["items"][0]["name"], "Acción en Excel")

    def test_action_import_recognizes_drive_csv_header_after_preamble(self):
        from apps.api.main import parse_action_import

        content = (
            "\n" * 10
            + "CODIGO_C..,ACCION_F..,FECHA_INI..,ESTADO\n"
            + "SIVAF-CSV-TEST,Acción desde Drive,2026-05-01,Iniciada\n"
        ).encode("utf-8")
        rows, columns = parse_action_import("drive.csv", content)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action_code"], "SIVAF-CSV-TEST")
        self.assertEqual(rows[0]["name"], "Acción desde Drive")
        self.assertEqual(rows[0]["start_date"], "2026-05-01")
        self.assertEqual(rows[0]["status"], "Iniciada")
        self.assertEqual(len(columns), 4)

    def test_dashboard_summary_shape(self):
        response = self.client.get("/api/v1/dashboard/summary")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json()),
            {"total", "pending", "in_review", "incidents", "not_verifiable", "processed"},
        )

    def test_create_and_get_job(self):
        response = self.client.post(
            "/api/v1/jobs",
            json={
                "source_pdf_path": "C:/INFOTEP/Verificacion/entrada/ejemplo.pdf",
                "created_by": "spoofed-user",
                "metadata": {"batch": "test"},
            },
        )
        self.assertEqual(response.status_code, 410)
        self.assertIn("Upload the PDF", response.json()["detail"])

        payload = self._upload_pdf("ejemplo.pdf")
        self.assertIn("id", payload)
        self.assertTrue(payload["evidence_available"])
        self.assertEqual(payload["metadata"]["requested_by"], self.username)
        self.assertNotIn("source_pdf_path", payload)
        job_id = payload["id"]

        get_response = self.client.get(f"/api/v1/jobs/{job_id}")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["source_pdf_name"].split("_", 1)[-1], "ejemplo.pdf")

    def test_pdf_upload_limits_file_size_and_metadata_shape(self):
        oversized_metadata = self.client.post(
            "/api/v1/jobs/upload",
            files={"file": ("metadata.pdf", self._make_pdf_bytes(), "application/pdf")},
            data={"metadata": " " * (16 * 1024 + 1)},
        )
        self.assertEqual(oversized_metadata.status_code, 413)

        non_object_metadata = self.client.post(
            "/api/v1/jobs/upload",
            files={"file": ("metadata.pdf", self._make_pdf_bytes(), "application/pdf")},
            data={"metadata": "[]"},
        )
        self.assertEqual(non_object_metadata.status_code, 400)

        previous_pdf_service = api_module.pdf_service
        api_module.pdf_service = PdfIngestionService(self.storage_directory.name, max_pdf_bytes=8)
        try:
            oversized_pdf = self.client.post(
                "/api/v1/jobs/upload",
                files={"file": ("oversized.pdf", self._make_pdf_bytes(), "application/pdf")},
            )
        finally:
            api_module.pdf_service = previous_pdf_service
        self.assertEqual(oversized_pdf.status_code, 413)
        self.assertIn("upload limit", oversized_pdf.json()["detail"])

    def test_start_processing(self):
        job_id = self._upload_pdf("proceso.pdf")["id"]

        response = self.client.post(f"/api/v1/jobs/{job_id}/process", json={"force": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "REQUIRES_REVIEW")

    def test_human_review_is_persisted_and_audited(self):
        job_id = self._upload_pdf("revision.pdf")["id"]

        response = self.client.put(
            f"/api/v1/jobs/{job_id}/review",
            json={
                "comments": "Revisado manualmente",
                "final_status": "DEVUELTA",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["final_status"], "DEVUELTA")
        self.assertEqual(response.json()["reviewer"], self.username)

        review_response = self.client.get(f"/api/v1/jobs/{job_id}/review")
        self.assertEqual(review_response.status_code, 200)
        self.assertEqual(review_response.json()["reviewer"], self.username)

        audit_response = self.client.get(f"/api/v1/jobs/{job_id}/audit")
        self.assertEqual(audit_response.status_code, 200)
        self.assertEqual(audit_response.json()[0]["action"], "HUMAN_REVIEW_SAVED")

        job_response = self.client.get(f"/api/v1/jobs/{job_id}")
        self.assertEqual(job_response.json()["human_review"]["final_status"], "DEVUELTA")

    def test_human_review_rejects_unknown_final_status(self):
        created = self._upload_pdf("revision-invalida.pdf")
        response = self.client.put(
            f"/api/v1/jobs/{created['id']}/review",
            json={"final_status": "ACEPTADA"},
        )
        self.assertEqual(response.status_code, 422)

    def test_reprocessing_invalidates_current_review_but_preserves_audit(self):
        job_id = self._upload_pdf("reprocesar.pdf")["id"]
        review = self.client.put(
            f"/api/v1/jobs/{job_id}/review",
            json={"final_status": "APROBADA", "comments": "Decisión anterior"},
        )
        self.assertEqual(review.status_code, 200)

        processed = self.client.post(f"/api/v1/jobs/{job_id}/process", json={"force": True})

        self.assertEqual(processed.status_code, 200)
        self.assertIsNone(self.client.get(f"/api/v1/jobs/{job_id}/review").json())
        audit = self.client.get(f"/api/v1/jobs/{job_id}/audit").json()
        self.assertIn("HUMAN_REVIEW_INVALIDATED_BY_REPROCESS", [event["action"] for event in audit])
        self.assertIn("HUMAN_REVIEW_SAVED", [event["action"] for event in audit])

    def test_evidence_endpoint_does_not_serve_files_outside_managed_storage(self):
        job_id = str(uuid4())
        with SessionLocal() as session:
            user = session.scalar(select(UserORM).where(UserORM.username == self.username))
            session.add(ProcessingJobORM(
                id=job_id,
                source_pdf_path=str(Path(__file__).resolve().parents[1] / "README.md"),
                original_file_hash="",
                created_by=user.id,
                payload_metadata={},
            ))
            session.commit()
        response = self.client.get(f"/api/v1/jobs/{job_id}/evidence")
        self.assertEqual(response.status_code, 403)
        preview_response = self.client.get(f"/api/v1/jobs/{job_id}/preview?page=1")
        self.assertEqual(preview_response.status_code, 403)

    def test_analysts_only_access_their_own_jobs_and_admin_can_access_all(self):
        job = self._upload_pdf("private.pdf")
        other = TestClient(app)
        login = other.post(
            "/api/v1/auth/login",
            json={"username": self.other_username, "password": self.other_password},
        )
        self.assertEqual(login.status_code, 200)

        self.assertNotIn(job["id"], [item["id"] for item in other.get("/api/v1/jobs").json()])
        self.assertEqual(other.get("/api/v1/dashboard/summary").json()["total"], 0)
        self.assertEqual(other.get(f"/api/v1/jobs/{job['id']}").status_code, 404)
        self.assertEqual(other.get(f"/api/v1/jobs/{job['id']}/results").status_code, 404)
        self.assertEqual(other.get(f"/api/v1/jobs/{job['id']}/review").status_code, 404)
        self.assertEqual(other.get(f"/api/v1/jobs/{job['id']}/audit").status_code, 404)
        self.assertEqual(other.get(f"/api/v1/jobs/{job['id']}/evidence").status_code, 404)
        self.assertEqual(other.get(f"/api/v1/jobs/{job['id']}/preview?page=1").status_code, 404)
        self.assertEqual(
            other.post(f"/api/v1/jobs/{job['id']}/process", json={"force": True}).status_code,
            404,
        )
        self.assertEqual(
            other.put(f"/api/v1/jobs/{job['id']}/review", json={"comments": "No autorizado"}).status_code,
            404,
        )

        admin = TestClient(app)
        admin.post(
            "/api/v1/auth/login",
            json={"username": self.admin_username, "password": self.admin_password},
        )
        self.assertEqual(admin.get(f"/api/v1/jobs/{job['id']}").status_code, 200)

    def test_evidence_reads_are_audited(self):
        job = self._upload_pdf("audited.pdf")
        response = self.client.get(f"/api/v1/jobs/{job['id']}/evidence")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["cache-control"])
        preview = self.client.get(f"/api/v1/jobs/{job['id']}/preview?page=1")
        self.assertEqual(preview.status_code, 200)
        events = self.client.get(f"/api/v1/jobs/{job['id']}/audit").json()
        actions = [event["action"] for event in events]
        self.assertIn("EVIDENCE_PDF_REQUESTED", actions)
        self.assertIn("EVIDENCE_PREVIEW_GENERATED", actions)


if __name__ == "__main__":
    unittest.main()
