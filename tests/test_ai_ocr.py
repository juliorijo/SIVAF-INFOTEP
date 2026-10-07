import json
import os
import unittest
from unittest.mock import patch

from packages.domain.contracts import OCRDocumentText, OCRPageText
from packages.ocr.ai_assisted_analyzer import AIAssistedOCRAnalyzer


class AIAssistedOCRAnalyzerTests(unittest.TestCase):
    def test_analyze_parses_openai_compatible_json(self):
        document = OCRDocumentText(
            pages=[
                OCRPageText(page_number=1, text="LISTA DE PARTICIPANTES 111-1111111-5", confidence=0.9),
                OCRPageText(page_number=2, text="CEDULA 11111111115", confidence=0.92),
            ],
            provider="test-provider",
        )

        with patch.dict(os.environ, {
            "AI_OCR_BASE_URL": "https://ai.example.test/v1",
            "AI_OCR_API_KEY": "test-key",
            "AI_OCR_MODEL": "gpt-test",
        }, clear=False):
            analyzer = AIAssistedOCRAnalyzer()
            with patch("packages.ocr.ai_assisted_analyzer.httpx.Client") as client_class:
                client = client_class.return_value.__enter__.return_value
                response = client.post.return_value
                response.raise_for_status.return_value = None
                response.json.return_value = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps({
                                    "summary": "Dos participantes detectados.",
                                    "confidence": 0.87,
                                    "warnings": ["Texto parcial"],
                                    "participant_items": [
                                        {
                                            "reference": "P-001",
                                            "full_name": "Juan Pérez",
                                            "cedula": "111-1111111-5",
                                            "review_status": "ok",
                                            "review_reason": "Coincidencia clara",
                                            "roster_pages": [1],
                                            "document_pages": [2],
                                            "roster_sheets": [1],
                                            "document_sheets": [1],
                                        }
                                    ],
                                }, ensure_ascii=False),
                            }
                        }
                    ]
                }

                result = analyzer.analyze(document, focus_pages=[1, 2], action_code="2026-000001")

        self.assertIsNotNone(result)
        self.assertEqual(result.model, "gpt-test")
        self.assertEqual(result.summary, "Dos participantes detectados.")
        self.assertEqual(result.confidence, 0.87)
        self.assertEqual(result.warnings, ["Texto parcial"])
        self.assertEqual(result.participant_items[0]["review_status"], "OK_AUTOMATICO")
        self.assertEqual(result.participant_items[0]["cedula_masked"], "111-1111111-5")
        self.assertEqual(result.participant_items[0]["roster_pages"], [1])
        self.assertEqual(result.participant_items[0]["document_pages"], [2])


if __name__ == "__main__":
    unittest.main()
