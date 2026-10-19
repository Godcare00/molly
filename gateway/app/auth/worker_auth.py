"""
Authenticates a worker calling the gateway *directly* over HTTP (not
through its tunnel) - today, only for `POST /worker/pairing-codes`
(app/api/pairing.py), issued from `molly connect` using the same
worker_id/worker_token pair the worker presents in its tunnel HELLO
frame. This never needs the tunnel to be up: a worker can request a
pairing code before it's ever opened one.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status

from app.db import get_db
from app.models import Worker
from app.security import secrets_match
from sqlalchemy.ext.asyncio import AsyncSession


async def get_authenticated_worker(
    x_worker_id: Annotated[Optional[str], Header()] = None,
    x_worker_token: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> Worker:
    if not x_worker_id or not x_worker_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-Worker-Id and X-Worker-Token headers required")

    worker = await db.get(Worker, x_worker_id)
    if not worker or worker.revoked_at is not None or not secrets_match(x_worker_token, worker.token_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker credentials")

    return worker
