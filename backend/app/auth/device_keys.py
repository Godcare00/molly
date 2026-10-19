"""
Device key (Ed25519) registration and verification.
"""
import base64
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature
from sqlalchemy import select

from app.auth.config import auth_settings
from app.auth.models import Device
from app.auth.database import AsyncSession


class PendingApprovalError(ValueError):
    """Signature is valid but the device hasn't been approved via /connect yet.
    Distinct from other ValueErrors so callers can tell "keep polling" apart
    from a terminal failure (expired challenge, bad signature, revoked)."""


class DeviceKeyManager:
    """Manages device public key registration and challenge-response verification."""

    @staticmethod
    def validate_public_key(pem: str) -> ed25519.Ed25519PublicKey:
        """Validate and load Ed25519 public key from PEM."""
        try:
            key = serialization.load_pem_public_key(pem.encode())
            if not isinstance(key, ed25519.Ed25519PublicKey):
                raise ValueError("Key must be Ed25519")
            return key
        except Exception as e:
            raise ValueError(f"Invalid public key: {e}")

    @staticmethod
    def compute_key_id(public_key: ed25519.Ed25519PublicKey) -> str:
        """Compute key identifier (SHA256 of raw public key)."""
        raw = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return hashlib.sha256(raw).hexdigest()[:64]

    @staticmethod
    def generate_challenge() -> str:
        """Generate a cryptographically random challenge."""
        return secrets.token_urlsafe(32)

    # Characters chosen to avoid visual ambiguity when read off a phone
    # screen and typed into a browser (no 0/O, 1/I/L).
    _PAIRING_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

    @classmethod
    def generate_pairing_code(cls) -> str:
        """Generate a short human-friendly pairing code (7 chars, no dashes).
        Clients are free to render it as e.g. 'K7P-4RXQ' for readability."""
        return "".join(secrets.choice(cls._PAIRING_CODE_ALPHABET) for _ in range(7))

    @staticmethod
    def normalize_pairing_code(code: str) -> str:
        """Normalize user-entered code for comparison (case/space/dash tolerant)."""
        return "".join(ch for ch in code.upper() if ch.isalnum())

    @staticmethod
    def verify_challenge_signature(
        public_key: ed25519.Ed25519PublicKey,
        challenge: str,
        signature_b64: str
    ) -> bool:
        """Verify challenge signature."""
        try:
            # Decode base64url signature
            signature = base64.urlsafe_b64decode(signature_b64 + "==")
            public_key.verify(signature, challenge.encode())
            return True
        except (InvalidSignature, ValueError):
            return False

    @classmethod
    async def register_device(
        cls,
        db_session: AsyncSession,
        user_id: str,
        public_key_pem: str,
        device_name: str,
        platform: str,
        platform_version: Optional[str] = None,
        app_version: Optional[str] = None,
    ) -> Tuple[Device, str, str, datetime]:
        """
        Register a new device.
        Returns: (device, challenge, pairing_code, pairing_code_expires_at)
        """
        public_key = cls.validate_public_key(public_key_pem)
        key_id = cls.compute_key_id(public_key)

        # Check if key already registered
        result = await db_session.execute(select(Device).where(Device.key_id == key_id))
        existing = result.scalar_one_or_none()
        if existing:
            raise ValueError("Device key already registered")

        # Generate challenge
        challenge = cls.generate_challenge()
        challenge_expires = datetime.now(timezone.utc) + timedelta(
            minutes=auth_settings.device_key_challenge_expire_minutes
        )

        # Generate the pairing code shown in-app; this is what an operator
        # enters at /connect to approve the device. Retry on the unlikely
        # collision with another still-pending code.
        pairing_code = cls.generate_pairing_code()
        for _ in range(5):
            existing_code = await db_session.execute(
                select(Device).where(Device.pairing_code == pairing_code)
            )
            if existing_code.scalar_one_or_none() is None:
                break
            pairing_code = cls.generate_pairing_code()
        pairing_code_expires = datetime.now(timezone.utc) + timedelta(
            minutes=auth_settings.pairing_code_expire_minutes
        )

        # Create device record. It stays untrusted until an operator
        # approves it via the /connect flow — signing the challenge alone
        # is no longer sufficient to gain access.
        device = Device(
            id=secrets.token_urlsafe(16),
            user_id=user_id,
            name=device_name,
            platform=platform,
            platform_version=platform_version,
            app_version=app_version,
            public_key=public_key_pem,
            key_id=key_id,
            challenge=challenge,
            challenge_expires_at=challenge_expires,
            pairing_code=pairing_code,
            pairing_code_expires_at=pairing_code_expires,
            is_trusted=False,
        )
        db_session.add(device)
        await db_session.flush()

        return device, challenge, pairing_code, pairing_code_expires

    @classmethod
    async def verify_device_challenge(
        cls,
        db_session: AsyncSession,
        device_id: str,
        signature_b64: str
    ) -> Device:
        """Verify challenge signature and mark device as verified."""
        result = await db_session.execute(select(Device).where(Device.id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            raise ValueError("Device not found")

        if device.is_revoked:
            raise ValueError("Device is revoked")

        if not device.challenge:
            raise ValueError("No pending challenge")

        if device.challenge_expires_at:
            # Handle both naive and aware datetimes
            expires = device.challenge_expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < datetime.now(timezone.utc):
                raise ValueError("Challenge expired")

        public_key = cls.validate_public_key(device.public_key)
        if not cls.verify_challenge_signature(public_key, device.challenge, signature_b64):
            raise ValueError("Invalid signature")

        # Signing the challenge only proves possession of the private key —
        # it does NOT grant trust. Trust is granted separately, by an
        # operator approving the device's pairing code at /connect. Until
        # that's happened, hold here even though the signature is valid.
        if not device.is_trusted:
            raise PendingApprovalError("Device not yet approved")

        # Clear challenge (single use)
        device.challenge = None
        device.challenge_expires_at = None
        await db_session.flush()

        return device

    @classmethod
    async def revoke_device(
        cls,
        db_session: AsyncSession,
        device_id: str,
        reason: Optional[str] = None
    ) -> Device:
        """Revoke a device."""
        result = await db_session.execute(select(Device).where(Device.id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            raise ValueError("Device not found")

        device.is_revoked = True
        device.revoked_at = datetime.now(timezone.utc)
        device.revoked_reason = reason
        await db_session.flush()

        return device

    @classmethod
    async def set_device_trust(
        cls,
        db_session: AsyncSession,
        device_id: str,
        is_trusted: bool
    ) -> Device:
        """Set device trust status."""
        result = await db_session.execute(select(Device).where(Device.id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            raise ValueError("Device not found")

        device.is_trusted = is_trusted
        await db_session.flush()

        return device