from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from packages.domain.contracts import OCRDocumentText


@dataclass(frozen=True)
class AIAssistedOCRResult:
    provider: str
    model: str
    summary: str
    participant_items: list[dict[str, Any]]
    confidence: float | None = None
    warnings: list[str] | None = None
    raw: dict[str, Any] | None = None


class AIAssistedOCRAnalyzer:
    def __init__(self) -> None:
        self.base_url = os.getenv("AI_OCR_BASE_URL", "http://127.0.0.1:11434/v1").strip()
        self.api_key = os.getenv("AI_OCR_API_KEY", "").strip()
        self.model = os.getenv("AI_OCR_MODEL", "qwen3:14b").strip()
        self.timeout = float(os.getenv("AI_OCR_TIMEOUT_SECONDS", "45"))
        self.max_page_snippets = int(os.getenv("AI_OCR_MAX_PAGE_SNIPPETS", "24"))
        self.max_chars_per_page = int(os.getenv("AI_OCR_MAX_CHARS_PER_PAGE", "1800"))

        if not self._is_local_endpoint(self.base_url):
            raise ValueError("AI OCR must use a local OpenAI-compatible endpoint")

    def is_configured(self) -> bool:
        return bool(self.base_url and self.model)

    def analyze(
        self,
        document: OCRDocumentText,
        *,
        focus_pages: list[int] | None = None,
        participant_hints: list[dict[str, Any]] | None = None,
        action_code: str | None = None,
    ) -> AIAssistedOCRResult | None:
        if not self.is_configured():
            return None

        page_payload = self._build_page_payload(document, focus_pages=focus_pages)
        if not page_payload:
            return None

        prompt = self._build_prompt(page_payload, participant_hints=participant_hints, action_code=action_code)
        response = self._post_chat_completion(prompt)
        content = self._extract_message_content(response)
        data = self._parse_json_content(content)

        participant_items_raw = data.get("participant_items", [])
        if not isinstance(participant_items_raw, list):
            raise ValueError("AI OCR response participant_items must be a list")

        participant_items = [self._normalize_participant_item(item) for item in participant_items_raw]
        return AIAssistedOCRResult(
            provider="openai-compatible",
            model=self.model,
            summary=str(data.get("summary") or "").strip(),
            participant_items=participant_items,
            confidence=self._coerce_float(data.get("confidence")),
            warnings=self._normalize_string_list(data.get("warnings")),
            raw=data,
        )

    def _build_page_payload(
        self,
        document: OCRDocumentText,
        *,
        focus_pages: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        pages_by_number = {page.page_number: page for page in document.pages}
        total_pages = len(document.pages)
        selected_numbers: list[int] = []

        if total_pages <= self.max_page_snippets or self.max_page_snippets <= 0:
            selected_numbers.extend(page.page_number for page in document.pages)
        else:
            head_count = max(4, self.max_page_snippets // 3)
            tail_count = max(4, self.max_page_snippets // 3)
            selected_numbers.extend(page.page_number for page in document.pages[:head_count])
            selected_numbers.extend(page.page_number for page in document.pages[-tail_count:])
            if focus_pages:
                selected_numbers.extend(self._normalize_int_list(focus_pages))

        selected_numbers = self._deduplicate_ints(selected_numbers)
        if self.max_page_snippets > 0:
            selected_numbers = selected_numbers[: self.max_page_snippets]

        payload: list[dict[str, Any]] = []
        for page_number in selected_numbers:
            page = pages_by_number.get(page_number)
            if page is None:
                continue
            text = (page.text or "").strip()
            if not text:
                continue
            payload.append(
                {
                    "page_number": page.page_number,
                    "confidence": page.confidence,
                    "text": text[: self.max_chars_per_page],
                }
            )

        return payload

    def _build_prompt(
        self,
        pages: list[dict[str, Any]],
        *,
        participant_hints: list[dict[str, Any]] | None = None,
        action_code: str | None = None,
    ) -> str:
        payload = {
            "action_code": action_code,
            "participant_hints": participant_hints or [],
            "pages": pages,
        }
        return (
            "Eres un analista documental especializado en acciones formativas de SIVAF. "
            "Debes interpretar el OCR ya extraído y devolver SOLO JSON válido, sin markdown ni explicaciones. "
            "Si hay incertidumbre, marca review_status como REQUIERE_REVISION. "
            "No inventes cédulas ni nombres que no aparezcan en el texto. "
            "Usa page_number para asociar páginas de lista y de documentos.\n\n"
            "Estructura requerida:\n"
            "{"
            '"summary": string, '
            '"confidence": number|null, '
            '"warnings": [string], '
            '"participant_items": ['
            "{"
            '"reference": string, '
            '"full_name": string|null, '
            '"cedula_masked": string|null, '
            '"review_status": "OK_AUTOMATICO" o "REQUIERE_REVISION", '
            '"review_reason": string, '
            '"roster_pages": [number], '
            '"document_pages": [number], '
            '"roster_sheets": [number], '
            '"document_sheets": [number]'
            "}"
            "]"
            "}\n\n"
            f"Datos:\n{json.dumps(payload, ensure_ascii=False)}"
        )

    def _post_chat_completion(self, prompt: str) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Responde únicamente con JSON válido."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _extract_message_content(response: dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content

        content = response.get("content")
        if isinstance(content, str):
            return content

        raise ValueError("AI OCR response did not include a message content")

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError("AI OCR response was not valid JSON") from exc

        if not isinstance(parsed, dict):
            raise ValueError("AI OCR response JSON must be an object")
        return parsed

    @staticmethod
    def _normalize_participant_item(item: Any) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise ValueError("AI OCR participant item must be an object")

        roster_pages = AIAssistedOCRAnalyzer._deduplicate_ints(
            AIAssistedOCRAnalyzer._normalize_int_list(item.get("roster_pages"))
        )
        document_pages = AIAssistedOCRAnalyzer._deduplicate_ints(
            AIAssistedOCRAnalyzer._normalize_int_list(item.get("document_pages"))
        )
        roster_sheets = AIAssistedOCRAnalyzer._deduplicate_ints(
            AIAssistedOCRAnalyzer._normalize_int_list(item.get("roster_sheets"))
        )
        document_sheets = AIAssistedOCRAnalyzer._deduplicate_ints(
            AIAssistedOCRAnalyzer._normalize_int_list(item.get("document_sheets"))
        )

        review_status = str(item.get("review_status") or item.get("status") or "REQUIERE_REVISION").strip().upper()
        if review_status in {"OK", "APROBADO", "CORRECTO", "AUTOMATICO", "OK_AUTOMATICO"}:
            review_status = "OK_AUTOMATICO"
        elif review_status in {"REVISAR", "REVISION", "REQUIERE_REVISION", "PENDIENTE"}:
            review_status = "REQUIERE_REVISION"
        elif "OK" in review_status and "REV" not in review_status:
            review_status = "OK_AUTOMATICO"
        else:
            review_status = "REQUIERE_REVISION"

        return {
            "reference": str(item.get("reference") or item.get("id") or item.get("position") or "").strip(),
            "full_name": AIAssistedOCRAnalyzer._normalize_optional_string(item.get("full_name") or item.get("name")),
            "cedula_masked": AIAssistedOCRAnalyzer._normalize_optional_string(
                item.get("cedula_masked") or item.get("cedula") or item.get("document_number")
            ),
            "review_status": review_status,
            "review_reason": str(item.get("review_reason") or item.get("reason") or "").strip(),
            "roster_pages": roster_pages,
            "document_pages": document_pages,
            "roster_sheets": roster_sheets,
            "document_sheets": document_sheets,
        }

    @staticmethod
    def _normalize_optional_string(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for entry in value:
            text = str(entry).strip()
            if text:
                items.append(text)
        return items

    @staticmethod
    def _normalize_int_list(value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        items: list[int] = []
        for entry in value:
            try:
                items.append(int(entry))
            except (TypeError, ValueError):
                continue
        return items

    @staticmethod
    def _deduplicate_ints(values: list[int]) -> list[int]:
        seen: set[int] = set()
        result: list[int] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    @staticmethod
    def _is_local_endpoint(base_url: str) -> bool:
        normalized = base_url.strip().lower()
        return (
            normalized.startswith("http://127.0.0.1")
            or normalized.startswith("http://localhost")
            or normalized.startswith("https://127.0.0.1")
            or normalized.startswith("https://localhost")
        )

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def create_ai_assisted_analyzer() -> AIAssistedOCRAnalyzer:
    return AIAssistedOCRAnalyzer()
