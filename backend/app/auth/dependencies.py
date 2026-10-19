"""
FastAPI authentication dependency.

This worker no longer authenticates anyone directly - it always runs
behind a fleet gateway now (see `python -m app.cli worker enroll` /
ARCHITECTURE.md). Every REST and WebSocket request this worker answers
was already authenticated once by the gateway (real email/password
accounts + code-based device pairing - see gateway/app/api/account.py
and pairing.py) and arrives here carrying a short-lived relay token,
signed with this worker's own `worker_secret` (established once at
enrollment, known only to this worker and the gateway). Verifying that
signature - not just trusting the header - is what makes this safe: a
request can't claim to be relayed from the gateway without a secret only
the gateway has.

See molly_tunnel_protocol.relay_token for RelayClaims/RelayAuthUser and
app/tunnel/client.py for where the header this reads is attached.
"""
from typing import Optional, Annotated
from fastapi import status, Header, HTTPException

from molly_tunnel_protocol import RelayAuthUser, RelayTokenError, verify_relay_token


def _fleet_credential() -> Optional[dict]:
    """This worker's saved {worker_id, worker_token, worker_secret}, set
    by `molly worker enroll`. None means this worker was never enrolled
    with a gateway, in which case there is no key to verify a relay token
    against - every request is refused rather than silently trusted."""
    from app.tunnel.enrollment import load_credential
    return load_credential()


async def get_current_user(
    x_molly_relay_token: Annotated[Optional[str], Header()] = None,
) -> RelayAuthUser:
    if not x_molly_relay_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing relay token - this worker only accepts requests proxied through its gateway",
        )

    cred = _fleet_credential()
    if not cred:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This worker is not enrolled with a gateway")

    try:
        claims = verify_relay_token(cred["worker_secret"], x_molly_relay_token, expected_worker_id=cred["worker_id"])
    except RelayTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    return RelayAuthUser(claims)
