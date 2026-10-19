"""
Adapts one multiplexed conversation channel on the tunnel to look like a
fastapi.WebSocket (accept/send_json/receive_json/close), so
app.api.websocket.handle_conversation_socket runs completely unmodified
whether the mobile app connected to this worker directly or through a
fleet gateway.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict

from fastapi import WebSocketDisconnect

_CLOSED = object()

# (frame_type: str, channel_id: str, payload: dict) -> awaitable
SendFrameFn = Callable[[str, str, Dict[str, Any]], Awaitable[None]]


class TunnelChannel:
    def __init__(self, channel_id: str, send_frame: SendFrameFn):
        self.channel_id = channel_id
        self._send_frame = send_frame
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._closed = False

    # --- the subset of fastapi.WebSocket's interface handle_conversation_socket needs ---

    async def accept(self) -> None:
        return  # the gateway already accepted the mobile-facing socket; nothing to do on this end

    async def send_json(self, data: Dict[str, Any]) -> None:
        if self._closed:
            return
        await self._send_frame("ws_data", self.channel_id, {"data": data})

    async def receive_json(self) -> Dict[str, Any]:
        item = await self._inbox.get()
        if item is _CLOSED:
            raise WebSocketDisconnect()
        return item

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self._closed:
            return
        self._closed = True
        await self._send_frame("ws_close", self.channel_id, {"reason": reason})

    # --- called by TunnelClient's read loop only ---

    def deliver(self, data: Dict[str, Any]) -> None:
        self._inbox.put_nowait(data)

    def mark_closed(self) -> None:
        self._closed = True
        self._inbox.put_nowait(_CLOSED)
