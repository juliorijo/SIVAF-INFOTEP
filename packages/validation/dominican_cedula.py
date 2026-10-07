from __future__ import annotations

import re

from packages.shared.normalization import normalize_document_number


def is_dominican_cedula_checksum_valid(value: str | None) -> bool:
    """Validate an 11-digit Dominican cédula candidate using its control digit."""
    normalized = normalize_document_number(value)
    if normalized is None or not re.fullmatch(r"\d{11}", normalized):
        return False

    weighted_sum = 0
    for index, character in enumerate(normalized[:10]):
        product = int(character) * (1 if index % 2 == 0 else 2)
        weighted_sum += product // 10 + product % 10

    expected_check_digit = (10 - weighted_sum % 10) % 10
    return int(normalized[-1]) == expected_check_digit
