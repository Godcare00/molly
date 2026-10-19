"""
Relay tokens are short-lived signed assertions the gateway attaches to
every HTTP request it proxies and every conversation channel it opens, so
a worker can trust "the gateway says this is tenant T, user U, device D"
without a second network round trip back to the gateway on every single
message.

Signed HS256 with a worker's own `secret` - established once, at
enrollment, and known only to that worker and the gateway (gateway:
gateway/app/api/admin_workers.py; worker: backend/app/tunnel/enrollment.py).
Deliberately short-lived: a full round trip already happens on every HTTP
request / WS channel open, so this is a signature check, not a session -
a leaked relay token is worthless within its TTL.

mint_relay_token is used by the gateway; verify_relay_token and
RelayAuthUser are used by the worker. Both live here, in the one package
both services depend on, rather than split across two repos where they'd
be easy to let drift.
"""
from __future__ import annotations

import time
from typing import Optional

import jwt as pyjwt
from pydantic import BaseModel

DEFAULT_TTL_SECONDS = 60


class RelayClaims(BaseModel):
    tenant_id: str
    worker_id: str
    user_id: Optional[str] = None
    device_id: Optional[str] = None
    role: str = "member"


class RelayTokenError(Exception):
    pass


def mint_relay_token(worker_secret: str, claims: RelayClaims, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    now = int(time.time())
    payload = claims.model_dump()
    payload.update({"iat": now, "exp": now + ttl_seconds, "iss": "molly-gateway"})
    return pyjwt.encode(payload, worker_secret, algorithm="HS256")


def verify_relay_token(worker_secret: str, token: str, expected_worker_id: str) -> RelayClaims:
    try:
        payload = pyjwt.decode(token, worker_secret, algorithms=["HS256"], issuer="molly-gateway")
    except pyjwt.PyJWTError as e:
        raise RelayTokenError(f"invalid relay token: {e}") from e

    if payload.get("worker_id") != expected_worker_id:
        # Either a bug on the gateway side, or (more worryingly) a relay
        # token minted for a different worker replayed against this one -
        # both are reasons to refuse, not just log.
        raise RelayTokenError("relay token was not minted for this worker")

    return RelayClaims(**{k: v for k, v in payload.items() if k in RelayClaims.model_fields})


class RelayAuthUser:
    """Duck-types app.auth.dependencies.AuthUser closely enough for
    handle_conversation_socket (and anything downstream that only reads
    .user_id / .device_id / .role / .has_role()) to work unmodified,
    backed by a verified RelayClaims instead of a local User/Device/Session
    DB lookup."""

    def __init__(self, claims: RelayClaims):
        self._claims = claims

    @property
    def user_id(self) -> str:
        return self._claims.user_id or ""

    @property
    def device_id(self) -> str:
        return self._claims.device_id or ""

    @property
    def role(self) -> str:
        return self._claims.role

    def has_role(self, *roles: str) -> bool:
        return self.role in roles
