"""
/worker/connect - the one endpoint every worker in the fleet dials into
and holds open. Everything else the worker does (serving REST, serving
conversation WebSockets) rides on top of this single connection as
frames; see app/tunnel/registry.py.

When app.tunnel.bus is configured (REDIS_URL set), the process handling
this connection also becomes that worker's bridge to every other gateway
process: it marks presence in Redis (heartbeat-refreshed so a crashed
process's workers don't stay marked online), relays every frame it reads
from the worker onto the shared uplink channel, and relays every frame
published to the worker's downlink channel (by *any* process, including
requests other processes' users initiated) onto the real WebSocket. See
registry.py's DistributedWorkerConnection for the other side of this.
"""
from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Worker
from app.security import secrets_match
from app.tunnel.bus import HEARTBEAT_INTERVAL_SECONDS, get_bus
from app.tunnel.registry import WorkerConnection, registry
from molly_tunnel_protocol import FrameType, TunnelFrame

logger = structlog.get_logger()
router = APIRouter()


async def _authenticate_worker(worker_id: str, token: str) -> Worker | None:
    async with SessionLocal() as db:
        worker = await db.get(Worker, worker_id)
        if not worker or worker.revoked_at is not None:
            return None
        if not secrets_match(token, worker.token_hash):
            return None
        return worker


async def _heartbeat_loop(worker: Worker, bus) -> None:
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            await bus.mark_online(worker.id, worker.tenant_id, worker.secret)
    except asyncio.CancelledError:
        pass


async def _downlink_bridge(worker: Worker, conn: WorkerConnection, bus) -> None:
    """Relays frames published to this worker's downlink channel - by any
    gateway process, including requests that originated on a process
    other than this one - onto the real WebSocket this process is
    holding."""
    pubsub, channel_name = bus.subscribe_downlink(worker.id)
    await pubsub.subscribe(channel_name)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            frame = TunnelFrame.from_wire(message["data"])
            if frame.type == FrameType.FORCE_DISCONNECT:
                logger.info("worker_force_disconnected", worker_id=worker.id)
                await conn.ws.close(code=4003)
                return
            await conn.send(frame)
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(channel_name)
        await pubsub.aclose()


@router.websocket("/worker/connect")
async def worker_tunnel_endpoint(websocket: WebSocket):
    await websocket.accept()

    try:
        hello = TunnelFrame.from_wire(await websocket.receive_text())
    except Exception:
        await websocket.close(code=4000)
        return

    if hello.type != FrameType.HELLO:
        await websocket.close(code=4000)
        return

    worker_id = hello.payload.get("worker_id", "")
    token = hello.payload.get("token", "")
    worker = await _authenticate_worker(worker_id, token)
    if not worker:
        await websocket.send_text(TunnelFrame(type=FrameType.HELLO_REJECT, payload={"reason": "invalid credentials"}).to_wire())
        await websocket.close(code=4001)
        return

    conn = WorkerConnection(worker.id, worker.tenant_id, worker.secret, websocket)
    registry.register(conn)
    await websocket.send_text(TunnelFrame(type=FrameType.HELLO_ACK, payload={"worker_id": worker.id}).to_wire())
    logger.info("worker_connected", worker_id=worker.id, tenant_id=worker.tenant_id)

    bus = get_bus()
    background_tasks: list[asyncio.Task] = []
    if bus:
        await bus.mark_online(worker.id, worker.tenant_id, worker.secret)
        background_tasks.append(asyncio.ensure_future(_heartbeat_loop(worker, bus)))
        background_tasks.append(asyncio.ensure_future(_downlink_bridge(worker, conn, bus)))

    try:
        while True:
            frame = TunnelFrame.from_wire(await websocket.receive_text())

            if frame.type == FrameType.HTTP_RESPONSE:
                conn.resolve_http(frame)
            elif frame.type == FrameType.WS_DATA:
                conn.deliver_ws_data(frame)
            elif frame.type == FrameType.WS_CLOSE:
                conn.close_ws_channel(frame)
            elif frame.type == FrameType.ERROR:
                conn.resolve_http(frame)  # let a hung REST caller fail instead of timing out
            elif frame.type == FrameType.PONG:
                pass

            # Mirror every frame from the worker onto Redis too, so any
            # *other* gateway process that's waiting on this correlation
            # id (because a user's request landed there, not here) gets
            # it. Harmless no-op if nobody else is subscribed.
            if bus and frame.type in (FrameType.HTTP_RESPONSE, FrameType.WS_DATA, FrameType.WS_CLOSE, FrameType.ERROR):
                await bus.publish_uplink(worker.id, frame)
    except WebSocketDisconnect:
        pass
    finally:
        for task in background_tasks:
            task.cancel()
        conn.fail_all_pending()
        registry.unregister(worker.id)
        if bus:
            await bus.mark_offline(worker.id)
        logger.info("worker_disconnected", worker_id=worker.id)
