"""
Every table here carries tenant_id, per ARCHITECTURE.md's own scaling
note in the worker repo ("Multi-user: Add user_id to all tables"). This is
the gateway's whole reason to exist: it's the one place that knows about
tenants at all. The worker's own SQLite (conversations, messages,
approvals, images) is untouched and stays single-tenant-shaped, because
from the worker's point of view it only ever serves one tenant's traffic
- whichever tenant owns it.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.timeutils import utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    # Simplified stand-in for real account auth (OAuth/OIDC, SSO, billing
    # plan, etc). Good enough to demonstrate tenant isolation; swap for a
    # real user/session system before this is a real SaaS - see README.
    api_key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)

    workers: Mapped[list["Worker"]] = relationship(back_populates="tenant")
    devices: Mapped[list["Device"]] = relationship(back_populates="tenant")


class Worker(Base):
    """One registered server. `secret` is the shared HMAC key used to sign
    and verify relay tokens for this worker specifically - scoped
    per-worker so a compromised worker can be revoked without affecting
    any other worker in the fleet, including other workers on the same
    tenant's account."""
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(128))  # hash of the long-lived worker_token presented in HELLO
    secret: Mapped[str] = mapped_column(String(128))      # HS256 key for this worker's relay tokens
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="workers")


class WorkerEnrollmentToken(Base):
    """One-time token an admin mints and pastes into `molly worker enroll`
    on the server. Possession of this token (delivered out of band, e.g.
    copy-pasted into a shell already running on the box) is this
    architecture's replacement for app/auth/connect.py's local-secret-file
    proof, which only worked because the gateway and the server used to be
    the same machine."""
    __tablename__ = "worker_enrollment_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    label_hint: Mapped[str] = mapped_column(String(200), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime())
    used_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class User(Base):
    """A person on a tenant's account, authenticated with a real
    email/password (see app/auth/passwords.py and app/api/account.py's
    /auth/signup + /auth/login) rather than the tenant-wide API key alone.
    `email` is globally unique - not scoped per-tenant - since login looks
    a user up by email before it knows which tenant they belong to."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="admin")  # admin | member
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)


class Device(Base):
    """A paired mobile device. default_worker_id is which of the tenant's
    workers this device's conversations route to - set at pairing time,
    changeable later (e.g. a "switch server" action in Settings)."""
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    platform: Mapped[str] = mapped_column(String(50), default="")
    default_worker_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workers.id"), nullable=True)

    is_trusted: Mapped[bool] = mapped_column(default=False)
    is_revoked: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)

    tenant: Mapped[Tenant] = relationship(back_populates="devices")


class RefreshToken(Base):
    """Backing store for refresh-token rotation, ported from the
    worker's original single-tenant app/auth/jwt.py pattern with
    tenant_id added. Only a hash of the token is stored (same reasoning
    as Worker.token_hash / Tenant.api_key_hash - these are high-entropy
    random values, not passwords). `replaced_by` records the rotation
    chain: using an already-rotated refresh token is a strong signal of
    a stolen/replayed token, not just an expired one, so it's kept
    distinguishable from a plain expiry for future auditing/alerting."""
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey("devices.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    replaced_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class PairingCode(Base):
    """A short-lived code the server itself generates (via `molly connect`,
    authenticated as that worker) for a human to type into the mobile
    app. No admin/browser step: whoever can read the code printed on the
    server's own terminal is trusted to pair a device, the same trust model
    the original single-tenant `molly connect` used - just brokered
    through the gateway instead of a locally-served page."""
    __tablename__ = "pairing_codes"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    worker_id: Mapped[str] = mapped_column(String(36), ForeignKey("workers.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime())
    used_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("devices.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=utcnow)
