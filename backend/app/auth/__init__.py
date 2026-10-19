"""
Authentication module.

Self-hosted, direct-to-device authentication (local email/password-less
Ed25519 device pairing, browser /connect approval, local JWT issuing) has
been removed - this worker now always authenticates via the gateway's
relay token (see dependencies.py). Real accounts, device pairing, and
sessions all live on the gateway now (see gateway/app/api/account.py and
pairing.py).
"""
from app.auth.dependencies import get_current_user

__all__ = [
    "get_current_user",
]
