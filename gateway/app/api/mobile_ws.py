"""
/w/{worker_id}/ws/conversations/{conversation_id} - what the mobile app
actually connects to in fleet mode. Deliberately mirrors the worker's own
/ws/conversations/{conversation_id} path (just with a /w/{worker_id}
prefix) so the message protocol the app already speaks - connected,
message, tool_started, approval_required, live_start, audio_chunk, ping/
pong, etc. - doesn't change at all; only the URL the app dials gains a
prefix. See molly-app/src/api/client.ts for the corresponding client-side
change.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.auth.tokens import TokenError, verify_access_token
from app.config import settings
from molly_tunnel_protocol import RelayClaims, mint_relay_token
from app.tunnel.registry import registry

logger = structlog.get_logger()
router = APIRouter()


@router.websocket("/w/{worker_id}/ws/conversations/{conversation_id}")
async def mobile_conversation_socket(
    websocket: WebSocket,
    worker_id: str,
    conversation_id: str,
    token: Optional[str] = Query(None),
):
    await websocket.accept()

    if not token:
        await websocket.close(code=4001, reason="Authentication required: token query parameter missing")
        return
    try:
        claims = verify_access_token(token)
    except TokenError as e:
        await websocket.close(code=4001, reason=f"Invalid token: {e}")
        return

    conn = await registry.get(worker_id, claims.tenant_id)
    if not conn:
        await websocket.close(code=4404, reason="Worker offline or not part of your account")
        return

    relay_token = mint_relay_token(conn.secret, RelayClaims(
        tenant_id=claims.tenant_id,
        worker_id=worker_id,
        user_id=claims.user_id,
        device_id=claims.device_id,
        role=claims.role,
    ), ttl_seconds=settings.relay_token_ttl_seconds)

    channel = await conn.open_ws_channel(conversation_id, relay_token)

    async def pump_to_mobile():
        try:
            while True:
                data = await channel.receive_from_worker()
                await websocket.send_json(data)
        except Exception:
            pass

    pump_task = asyncio.ensure_future(pump_to_mobile())
    try:
        while True:
            data = await websocket.receive_json()
            await channel.send_to_worker(data)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("mobile_socket_error", conversation_id=conversation_id)
    finally:
        pump_task.cancel()
        try:
            await channel.close()
        except Exception:
            pass
