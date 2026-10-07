import unittest
from uuid import uuid4

from packages.domain.enums import DocumentType, ResultOutcome, RuleCode
from packages.domain.models import IdentityDocument, Participant
from packages.shared.normalization import normalize_document_number
from packages.validation.engine import ValidationEngine


class ValidationEngineTests(unittest.TestCase):
    def test_normalize_document_number(self):
        self.assertEqual(normalize_document_number("111-1111111-5"), "11111111115")
        self.assertEqual(normalize_document_number("  123 456 789 "), "123456789")

    def test_valid_cedula_match(self):
        participant = Participant(id=uuid4(), list_document_number="11111111115")
        document = IdentityDocument(id=uuid4(), document_type=DocumentType.CEDULA, document_number_normalized="11111111115")

        result = ValidationEngine().evaluate(participant, document)[0]
        self.assertEqual(result.outcome, ResultOutcome.CORRECTO)

    def test_illegible_cedula(self):
        participant = Participant(id=uuid4(), list_document_number="11111111115")
        document = IdentityDocument(id=uuid4(), document_type=DocumentType.CEDULA, document_number_normalized=None)

        result = ValidationEngine().evaluate(participant, document)[0]
        self.assertEqual(result.outcome, ResultOutcome.NO_VERIFICABLE)
        self.assertEqual(result.reason_code, RuleCode.CEDULA_NO_LEGIBLE)

    def test_foreign_participant_with_carnet_requires_revision(self):
        participant = Participant(id=uuid4(), is_foreign=True, list_document_number="P123456")
        document = IdentityDocument(id=uuid4(), document_type=DocumentType.CARNET, document_number_normalized="P123456")

        result = ValidationEngine().evaluate(participant, document)[0]
        self.assertEqual(result.outcome, ResultOutcome.REVISION)
        self.assertEqual(result.reason_code, RuleCode.DOCUMENTO_EXTRANJERO_NO_PASAPORTE)

    def test_duplicate_detection(self):
        participants = [
            Participant(id=uuid4(), list_document_number="11111111115"),
            Participant(id=uuid4(), list_document_number="11111111115"),
        ]

        results = ValidationEngine().detect_duplicate_documents(participants)
        self.assertTrue(results)
        self.assertEqual(results[0].reason_code, RuleCode.CEDULA_DUPLICADA)


if __name__ == "__main__":
    unittest.main()
