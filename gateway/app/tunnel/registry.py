"""
In-process registry of live worker tunnel connections, extended to be
cluster-aware when app.tunnel.bus is configured (REDIS_URL set).

Two connection types share the same public interface
(request_http / open_ws_channel / .secret / .tenant_id), so callers in
api/proxy.py and api/mobile_ws.py never need to know or care which one
they got back from `await registry.get(...)`:

  - WorkerConnection: this process is physically holding the worker's
    tunnel WebSocket (set up in api/worker_ws.py). Fastest path - talks
    to the worker directly, no Redis round trip, used whether or not a
    bus is configured.
  - DistributedWorkerConnection: some *other* gateway process is holding
    the tunnel. Only reachable when app.tunnel.bus.get_bus() returns a
    connected Bus - every call goes out over Redis pub/sub and waits for
    the owning process's worker_ws.py to relay the worker's reply back.
    Without a bus configured, a worker connected to another process is
    simply invisible to this one (single-process mode, same as before
    this existed).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Union

from molly_tunnel_protocol import FrameType, TunnelFrame, decode_body, encode_body

_CLOSED = object()


class GatewayChannel:
    """The gateway-side mirror of the worker's TunnelChannel: pumps
    messages between one mobile-facing fastapi.WebSocket and this
    worker's shared tunnel connection, when this process physically
    holds that tunnel."""

    def __init__(self, conversation_id: str, conn: "WorkerConnection"):
        self.conversation_id = conversation_id
        self.conn = conn
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._closed = False

    async def send_to_worker(self, data: Dict[str, Any]) -> None:
        await self.conn.send(TunnelFrame(type=FrameType.WS_DATA, id=self.conversation_id, payload={"data": data}))

    def deliver(self, data: Dict[str, Any]) -> None:
        self._inbox.put_nowait(data)

    def mark_closed(self) -> None:
        self._closed = True
        self._inbox.put_nowait(_CLOSED)

    async def receive_from_worker(self) -> Dict[str, Any]:
        item = await self._inbox.get()
        if item is _CLOSED:
            raise RuntimeError("worker closed the conversation channel")
        return item

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.conn.send(TunnelFrame(type=FrameType.WS_CLOSE, id=self.conversation_id, payload={}))


class WorkerConnection:
    """This process is physically holding worker_id's tunnel WebSocket."""

    def __init__(self, worker_id: str, tenant_id: str, secret: str, ws):
        self.worker_id = worker_id
        self.tenant_id = tenant_id
        self.secret = secret
        self.ws = ws
        self.pending_http: Dict[str, asyncio.Future] = {}
        self.ws_channels: Dict[str, GatewayChannel] = {}
        self._send_lock = asyncio.Lock()

    async def send(self, frame: TunnelFrame) -> None:
        async with self._send_lock:
            await self.ws.send_text(frame.to_wire())

    async def request_http(
        self,
        frame_id: str,
        method: str,
        path: str,
        query: Dict[str, str],
        headers: Dict[str, str],
        body: bytes,
        relay_token: str,
        timeout: float = 30.0,
    ) -> TunnelFrame:
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self.pending_http[frame_id] = fut
        try:
            await self.send(TunnelFrame(
                type=FrameType.HTTP_REQUEST,
                id=frame_id,
                payload={
                    "method": method,
                    "path": path,
                    "query": query,
                    "headers": headers,
                    "body_b64": encode_body(body),
                    "relay_token": relay_token,
                },
            ))
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self.pending_http.pop(frame_id, None)

    def resolve_http(self, frame: TunnelFrame) -> None:
        fut = self.pending_http.get(frame.id)
        if fut and not fut.done():
            fut.set_result(frame)

    async def open_ws_channel(self, conversation_id: str, relay_token: str) -> GatewayChannel:
        channel = GatewayChannel(conversation_id, self)
        self.ws_channels[conversation_id] = channel
        await self.send(TunnelFrame(type=FrameType.WS_OPEN, id=conversation_id, payload={"relay_token": relay_token}))
        return channel

    def deliver_ws_data(self, frame: TunnelFrame) -> None:
        channel = self.ws_channels.get(frame.id)
        if channel:
            channel.deliver(frame.payload.get("data", {}))

    def close_ws_channel(self, frame: TunnelFrame) -> None:
        channel = self.ws_channels.pop(frame.id, None)
        if channel:
            channel.mark_closed()

    def fail_all_pending(self) -> None:
        """Called when the tunnel drops - an in-flight REST call shouldn't
        hang forever waiting for a response that will never come."""
        for fut in self.pending_http.values():
            if not fut.done():
                fut.set_exception(ConnectionError("worker tunnel disconnected"))
        for channel in self.ws_channels.values():
            channel.mark_closed()


class DistributedGatewayChannel:
    """Same role as GatewayChannel, but for a worker this process isn't
    physically connected to - everything goes over app.tunnel.bus."""

    def __init__(self, conversation_id: str, conn: "DistributedWorkerConnection", pubsub, channel_name: str):
        self.conversation_id = conversation_id
        self.conn = conn
        self._pubsub = pubsub
        self._channel_name = channel_name
        self._closed = False

    async def send_to_worker(self, data: Dict[str, Any]) -> None:
        await self.conn.send_ws_data(self.conversation_id, data)

    async def receive_from_worker(self) -> Dict[str, Any]:
        async for message in self._pubsub.listen():
            if message.get("type") != "message":
                continue
            frame = TunnelFrame.from_wire(message["data"])
            if frame.id != self.conversation_id:
                continue
            if frame.type == FrameType.WS_CLOSE:
                raise RuntimeError("worker closed the conversation channel")
            if frame.type == FrameType.WS_DATA:
                return frame.payload.get("data", {})

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.conn.close_ws_channel(self.conversation_id)
        await self._pubsub.unsubscribe(self._channel_name)
        await self._pubsub.aclose()


class DistributedWorkerConnection:
    """Talks to worker_id's tunnel through app.tunnel.bus, without this
    process holding the actual WebSocket - some other gateway process
    does, and its worker_ws.py relays frames to/from Redis on our
    behalf. Deliberately mirrors WorkerConnection's public interface so
    callers can treat the two interchangeably."""

    def __init__(self, worker_id: str, tenant_id: str, secret: str, bus):
        self.worker_id = worker_id
        self.tenant_id = tenant_id
        self.secret = secret
        self._bus = bus

    async def request_http(
        self,
        frame_id: str,
        method: str,
        path: str,
        query: Dict[str, str],
        headers: Dict[str, str],
        body: bytes,
        relay_token: str,
        timeout: float = 30.0,
    ) -> TunnelFrame:
        pubsub, channel_name = self._bus.subscribe_uplink(self.worker_id)
        await pubsub.subscribe(channel_name)
        try:
            await self._bus.publish_downlink(self.worker_id, TunnelFrame(
                type=FrameType.HTTP_REQUEST,
                id=frame_id,
                payload={
                    "method": method,
                    "path": path,
                    "query": query,
                    "headers": headers,
                    "body_b64": encode_body(body),
                    "relay_token": relay_token,
                },
            ))
            return await asyncio.wait_for(self._wait_for(pubsub, frame_id), timeout=timeout)
        finally:
            await pubsub.unsubscribe(channel_name)
            await pubsub.aclose()

    async def _wait_for(self, pubsub, frame_id: str) -> TunnelFrame:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            frame = TunnelFrame.from_wire(message["data"])
            if frame.id == frame_id:
                return frame

    async def open_ws_channel(self, conversation_id: str, relay_token: str) -> DistributedGatewayChannel:
        pubsub, channel_name = self._bus.subscribe_uplink(self.worker_id)
        await pubsub.subscribe(channel_name)
        await self._bus.publish_downlink(self.worker_id, TunnelFrame(
            type=FrameType.WS_OPEN, id=conversation_id, payload={"relay_token": relay_token},
        ))
        return DistributedGatewayChannel(conversation_id, self, pubsub, channel_name)

    async def send_ws_data(self, conversation_id: str, data: Dict[str, Any]) -> None:
        await self._bus.publish_downlink(self.worker_id, TunnelFrame(type=FrameType.WS_DATA, id=conversation_id, payload={"data": data}))

    async def close_ws_channel(self, conversation_id: str) -> None:
        await self._bus.publish_downlink(self.worker_id, TunnelFrame(type=FrameType.WS_CLOSE, id=conversation_id, payload={}))

    async def force_disconnect(self) -> None:
        await self._bus.publish_downlink(self.worker_id, TunnelFrame(type=FrameType.FORCE_DISCONNECT))


AnyWorkerConnection = Union[WorkerConnection, DistributedWorkerConnection]


class WorkerRegistry:
    def __init__(self):
        self._by_id: Dict[str, WorkerConnection] = {}

    def register(self, conn: WorkerConnection) -> None:
        existing = self._by_id.get(conn.worker_id)
        if existing:
            existing.fail_all_pending()  # a stale connection for the same worker_id is being replaced
        self._by_id[conn.worker_id] = conn

    def unregister(self, worker_id: str) -> None:
        self._by_id.pop(worker_id, None)

    def get_local(self, worker_id: str) -> Optional[WorkerConnection]:
        return self._by_id.get(worker_id)

    async def get(self, worker_id: str, tenant_id: str) -> Optional[AnyWorkerConnection]:
        conn = self._by_id.get(worker_id)
        if conn:
            return conn if conn.tenant_id == tenant_id else None

        from app.tunnel.bus import get_bus
        bus = get_bus()
        if not bus:
            return None  # single-process mode: not local means genuinely not reachable from here

        presence = await bus.get_presence(worker_id)
        if not presence or presence["tenant_id"] != tenant_id:
            return None
        return DistributedWorkerConnection(worker_id, tenant_id, presence["secret"], bus)

    async def is_online(self, worker_id: str) -> bool:
        if worker_id in self._by_id:
            return True
        from app.tunnel.bus import get_bus
        bus = get_bus()
        if not bus:
            return False
        return await bus.get_presence(worker_id) is not None


registry = WorkerRegistry()
