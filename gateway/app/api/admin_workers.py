from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tenant_auth import get_tenant_admin
from app.config import settings
from app.timeutils import utcnow
from app.db import get_db
from app.models import Tenant, Worker, WorkerEnrollmentToken
from app.security import hash_secret
from app.tunnel.registry import DistributedWorkerConnection, WorkerConnection, registry

router = APIRouter()


def mint_enrollment_token(db: AsyncSession, tenant_id: str, label_hint: str = "") -> WorkerEnrollmentToken:
    """Create (but don't commit) a one-time enrollment token row. Shared by
    the explicit /admin/workers/tokens endpoint below and by /auth/signup
    (app/api/account.py), which mints a worker's first enrollment token
    automatically so a brand-new tenant doesn't need a separate admin call
    just to get their first server enrolled."""
    row = WorkerEnrollmentToken(
        token=secrets.token_urlsafe(24),
        tenant_id=tenant_id,
        label_hint=label_hint,
        expires_at=utcnow() + timedelta(minutes=settings.enrollment_token_ttl_minutes),
    )
    db.add(row)
    return row


class CreateTokenBody(BaseModel):
    label_hint: str = ""


@router.post("/admin/workers/tokens")
async def create_enrollment_token(
    body: CreateTokenBody,
    tenant: Tenant = Depends(get_tenant_admin),
    db: AsyncSession = Depends(get_db),
):
    """Mint a one-time token to hand to `molly worker enroll` on a new server.
    Short-lived on purpose - it only needs to survive the copy/paste from
    this response into a shell on the box."""
    row = mint_enrollment_token(db, tenant.id, body.label_hint)
    await db.commit()
    return {
        "enrollment_token": row.token,
        "expires_in_minutes": settings.enrollment_token_ttl_minutes,
        "run_on_the_vps": (
            f"molly worker enroll --token {row.token}"
            f"  # or add --gateway <url> if this worker's built-in default isn't {settings.public_http_url}"
        ),
    }


class EnrollBody(BaseModel):
    enrollment_token: str
    label: str = ""


@router.post("/admin/workers/enroll")
async def enroll_worker(body: EnrollBody, db: AsyncSession = Depends(get_db)):
    """Called by the worker itself (app/tunnel/enrollment.py), not by an
    admin - no tenant-admin auth here, the enrollment token *is* the
    credential for this one call."""
    row = await db.get(WorkerEnrollmentToken, body.enrollment_token)
    now = utcnow()
    if not row or row.used_at is not None or row.expires_at < now:
        raise HTTPException(status_code=400, detail="Invalid or expired enrollment token")

    row.used_at = now

    worker_token = secrets.token_urlsafe(32)
    worker_secret = secrets.token_urlsafe(32)
    worker = Worker(
        tenant_id=row.tenant_id,
        label=body.label or row.label_hint or "unnamed worker",
        token_hash=hash_secret(worker_token),
        secret=worker_secret,
    )
    db.add(worker)
    await db.commit()
    await db.refresh(worker)

    return {
        "worker_id": worker.id,
        "worker_token": worker_token,
        "worker_secret": worker_secret,
        "gateway_ws_url": settings.public_ws_url,
    }


@router.get("/admin/workers")
async def list_workers(tenant: Tenant = Depends(get_tenant_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Worker).where(Worker.tenant_id == tenant.id))
    workers = result.scalars().all()
    return [
        {
            "id": w.id,
            "label": w.label,
            "online": await registry.is_online(w.id),
            "revoked": w.revoked_at is not None,
            "created_at": w.created_at.isoformat(),
        }
        for w in workers
    ]


@router.delete("/admin/workers/{worker_id}")
async def revoke_worker(worker_id: str, tenant: Tenant = Depends(get_tenant_admin), db: AsyncSession = Depends(get_db)):
    worker = await db.get(Worker, worker_id)
    if not worker or worker.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Worker not found")

    worker.revoked_at = utcnow()
    await db.commit()

    conn = await registry.get(worker_id, tenant.id)
    if isinstance(conn, WorkerConnection):
        await conn.ws.close(code=4003)
        registry.unregister(worker_id)
    elif isinstance(conn, DistributedWorkerConnection):
        # Some other gateway process is holding this worker's socket -
        # ask it (via Redis) to close it, instead of reaching in and
        # touching a WebSocket that belongs to a different process.
        await conn.force_disconnect()

    return {"status": "revoked"}
