from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


PASSWORD_HASH_ITERATIONS = 600_000
PASSWORD_HASH_NAME = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Passwords must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS)
    return "$".join((
        PASSWORD_HASH_NAME,
        str(PASSWORD_HASH_ITERATIONS),
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    ))


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, rounds_text, salt_text, digest_text = encoded_hash.split("$")
        rounds = int(rounds_text)
        if algorithm != PASSWORD_HASH_NAME or not 100_000 <= rounds <= 2_000_000:
            return False
        salt = base64.b64decode(salt_text, altchars=b"-_", validate=True)
        expected_digest = base64.b64decode(digest_text, altchars=b"-_", validate=True)
    except (AttributeError, ValueError):
        return False

    actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(actual_digest, expected_digest)
