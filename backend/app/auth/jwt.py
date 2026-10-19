"""
JWT token handling with key rotation support.
"""
import jwt
import time
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ed25519
from pathlib import Path

from app.auth.config import auth_settings


class JWTManager:
    """Manages JWT signing keys and token operations."""

    def __init__(self):
        self._private_key: Optional[rsa.RSAPrivateKey] = None
        self._public_key: Optional[rsa.RSAPublicKey] = None
        self._jwks_cache: Optional[Dict] = None
        self._load_or_generate_keys()

    def _load_or_generate_keys(self):
        """Load existing keys or generate new RSA key pair."""
        private_path = Path(auth_settings.jwt_private_key_path).expanduser()
        public_path = Path(auth_settings.jwt_public_key_path).expanduser()

        if private_path.exists() and public_path.exists():
            with open(private_path, "rb") as f:
                self._private_key = serialization.load_pem_private_key(f.read(), password=None)
            with open(public_path, "rb") as f:
                self._public_key = serialization.load_pem_public_key(f.read())
        else:
            # Generate new key pair
            self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            self._public_key = self._private_key.public_key()

            # Save keys
            private_path.parent.mkdir(parents=True, exist_ok=True)
            with open(private_path, "wb") as f:
                f.write(self._private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            with open(public_path, "wb") as f:
                f.write(self._public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                ))

    @property
    def private_key(self) -> rsa.RSAPrivateKey:
        return self._private_key

    @property
    def public_key(self) -> rsa.RSAPublicKey:
        return self._public_key

    def get_jwks(self) -> Dict[str, Any]:
        """Get JSON Web Key Set for public key distribution."""
        if self._jwks_cache is None:
            numbers = self._public_key.public_numbers()
            import base64
            n = base64.urlsafe_b64encode(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")).decode().rstrip("=")
            e = base64.urlsafe_b64encode(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")).decode().rstrip("=")

            self._jwks_cache = {
                "keys": [{
                    "kty": "RSA",
                    "use": "sig",
                    "kid": "molly-1",
                    "alg": "RS256",
                    "n": n,
                    "e": e,
                }]
            }
        return self._jwks_cache

    def create_access_token(
        self,
        subject: str,
        device_id: str,
        role: str = "operator",
        additional_claims: Optional[Dict] = None
    ) -> Tuple[str, str, int]:
        """
        Create access token.
        Returns: (token, jti, expires_in_seconds)
        """
        now = datetime.now(timezone.utc)
        expires_in = auth_settings.jwt_access_token_expire_minutes * 60
        exp = now + timedelta(seconds=expires_in)
        jti = secrets.token_urlsafe(16)

        claims = {
            "iss": auth_settings.jwt_issuer,
            "aud": auth_settings.jwt_audience,
            "sub": subject,
            "device_id": device_id,
            "role": role,
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "jti": jti,
        }
        if additional_claims:
            claims.update(additional_claims)

        token = jwt.encode(claims, self._private_key, algorithm=auth_settings.jwt_algorithm, headers={"kid": "molly-1"})
        return token, jti, expires_in

    def create_refresh_token(self, subject: str, device_id: str) -> Tuple[str, str, int]:
        """Create refresh token. Returns (token, token_hash, expires_in_seconds)."""
        now = datetime.now(timezone.utc)
        expires_in = auth_settings.jwt_refresh_token_expire_days * 24 * 3600
        exp = now + timedelta(seconds=expires_in)

        token = secrets.token_urlsafe(64)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        claims = {
            "iss": auth_settings.jwt_issuer,
            "aud": auth_settings.jwt_audience,
            "sub": subject,
            "device_id": device_id,
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "jti": token_hash,
        }

        jwt_token = jwt.encode(claims, self._private_key, algorithm=auth_settings.jwt_algorithm, headers={"kid": "molly-1"})
        return jwt_token, token_hash, expires_in

    def verify_token(self, token: str, expected_type: Optional[str] = None) -> Dict[str, Any]:
        """Verify and decode JWT token."""
        try:
            payload = jwt.decode(
                token,
                self._public_key,
                algorithms=[auth_settings.jwt_algorithm],
                audience=auth_settings.jwt_audience,
                issuer=auth_settings.jwt_issuer,
                options={"require": ["exp", "iat", "sub", "type"]}
            )
            if expected_type and payload.get("type") != expected_type:
                raise jwt.InvalidTokenError(f"Expected token type {expected_type}")
            return payload
        except jwt.ExpiredSignatureError:
            raise jwt.InvalidTokenError("Token expired")
        except jwt.InvalidTokenError as e:
            raise jwt.InvalidTokenError(f"Invalid token: {e}")

    def decode_unverified(self, token: str) -> Dict[str, Any]:
        """Decode token without verification (for debugging)."""
        return jwt.decode(token, options={"verify_signature": False})


# Global instance
jwt_manager = JWTManager()


def hash_refresh_token(token: str) -> str:
    """Hash refresh token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_refresh_token_hash(token: str, stored_hash: str) -> bool:
    """Verify refresh token against stored hash."""
    return hash_refresh_token(token) == stored_hash