"""
Wire protocol for the worker<->gateway tunnel.

The worker opens exactly one outbound WebSocket connection to the gateway
and keeps it open (backend/app/tunnel/client.py). Everything else -
proxied REST calls, and the per-conversation WebSocket the mobile app
talks to - is multiplexed over that single connection as small JSON
frames.

This used to be physically duplicated between backend/app/tunnel/ and
gateway/app/tunnel/; it's now this one installable package that both
depend on (see each service's requirements.txt), so the two can no
longer drift out of sync with each other.
"""
from __future__ import annotations

import base64
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

PROTOCOL_VERSION = 1


class FrameType(str, Enum):
    # Connection lifecycle
    HELLO = "hello"                # worker -> gateway, first frame on a new tunnel connection
    HELLO_ACK = "hello_ack"        # gateway -> worker, credentials accepted
    HELLO_REJECT = "hello_reject"  # gateway -> worker, credentials rejected (worker should NOT fast-retry)
    PING = "ping"
    PONG = "pong"
    FORCE_DISCONNECT = "force_disconnect"  # gateway -> worker: an admin revoked this worker, drop the tunnel now

    # Generic reverse-proxied HTTP request/response (gateway -> worker -> gateway)
    HTTP_REQUEST = "http_request"
    HTTP_RESPONSE = "http_response"

    # Multiplexed conversation WebSocket channels, one per mobile session
    WS_OPEN = "ws_open"     # gateway -> worker: mobile app opened /w/{worker_id}/ws/conversations/{id}
    WS_DATA = "ws_data"     # either direction: one JSON message in that conversation's socket protocol
    WS_CLOSE = "ws_close"   # either direction: that conversation socket is done

    ERROR = "error"


class TunnelFrame(BaseModel):
    """One message on the tunnel.

    `id` correlates request/response pairs for HTTP_* frames, and
    identifies the channel for WS_* frames (== the conversation_id the
    mobile app is talking to). Frame-type-specific fields live in
    `payload` rather than as top-level fields so this model doesn't need
    to grow a field for every frame type.
    """
    type: FrameType
    id: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)

    def to_wire(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_wire(cls, raw: str) -> "TunnelFrame":
        return cls.model_validate_json(raw)


def encode_body(body: Optional[bytes]) -> Optional[str]:
    if not body:
        return None
    return base64.b64encode(body).decode("ascii")


def decode_body(body_b64: Optional[str]) -> bytes:
    if not body_b64:
        return b""
    return base64.b64decode(body_b64)
