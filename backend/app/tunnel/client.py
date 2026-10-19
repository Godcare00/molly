"""
The worker side of the fleet tunnel: one persistent outbound WebSocket to
the gateway, authenticated once at connect time, multiplexing:

  - HTTP_REQUEST/HTTP_RESPONSE frames, answered by calling this worker's
    own FastAPI app *in-process* via httpx's ASGI transport. No extra
    port, no extra process, no changes to a single REST route - the
    entire existing app/api/*.py surface is reused verbatim.

  - WS_OPEN/WS_DATA/WS_CLOSE frames, one channel per mobile conversation
    socket, answered by running the exact same
    app.api.websocket.handle_conversation_socket coroutine the local
    /ws/conversations/{id} route uses. Approvals, live-voice mode, and
    everything else that flows over that socket works identically in
    both deployment modes.

Reconnects with jittered exponential backoff. Losing the gateway doesn't
affect anyone still reaching this worker directly (SSH, `molly run`,
local self-hosted mode, or Tailscale) - the tunnel is purely additive.
"""
from __future__ import annotations

import asyncio
import random
from typing import Dict, Optional

import httpx
import structlog
import websockets
from websockets.exceptions import ConnectionClosed

from app.api.websocket import handle_conversation_socket
from app.tunnel.channel import TunnelChannel
from molly_tunnel_protocol import PROTOCOL_VERSION, FrameType, TunnelFrame, decode_body, encode_body
from molly_tunnel_protocol import RelayAuthUser, RelayTokenError, verify_relay_token

logger = structlog.get_logger()


class TunnelClient:
    def __init__(
        self,
        gateway_ws_url: str,
        worker_id: str,
        worker_token: str,
        worker_secret: str,
        asgi_app,
    ):
        self.gateway_ws_url = gateway_ws_url
        self.worker_id = worker_id
        self.worker_token = worker_token   # long-lived credential, proves worker identity to the gateway
        self.worker_secret = worker_secret  # shared secret used to verify the gateway's relay tokens
        self._http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=asgi_app),
            base_url="http://worker.internal",
            timeout=120.0,
        )
        self._channels: Dict[str, TunnelChannel] = {}
        self._ws = None
        self._send_lock = asyncio.Lock()
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    async def run_forever(self) -> None:
        backoff = 1.0
        while not self._stop:
            try:
                await self._connect_once()
                backoff = 1.0  # a session that got this far and then dropped isn't a config problem
            except (ConnectionClosed, OSError) as e:
                logger.warning("tunnel_disconnected", error=str(e))
            except Exception:
                logger.exception("tunnel_error")
            if self._stop:
                break
            sleep_for = backoff + random.uniform(0, backoff * 0.25)
            logger.info("tunnel_reconnecting", in_seconds=round(sleep_for, 1))
            await asyncio.sleep(sleep_for)
            backoff = min(backoff * 2, 60.0)

    async def _connect_once(self) -> None:
        async with websockets.connect(self.gateway_ws_url, max_size=16 * 1024 * 1024) as ws:
            self._ws = ws
            await self._send(TunnelFrame(
                type=FrameType.HELLO,
                payload={
                    "worker_id": self.worker_id,
                    "token": self.worker_token,
                    "protocol_version": PROTOCOL_VERSION,
                },
            ))

            ack = TunnelFrame.from_wire(await ws.recv())
            if ack.type != FrameType.HELLO_ACK:
                logger.error("tunnel_hello_rejected", reason=ack.payload.get("reason", "unknown"))
                # Don't hot-loop against a gateway that's actively rejecting us
                # (revoked credentials, version mismatch) - back off harder.
                await asyncio.sleep(30)
                return

            logger.info("tunnel_connected", worker_id=self.worker_id, gateway=self.gateway_ws_url)

            async for raw in ws:
                frame = TunnelFrame.from_wire(raw)
                asyncio.ensure_future(self._handle_frame(frame))

    async def _send(self, frame: TunnelFrame) -> None:
        if self._ws is None:
            return
        async with self._send_lock:
            await self._ws.send(frame.to_wire())

    async def _send_channel_frame(self, frame_type: str, channel_id: str, payload: dict) -> None:
        await self._send(TunnelFrame(type=FrameType(frame_type), id=channel_id, payload=payload))

    async def _handle_frame(self, frame: TunnelFrame) -> None:
        if frame.type == FrameType.PING:
            await self._send(TunnelFrame(type=FrameType.PONG, id=frame.id))
        elif frame.type == FrameType.HTTP_REQUEST:
            await self._handle_http_request(frame)
        elif frame.type == FrameType.WS_OPEN:
            await self._handle_ws_open(frame)
        elif frame.type == FrameType.WS_DATA:
            channel = self._channels.get(frame.id)
            if channel:
                channel.deliver(frame.payload.get("data", {}))
        elif frame.type == FrameType.WS_CLOSE:
            channel = self._channels.pop(frame.id, None)
            if channel:
                channel.mark_closed()

    def _auth_user_from_relay_token(self, relay_token: str) -> RelayAuthUser:
        claims = verify_relay_token(self.worker_secret, relay_token, expected_worker_id=self.worker_id)
        return RelayAuthUser(claims)

    async def _handle_http_request(self, frame: TunnelFrame) -> None:
        p = frame.payload
        try:
            headers = dict(p.get("headers") or {})
            headers.pop("authorization", None)  # the gateway already authenticated this request

            relay_token = p.get("relay_token")
            if relay_token:
                # Pass the *signed* token through, not the claims it
                # contains - app.auth.dependencies.get_current_user
                # re-verifies the signature against worker_secret before
                # trusting anything in it (see the relay branch there).
                # A bare "x-relay-user: alice" header would be forgeable
                # by anyone who can reach this worker's real port
                # directly; a signature only this worker and the gateway
                # can produce is not.
                headers["x-molly-relay-token"] = relay_token

            resp = await self._http.request(
                p.get("method", "GET"),
                p.get("path", "/"),
                params=p.get("query") or None,
                headers=headers,
                content=decode_body(p.get("body_b64")),
            )
            await self._send(TunnelFrame(
                type=FrameType.HTTP_RESPONSE,
                id=frame.id,
                payload={
                    "status": resp.status_code,
                    "headers": dict(resp.headers),
                    "body_b64": encode_body(resp.content),
                },
            ))
        except Exception as e:
            logger.exception("tunnel_http_proxy_error")
            await self._send(TunnelFrame(type=FrameType.ERROR, id=frame.id, payload={"message": str(e)}))

    async def _handle_ws_open(self, frame: TunnelFrame) -> None:
        conversation_id = frame.id
        relay_token = frame.payload.get("relay_token", "")
        try:
            auth_user = self._auth_user_from_relay_token(relay_token)
        except RelayTokenError as e:
            await self._send(TunnelFrame(type=FrameType.WS_CLOSE, id=conversation_id, payload={"reason": str(e)}))
            return

        channel = TunnelChannel(conversation_id, self._send_channel_frame)
        self._channels[conversation_id] = channel

        async def _run():
            try:
                await handle_conversation_socket(channel, conversation_id, auth_user)
            except Exception:
                logger.exception("tunnel_channel_error", conversation_id=conversation_id)
            finally:
                self._channels.pop(conversation_id, None)
                await self._send(TunnelFrame(type=FrameType.WS_CLOSE, id=conversation_id, payload={}))

        asyncio.ensure_future(_run())
