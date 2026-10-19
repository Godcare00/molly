"""
Hashing for high-entropy random tokens (worker enrollment tokens, worker
credentials, tenant API keys) - plain salted SHA-256 is fine here because
these are 32-byte secrets.token_urlsafe() values, not user-chosen
passwords; there's no dictionary/brute-force surface a slow KDF like
bcrypt would meaningfully defend against, and the constant-time compare
is what actually matters.
"""
from __future__ import annotations

import hashlib
import secrets


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def secrets_match(provided: str, stored_hash: str) -> bool:
    return secrets.compare_digest(hash_secret(provided), stored_hash)
