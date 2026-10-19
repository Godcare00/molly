# Molly: fleet architecture (gateway + worker split)

This is the connections/auth/routing vs. server-worker split discussed earlier,
built and tested end to end. Short version of what changed:

- **`backend/`** is the same app as before, plus a new `app/tunnel/`
  package. It now *requires* fleet enrollment (`molly worker enroll`) -
  the self-hosted, Tailscale-direct mode (local Ed25519 device pairing,
  browser `/connect` approval, local JWTs) has been removed. Every
  request this worker answers - REST or WebSocket - arrives carrying a
  relay token the gateway already authenticated and signs with this
  worker's own `worker_secret`; see `app/auth/dependencies.py`.
- **`gateway/`** is a new, separate service: multi-tenant accounts (real
  email/password signup/login - see `app/api/account.py` - alongside a
  per-tenant API key for scripts/CI), worker registry, device pairing,
  and a reverse tunnel that proxies both REST and the conversation
  WebSocket through to whichever worker owns a given tenant's traffic.
- **`molly-app/`** talks to the gateway exclusively now: `AuthContext`/
  `PairingScreen` do real signup/login (`/auth/signup`, `/auth/login`)
  followed by code-based device pairing (`POST /devices/pair`), and
  prefix fleet-mode requests with `/w/{worker_id}` for everything else.
  That's implemented in `src/api/client.ts` (+ `files.ts`, `images.ts`,
  `context/WebSocketContext.tsx`) via `setActiveWorkerId()`, plus a
  `gatewayNative` option for the handful of calls (`/auth/me`,
  `/auth/logout`, signup/login/pair) that must never get that prefix.

## Pairing a device (no admin, no browser)

`POST /auth/signup` also mints this tenant's first worker-enrollment
token as part of the response (see `mint_enrollment_token()` in
`gateway/app/api/admin_workers.py`) - so a brand-new user's flow is
sign up → run the `molly worker enroll --token ...` command the app
shows them → `molly connect` on that same server → pair:

```
phone: user signs up (POST /auth/signup) -> gets a session_token AND
       a one-time enrollment_token for their first server
vps:   molly worker enroll --token <enrollment_token>   (one-time)
       molly connect
       -> POST /worker/pairing-codes   (authenticated as the worker itself)
       -> prints an 8-character code in the terminal
phone: user types that code into the app
       -> POST /devices/pair {code, name, platform}, with the session
          token from signup attached
       -> gets back a real access/refresh token pair immediately
```

Additional workers (a second server, or pairing without ever having signed
up) still go through the explicit `POST /admin/workers/tokens` /
`POST /auth/login` paths described below - signup's automatic token is
just a shortcut for the very first one.

One code, no intermediate admin approval or browser page. Whoever can
read the code printed on the server's own terminal is trusted to pair a
device - the already-enrolled worker requested that code on the
operator's behalf. See `gateway/app/api/pairing.py`'s module docstring
for the full reasoning, including the naive per-IP rate limit on
`/devices/pair` (a real deployment should put a proper rate limiter, e.g.
at a reverse proxy, in front of it - the 33^8 code space and short TTL
make brute-forcing impractical but not costly to slow down further).

`molly connect` now requires the worker to be enrolled with a gateway
(`molly worker enroll`) - there is no local-secret/browser fallback left.

## Why this shape

A shared gateway can't dial into an arbitrary customer's server - most sit
behind NAT with no inbound access. So the worker has to be the one that
opens the connection: one persistent outbound WebSocket to the gateway,
authenticated once, multiplexing everything else (REST calls, the
conversation socket) as small JSON frames. See
`backend/app/tunnel/protocol.py` for the frame format and
`backend/app/tunnel/client.py` for the client that speaks it.

The worker's actual application code didn't need to change to support
this - `client.py` answers `HTTP_REQUEST` frames by calling the worker's
own FastAPI app in-process via `httpx`'s ASGI transport (no extra port,
every existing route works untouched), and answers `WS_OPEN` frames by
running the exact same `handle_conversation_socket()` coroutine the local
`/ws/conversations/{id}` route already used - that function was extracted
from `app/api/websocket.py` specifically so both transports could share
it. This is the same shape as ngrok / Cloudflare Tunnel, just carrying
both HTTP and one specialized WebSocket instead of only HTTP.

## What's been verified (not just written)

Everything below was actually run, against the real gateway and the real,
otherwise-unmodified backend (not mocks):

- Tenant bootstrap, worker enrollment token issuance, and enrollment
  (`POST /admin/workers/enroll`) - real DB round trip.
- The **real** `backend/app/tunnel/client.py`, running inside the real
  `molly serve` process, connecting out to the gateway and completing the
  HELLO/HELLO_ACK handshake - the gateway's worker list showed it
  `"online": true`.
- A **real** conversation created through `POST /w/{worker_id}/conversations`
  on the gateway, proxied over the tunnel, landing in the worker's actual
  SQLite storage and coming back correctly on `GET /w/{worker_id}/conversations`.
- A **real** WebSocket opened at `/w/{worker_id}/ws/conversations/{id}` on
  the gateway, relayed through the tunnel, handled by the actual
  `handle_conversation_socket()` running inside the real worker process,
  producing the real `connected` event (correct `conversation_id` and
  tenant-scoped `user_id`) and a real `pong` in response to `ping`.
- The full device-pairing flow: `molly connect` in fleet mode correctly
  requests a code from the gateway using the worker's own credentials
  (no tunnel required for this call); redeeming that code via
  `POST /devices/pair` returns a real token pair with the correct
  `default_worker_id`; reusing the same code is correctly rejected
  (`400 Invalid or expired code`); and the issued access token correctly
  authenticates against the REST proxy (confirmed getting a `503 Worker
  is offline` rather than a `401`, i.e. auth passed and it got as far as
  looking for the worker's tunnel).
- Relay-token verification correctly rejecting both a bad signature and a
  token minted for a different `worker_id`.
- **REST auth is now enforced**: a request to `/w/{worker_id}/conversations`
  with no token returns 401; with a real device access token it returns
  200 and reaches the real worker.
- **Refresh-token rotation**: `POST /devices/{id}/token` issues a real
  `{access_token, refresh_token, token_type, expires_in, refresh_expires_in}`
  pair; `POST /auth/refresh` rotates it (new pair, old one marked used);
  replaying the already-rotated refresh token is correctly rejected
  (`401 refresh token already used or revoked`); the new access token
  works against the REST proxy.
- **Multi-process routing via Redis**: two separate gateway processes
  sharing one Redis instance, a worker's tunnel physically held by
  process A only. Process B - which never touched that tunnel - correctly
  reported the worker `"online": true` (via Redis presence) and correctly
  proxied a real `POST /w/{worker_id}/conversations` through to the real
  worker (via `DistributedWorkerConnection` → Redis pub/sub → process A's
  bridge → the actual tunnel), confirmed by then reading that same
  conversation back through process A directly.
- Unit-level round trips for the frame protocol and `TunnelChannel`'s
  send/receive/close behavior.

Two things were exercised only *through the HTTP path*, not directly: the
distributed WS-channel path (`DistributedGatewayChannel`) and cross-process
`force_disconnect` follow the identical publish/subscribe pattern already
proven correct for HTTP requests, but weren't independently re-run end to
end - flagged here rather than silently assumed.

One real bug was found and fixed along the way: SQLite drops tzinfo on
read even for `DateTime(timezone=True)` columns, so a timestamp written as
timezone-aware comes back naive and blows up on comparison. Fixed by
switching the gateway to naive-UTC-everywhere (`app/timeutils.py`) instead
of fighting SQLite's type affinity - works identically against Postgres.

## What was fixed after the first pass

- **REST routes now require auth.** `approvals.py`, `files.py`, `images.py`,
  `projects.py`, `settings.py`, and `routes.py` (conversations) all declare
  `dependencies=[Depends(get_current_user)]` at the router level, verified
  against the gateway's relay token now that self-hosted's local
  Bearer-JWT path is gone (see `app/auth/dependencies.py`). `health.py`
  is correctly left as-is; the WebSocket route no longer exists as a
  standalone endpoint (fleet's `WS_OPEN` frame handling authenticates
  the same way before calling `handle_conversation_socket`).
- **Protocol duplication eliminated.** `protocol/` is now a real
  installable package (`molly_tunnel_protocol`) that both `backend/` and
  `gateway/` depend on (`-e ../protocol` in each `requirements.txt`). The
  old `backend/app/tunnel/protocol.py` / `relay_token.py` and
  `gateway/app/tunnel/protocol.py` / `relay_token.py` are gone - there's
  one copy of the frame format and the relay-token logic, not two that
  could drift.
- **Refresh-token rotation**, ported from the worker's original
  single-tenant `app/auth/jwt.py` pattern with `tenant_id` added:
  `gateway/app/models.py`'s new `RefreshToken` table, `issue_token_pair` /
  `rotate_refresh_token` / `revoke_all_refresh_tokens` in
  `gateway/app/auth/tokens.py`, and a gateway-native `POST /auth/refresh`
  matching the mobile app's existing `RefreshResponse` contract exactly
  (`{access_token, refresh_token, token_type, expires_in, refresh_expires_in}`).
  Reusing an already-rotated refresh token is refused, not silently
  re-served - see rotate_refresh_token's docstring for why that distinction
  matters (it's the signal of a stolen token, not just a slow client).
  `POST /admin/devices/{id}/revoke` also kills a device's outstanding
  refresh tokens.
- **Multi-process gateway support.** New `gateway/app/tunnel/bus.py`
  (Redis pub/sub) plus `DistributedWorkerConnection` /
  `DistributedGatewayChannel` in `registry.py`: any gateway process can
  now talk to any worker regardless of which process physically holds
  that worker's tunnel WebSocket, by publishing frames on a per-worker
  Redis channel that the owning process's `worker_ws.py` bridges to the
  real socket. Presence is heartbeat-refreshed in Redis so a crashed
  process's workers don't stay marked online. Entirely opt-in: leave
  `REDIS_URL` unset and this code path is never touched - single-process
  behavior is unchanged from before this existed.

## What's still a deliberate scope boundary, not a bug

- **Real accounts exist (`gateway/app/api/account.py`'s `/auth/signup` /
  `/auth/login`), but email verification, password reset, and multiple
  users per tenant sharing distinct roles don't.** `User.role` exists and
  signup always creates an "admin"; nothing yet stops or lets a second
  person sign up onto the same tenant - that's a real feature (invites),
  not a fix. The per-tenant API key (`gateway/app/auth/tenant_auth.py`)
  still exists alongside real accounts, for scripts/CI.
- **No billing.** Nothing here meters usage or gates access on a plan;
  that's a genuinely separate feature, not something to bolt on as a fix.
- **No admin UI.** Everything is API-only; a console (create pairing
  sessions, see workers online/offline, revoke devices) is a thin
  frontend over endpoints that already exist - `admin_workers.py` and
  `admin_devices.py` are the whole surface it would need.
- **`shared/protocol.py`'s duplication is gone, but the package still
  lives inside this monorepo** rather than being published anywhere -
  fine for one team building both services together, worth a real
  package registry once the gateway and worker have separate release
  cadences or separate teams.

## Running it locally

```bash
# --- redis (only needed if you want to run more than one gateway process) ---
redis-server --daemonize yes

# --- gateway ---
cd gateway
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt   # installs ../protocol as an editable dep
cp .env.example .env              # set REDIS_URL if you're testing multi-process
python -m app.cli create-tenant --name "Acme Corp"   # prints tenant_id + api_key
uvicorn app.main:app --port 8080

# --- worker, in another shell ---
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt   # installs ../protocol as an editable dep
cp .env.example .env   # fill in an LLM_API_KEY if you want real agent runs

# mint a one-time enrollment token (needs the tenant's api_key from above)
# - or skip this curl call entirely and use the enrollment_token that
#   POST /auth/signup already returned when you created the tenant above
curl -X POST http://localhost:8080/admin/workers/tokens \
  -H "X-API-Key: <api_key>" -H "Content-Type: application/json" \
  -d '{"label_hint":"my-vps-1"}'

python -m app.cli worker enroll --gateway http://localhost:8080 --token <enrollment_token>
python -m app.cli serve   # now also dials out to the gateway on startup

# --- confirm it connected ---
curl http://localhost:8080/admin/workers -H "X-API-Key: <api_key>"
# -> "online": true
```

From there, pair a device (`molly connect` on the server → code → `POST
/devices/pair` from the phone) to get a real access/refresh token pair,
and `POST /w/{worker_id}/conversations` / `GET /w/{worker_id}/conversations`
on the gateway reach the worker exactly like they would talking to it
directly - just routed through the gateway, authenticated, and (if
`REDIS_URL` is set) reachable from any gateway process in the fleet.

## Where things live

```
protocol/molly_tunnel_protocol/
  protocol.py      wire format (TunnelFrame, FrameType) - shared by both services
  relay_token.py   mint (gateway) + verify (worker) for signed relay assertions

backend/app/tunnel/
  channel.py      TunnelChannel - makes one muxed channel look like a WebSocket
  client.py       the outbound connection: HTTP-via-ASGI-transport + WS muxing
  enrollment.py   trades a one-time token for this worker's permanent credential
backend/app/auth/
  dependencies.py get_current_user - relay-token-only now (self-hosted's local
                  Ed25519/JWT auth was removed; see README's pairing section)

gateway/app/
  models.py             Tenant, Worker, WorkerEnrollmentToken, User, Device,
                         PairingCode, RefreshToken
  auth/passwords.py      PBKDF2 hashing for real user passwords
  auth/tokens.py         access-token mint/verify + refresh-token issue/rotate/revoke
                         + user-session token mint/verify (real accounts)
  auth/tenant_auth.py    admin auth: X-API-Key or a logged-in user's session
  auth/device_auth.py    authenticates a paired device's own /auth/me, /auth/logout
  auth/worker_auth.py    authenticates a worker's own direct calls (X-Worker-Id/-Token)
  tunnel/bus.py          Redis pub/sub bridge for multi-process routing (optional)
  tunnel/registry.py     WorkerConnection (local) + DistributedWorkerConnection (via bus)
  api/worker_ws.py        /worker/connect - where workers dial in
  api/mobile_ws.py         /w/{worker_id}/ws/conversations/{id} - mobile realtime traffic
  api/proxy.py              /w/{worker_id}/{path:path} - generic REST reverse proxy
  api/account.py            /auth/signup, /auth/login - real email/password accounts
  api/admin_workers.py      enrollment tokens, list/revoke workers
  api/pairing.py            /worker/pairing-codes, /devices/pair - the pairing flow above
  api/admin_devices.py      /auth/refresh, /auth/me, /auth/logout, /admin/devices/{id}/revoke
```
