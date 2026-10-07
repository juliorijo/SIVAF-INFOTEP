from __future__ import annotations

import re

from packages.shared.normalization import normalize_document_number

_OCR_DIGIT_TRANSLATION = str.maketrans({
    "O": "0",
    "Q": "0",
    "D": "0",
    "I": "1",
    "L": "1",
    "S": "5",
    "B": "8",
    "G": "6",
    "Z": "2",
})


def normalize_dominican_cedula_candidate(value: str | None) -> str | None:
    """
    Normalize a Dominican cédula candidate from noisy OCR text.

    Handles common OCR substitutions like O/0, I/1, S/5, etc., and supports
    numbers written with separators such as 000-0000000-0.
    """
    if value is None:
        return None

    text = str(value).upper().translate(_OCR_DIGIT_TRANSLATION)
    grouped_match = re.search(
        r"(?<!\d)(\d{3})[\s\-.:_/,;]*([0-9]{7})[\s\-.:_/,;]*([0-9])(?!\d)",
        text,
    )
    if grouped_match is not None:
        return "".join(grouped_match.groups())

    normalized = normalize_document_number(text)
    if normalized is None:
        return None
    digits_only = re.sub(r"\D", "", normalized)
    if re.fullmatch(r"\d{11}", digits_only) is None:
        return None
    return digits_only


def is_dominican_cedula_checksum_valid(value: str | None) -> bool:
    """Validate an 11-digit Dominican cédula candidate using its control digit."""
    normalized = normalize_dominican_cedula_candidate(value)
    if normalized is None or not re.fullmatch(r"\d{11}", normalized):
        return False

    weighted_sum = 0
    for index, character in enumerate(normalized[:10]):
        product = int(character) * (1 if index % 2 == 0 else 2)
        weighted_sum += product // 10 + product % 10

    expected_check_digit = (10 - weighted_sum % 10) % 10
    return int(normalized[-1]) == expected_check_digit
