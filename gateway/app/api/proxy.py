"""
/w/{worker_id}/{path:path} - reverse proxies any other REST call
(conversations, approvals, images, files, projects, settings...) straight
through to that worker over its tunnel, unchanged. The worker's existing
FastAPI routes don't know or care that a request arrived this way instead
of hitting uvicorn directly - see backend/app/tunnel/client.py's use of
httpx's ASGI transport.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Request, Response

from app.auth.tokens import TokenError, verify_access_token
from app.config import settings
from molly_tunnel_protocol import decode_body
from molly_tunnel_protocol import RelayClaims, mint_relay_token
from app.tunnel.registry import registry

logger = structlog.get_logger()
router = APIRouter()

_HOP_BY_HOP = {"host", "authorization", "content-length", "connection", "transfer-encoding"}


@router.api_route("/w/{worker_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_to_worker(
    worker_id: str,
    path: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    try:
        claims = verify_access_token(authorization.split(" ", 1)[1])
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))

    conn = await registry.get(worker_id, claims.tenant_id)
    if not conn:
        raise HTTPException(status_code=503, detail="Worker is offline or not part of your account")

    relay_token = mint_relay_token(conn.secret, RelayClaims(
        tenant_id=claims.tenant_id,
        worker_id=worker_id,
        user_id=claims.user_id,
        device_id=claims.device_id,
        role=claims.role,
    ), ttl_seconds=settings.relay_token_ttl_seconds)

    body = await request.body()
    try:
        frame = await conn.request_http(
            frame_id=str(uuid.uuid4()),
            method=request.method,
            path="/" + path,
            query=dict(request.query_params),
            headers={k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP},
            body=body,
            relay_token=relay_token,
        )
    except (ConnectionError, TimeoutError):
        raise HTTPException(status_code=504, detail="Worker did not respond in time")

    p = frame.payload
    response_headers = {
        k: v for k, v in (p.get("headers") or {}).items()
        if k.lower() not in {"content-length", "transfer-encoding", "content-encoding"}
    }
    return Response(
        content=decode_body(p.get("body_b64")),
        status_code=p.get("status", 502),
        headers=response_headers,
    )
