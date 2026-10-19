"""
Real email/password accounts for a tenant's admin-side session - replaces
having to run `python -m app.cli create-tenant` on a box you have shell
access to and copy-paste a raw API key into the app. This sits *alongside*,
not instead of, the X-API-Key scheme in auth/tenant_auth.py -
get_tenant_admin accepts either, so scripts/CI can keep using a long-lived
API key while the app/browser go through a normal signup -> login ->
session flow.

Deliberately out of scope here, same as the rest of this build (see
top-level README's "what's still a deliberate scope boundary" section):
email verification, password reset, and multiple users per tenant sharing
one login surface with distinct roles. `User.role` exists and signup
always creates an "admin", but nothing yet stops or lets a second person
sign up onto the same tenant - that's a real feature (invites), not a fix.

Note this is account/tenant identity, plus a first step toward having
something to run Molly on: signup also mints this tenant's first
worker-enrollment token (see mint_enrollment_token() in admin_workers.py)
so the app can show "run this on your server" right away. It still does not
pair a device - pairing a specific phone to a specific worker goes
through the code flow in api/pairing.py; a logged-in session is
*accepted* there (see its optional Authorization header) to link the
resulting device to a user, but is not required, preserving the original
no-account pairing path.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password, verify_password
from app.auth.tenant_auth import hash_api_key
from app.auth.tokens import UserClaims, mint_user_token
from app.config import settings
from app.db import get_db
from app.models import Tenant, User
from app.api.admin_workers import mint_enrollment_token

router = APIRouter()


class SignupBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    tenant_name: str = Field(min_length=1, max_length=200)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class SessionResponse(BaseModel):
    session_token: str
    tenant_id: str
    user_id: str
    email: str
    role: str


class SignupResponse(SessionResponse):
    # Shown once, at creation, same spirit as any "here's your API key,
    # save it - we can't show it to you again" flow: it's stored only as
    # a hash (Tenant.api_key_hash), same as everything else in
    # app/security.py. Lets someone who *did* sign up in the app still
    # script/CI against the tenant-admin endpoints later if they want to.
    api_key: str
    # This tenant's first worker-enrollment token (see
    # app/models.py's WorkerEnrollmentToken and admin_workers.py). Minted
    # automatically here so the app can walk a brand-new user straight
    # from "create account" to "run this on your server" without a separate
    # admin call - see mint_enrollment_token(). Same one-time,
    # short-lived semantics as a token minted via /admin/workers/tokens;
    # additional workers/tokens after this one do go through that
    # endpoint (or `molly` app's future "add another server" action).
    enrollment_token: str
    enrollment_token_expires_in_minutes: int


@router.post("/auth/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupBody, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with that email already exists")

    api_key = secrets.token_urlsafe(32)
    tenant = Tenant(name=body.tenant_name, api_key_hash=hash_api_key(api_key))
    db.add(tenant)
    await db.flush()  # assigns tenant.id before the User row below references it

    user = User(
        tenant_id=tenant.id,
        email=body.email,
        password_hash=hash_password(body.password),
        role="admin",
    )
    db.add(user)

    enrollment_row = mint_enrollment_token(db, tenant.id, label_hint="")

    await db.commit()
    await db.refresh(user)

    token = mint_user_token(UserClaims(tenant_id=tenant.id, user_id=user.id, email=user.email, role=user.role))
    return SignupResponse(
        session_token=token,
        tenant_id=tenant.id,
        user_id=user.id,
        email=user.email,
        role=user.role,
        api_key=api_key,
        enrollment_token=enrollment_row.token,
        enrollment_token_expires_in_minutes=settings.enrollment_token_ttl_minutes,
    )


@router.post("/auth/login", response_model=SessionResponse)
async def login(body: LoginBody, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    # Constant-shape failure whether the email doesn't exist or the
    # password is wrong - don't let this endpoint be used to enumerate
    # which emails have accounts.
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = mint_user_token(UserClaims(tenant_id=user.tenant_id, user_id=user.id, email=user.email, role=user.role))
    return SessionResponse(session_token=token, tenant_id=user.tenant_id, user_id=user.id, email=user.email, role=user.role)
