"""
Authentication database models.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Text, DateTime, Integer, Boolean, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.sqlite import JSON


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "auth_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="operator", nullable=False)  # operator, viewer, admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    devices: Mapped[list["Device"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Device(Base):
    __tablename__ = "auth_devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)  # e.g., "iPhone 15 Pro"
    platform: Mapped[str] = mapped_column(String(50), nullable=False)  # ios, android, desktop
    platform_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    app_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)  # Ed25519 PEM
    key_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # SHA256 of public key
    challenge: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    challenge_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Human-readable pairing code, shown in the app and entered in the browser
    # at /connect to approve this device. Cleared (single-use) once approved.
    pairing_code: Mapped[Optional[str]] = mapped_column(String(16), unique=True, nullable=True)
    pairing_code_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_trusted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="devices")
    sessions: Mapped[list["Session"]] = relationship(back_populates="device", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_auth_devices_user_id", "user_id"),
        Index("ix_auth_devices_key_id", "key_id"),
        Index("ix_auth_devices_pairing_code", "pairing_code"),
    )


class Session(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey("auth_devices.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)  # SHA256
    access_token_jti: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # JWT ID for revocation
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="sessions")
    device: Mapped["Device"] = relationship(back_populates="sessions")

    __table_args__ = (
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_device_id", "device_id"),
        Index("ix_auth_sessions_expires_at", "expires_at"),
    )


class ConnectSession(Base):
    """
    A single-use pairing session created by `molly connect` (run on the VPS
    itself). Its token is the proof that whoever holds the connect URL was
    handed it by someone with shell access to the box — that's the root of
    trust for approving a new device.
    """
    __tablename__ = "auth_connect_sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending, approved, expired
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approved_device_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class OAuthAccount(Base):
    __tablename__ = "auth_oauth_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # github, google, microsoft
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # encrypted
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # encrypted
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="oauth_accounts")

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        Index("ix_auth_oauth_accounts_user_id", "user_id"),
    )


class RefreshTokenRevocationList(Base):
    """Blocklist for revoked refresh tokens (for immediate revocation)."""
    __tablename__ = "auth_refresh_token_revocations"

    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)