"""
Password hashing for real user accounts (email/password signup + login).

Deliberately *not* reusing app.security.hash_secret's plain-salted-SHA-256
scheme: that one is fine for high-entropy random tokens (worker
credentials, API keys) where there's no dictionary/brute-force surface
worth defending against, but a user-chosen password is exactly a
dictionary-attackable secret. This uses PBKDF2-HMAC-SHA256 with a random
per-password salt and a deliberately slow iteration count instead.

No new dependency (bcrypt/argon2) - stdlib hashlib.pbkdf2_hmac is a fine
KDF for this, and the encoded hash carries its own algorithm tag and
iteration count, so bumping _ITERATIONS later (or swapping _ALGO for a
future scheme) doesn't invalidate already-stored hashes.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations_s, salt, hex_digest = stored_hash.split("$")
        iterations = int(iterations_s)
    except (ValueError, AttributeError):
        return False
    if algo != _ALGO:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations)
    return hmac.compare_digest(candidate.hex(), hex_digest)
