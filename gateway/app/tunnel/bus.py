"""
Redis-backed cross-process message bus for the worker tunnel registry.

gateway/app/tunnel/registry.py's WorkerConnection is in-memory and
per-process: it answers "is worker W online, and if so, which open
WebSocket is it on" only for whichever process currently holds that
worker's tunnel. Run more than one gateway process behind a load balancer
and a mobile request can land on a process that isn't holding the target
worker's actual socket.

This module makes that transparent: every frame destined for a worker is
published on a per-worker Redis channel that whichever process *is*
holding the tunnel subscribes to and relays onto the real WebSocket, and
every frame that arrives *from* the worker is published back the same
way, so any process waiting on a correlation id (an HTTP request id, or a
conversation_id for a WS channel) receives it regardless of which process
physically owns the socket. See registry.py's DistributedWorkerConnection
for the client side of this and worker_ws.py for the owning-process side.

Only active when REDIS_URL is set (app/config.py). Leave it unset and
nothing in this file is ever touched - the registry falls back to pure
in-memory, single-process behavior, exactly as before this existed.
"""
from __future__ import annotations

import json
from typing import Optional

import redis.asyncio as aioredis
import structlog

from app.config import settings
from molly_tunnel_protocol import TunnelFrame

logger = structlog.get_logger()

PRESENCE_TTL_SECONDS = 20       # a worker is considered offline if no heartbeat refreshes this in time
HEARTBEAT_INTERVAL_SECONDS = 7  # comfortably under the TTL so a couple of missed beats don't flap it offline


def _downlink_channel(worker_id: str) -> str:
    return f"molly:worker:{worker_id}:downlink"  # gateway (any process) -> worker


def _uplink_channel(worker_id: str) -> str:
    return f"molly:worker:{worker_id}:uplink"  # worker -> gateway (any process)


def _presence_key(worker_id: str) -> str:
    return f"molly:worker:{worker_id}:presence"


class Bus:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        await self._redis.ping()

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    @property
    def redis(self) -> aioredis.Redis:
        assert self._redis is not None, "Bus.connect() was never called"
        return self._redis

    # --- presence ---

    async def mark_online(self, worker_id: str, tenant_id: str, secret: str) -> None:
        await self.redis.set(
            _presence_key(worker_id),
            json.dumps({"tenant_id": tenant_id, "secret": secret}),
            ex=PRESENCE_TTL_SECONDS,
        )

    async def mark_offline(self, worker_id: str) -> None:
        await self.redis.delete(_presence_key(worker_id))

    async def get_presence(self, worker_id: str) -> Optional[dict]:
        raw = await self.redis.get(_presence_key(worker_id))
        return json.loads(raw) if raw else None

    # --- frame relay ---

    async def publish_downlink(self, worker_id: str, frame: TunnelFrame) -> None:
        await self.redis.publish(_downlink_channel(worker_id), frame.to_wire())

    async def publish_uplink(self, worker_id: str, frame: TunnelFrame) -> None:
        await self.redis.publish(_uplink_channel(worker_id), frame.to_wire())

    def subscribe_downlink(self, worker_id: str):
        pubsub = self.redis.pubsub()
        return pubsub, _downlink_channel(worker_id)

    def subscribe_uplink(self, worker_id: str):
        pubsub = self.redis.pubsub()
        return pubsub, _uplink_channel(worker_id)


_bus: Optional[Bus] = None


def get_bus() -> Optional[Bus]:
    """None if REDIS_URL isn't configured - callers treat that as
    "single-process mode, in-memory registry only"."""
    return _bus


async def init_bus() -> None:
    global _bus
    if settings.redis_url:
        bus = Bus(settings.redis_url)
        await bus.connect()
        _bus = bus
        logger.info("bus_connected", redis_url=settings.redis_url)


async def close_bus() -> None:
    global _bus
    if _bus:
        await _bus.close()
        _bus = None
