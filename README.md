# Molly

A self-hosted AI agent that operates a Linux server through natural language —
inspect it, change it, troubleshoot it — with a mobile client for reaching it
from anywhere.

Molly proposes actions rather than just answering questions, so every action is
risk-classified and anything above read-only pauses for an explicit
**approve / reject / correct** decision before it runs.

## What it does

- **Operates the server** — system, disk, memory and process inspection; file
  reads/writes/edits; shell commands; git. All driven by natural language.
- **Approval gate** — actions are tiered `READ` → `LOW_RISK` → `MODERATE` →
  `HIGH_RISK` → `DANGEROUS` → `CRITICAL`; everything past read-only waits for
  approval, and "correct" feeds a revised action back to the agent.
- **Multimodal** — native image understanding, so a screenshot or a stack
  trace can be attached and discussed.
- **Skills** — reusable, on-demand instructions stored as plain `SKILL.md`
  files on disk, indexed into the system prompt by name + description and
  loaded in full only when relevant.
- **Agent modes** — `general` (operate this server) and `bug_bounty`
  (authorized security testing, scope-and-authorization first). The mode
  changes how Molly reasons, not what it is allowed to do.
- **Live voice** — realtime voice sessions over the Gemini Live API; caps and
  caveats are documented in `backend/KNOWN_LIMITATIONS.md`.
- **Mobile client** — Expo SDK 54 / React Native 0.81 app for iOS and Android.

## Repository layout

| Path | What it is |
|------|------------|
| `backend/` | The worker: the FastAPI agent API — conversations, approvals, tools, skills. Defaults to `:8000`. |
| `gateway/` | Optional multi-tenant front door for fleet deployments. Defaults to `:8080`. |
| `protocol/` | `molly-tunnel-protocol` — the tunnel wire format and relay-token helpers shared by `backend/` and `gateway/`. |
| `molly-app/` | The Expo / React Native mobile client. |
| `openapi.json` | The backend's OpenAPI spec (mirrored by `molly-app/src/types/api.ts`). |
| `CHANGES.md` | Change log. |
| `setup-android-build.sh` | Installs a user-local Android build toolchain — see below. |

## How it fits together

A worker can be reached in two ways, and **the two modes are not exclusive** —
one worker can serve local clients *and* be reachable through a gateway at the
same time (see `gateway_ws_url` in `backend/app/config.py`).

### Direct (the default)

`backend/` serves its own REST + WebSocket API on `:8000`, and clients talk to
it directly — localhost, a LAN address, or a Tailscale address. With
`gateway_ws_url` left blank, no gateway is involved at all.

Access is by **device pairing, not passwords**. The mobile app:

1. generates an Ed25519 keypair on-device — the private key never leaves the
   device, it is held in `expo-secure-store` (Keychain / Keystore);
2. calls `POST /auth/device/register` with the public key and gets back a
   challenge plus a short pairing code;
3. shows that code so it can be approved at the server's `/connect` page;
4. signs the challenge and calls `POST /auth/device/verify` to exchange it for
   an access/refresh token pair, which `src/api/client.ts` then refreshes
   transparently.

Relevant code: `backend/app/auth/` (`router.py`, `device_keys.py`, `jwt.py`),
`molly-app/src/api/auth.ts`, `molly-app/src/context/AuthContext.tsx`.

### Fleet (optional, via `gateway/`)

A shared gateway cannot dial *into* an arbitrary server — most sit behind NAT
with no inbound access. So the worker is the side that connects out: it opens
one persistent outbound WebSocket to the gateway's `/worker/connect`,
authenticates once, and multiplexes everything else (REST calls and the
conversation WebSocket) as small JSON frames. That is the same shape as ngrok
or Cloudflare Tunnel, carrying both HTTP and one specialized WebSocket.

The gateway then reverse-proxies per tenant at `/w/{worker_id}/…` to whichever
worker owns that tenant's traffic, and can run as more than one process when
`REDIS_URL` is set. Gateway accounts are real email/password
(`/auth/signup`, `/auth/login`), followed by code-based device pairing
(`POST /devices/pair`); every request a worker receives carries a relay token
the gateway signed with that worker's own `worker_secret`.

Relevant code: `backend/app/tunnel/`, `gateway/app/api/`,
`gateway/app/tunnel/`, `protocol/molly_tunnel_protocol/`.

To enable it, enroll the worker (`python -m app.cli worker enroll`, which
writes `data/gateway_credential.json`) and set `gateway_ws_url` in its `.env`.

## Quick start

### Backend (worker)

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt   # also installs ../protocol as an editable dep
cp .env.example .env              # set LLM_API_KEY etc. for real agent runs
python -m app.cli serve           # http://localhost:8000
```

Useful CLI commands:

```bash
python -m app.cli run "Check disk usage"   # one-off agent run
python -m app.cli run --mode bug_bounty "…" # same, bug-bounty mode
python -m app.cli tools                    # list available tools
python -m app.cli projects                 # list registered projects
python -m app.cli worker enroll --gateway http://localhost:8080 --token <token>
python -m app.cli worker status            # fleet enrollment status
python -m app.cli worker unenroll
python -m app.cli connect                  # print a device pairing code
```

The full API reference — every endpoint, the 19 tools and their risk tiers,
the approval flow, skills, agent modes and Ubuntu deployment notes — lives in
**`backend/README.md`**.

### Mobile app

```bash
cd molly-app
npm install
npx expo start
```

The API host is configured in `molly-app/src/api/client.ts` (`API_BASE_URL` /
`WS_BASE_URL`). See `molly-app/README.md` for the app's structure and auth
notes.

### Gateway (only needed for fleet mode)

```bash
cd gateway
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.cli create-tenant --name "Acme Corp"   # prints tenant_id + api_key
uvicorn app.main:app --port 8080
```

Then enroll the worker as shown above and start it — it dials out to the
gateway on startup. Confirm with:

```bash
curl http://localhost:8080/admin/workers -H "X-API-Key: <api_key>"
# -> the worker should report "online": true
```

## Building the Android app locally

`setup-android-build.sh` installs everything needed under `$HOME` — no sudo —
and writes the env vars to `~/.android-env.sh`:

- Temurin **JDK 17** (what `kotlin.jvmToolchain(17)` and AGP 8.11 expect)
- **Node 22 LTS** (React Native 0.81 requires ≥ 20.19.4)
- Android SDK pieces: `platform-tools`, `platforms;android-36`,
  `build-tools;36.0.0`, `ndk;27.1.12297006`, `cmake;3.22.1`

```bash
./setup-android-build.sh
cd molly-app
npm install
npx expo prebuild --platform android
cd android && ./gradlew assembleDebug
```

Gradle itself is deliberately not installed separately — the wrapper generated
by `expo prebuild` fetches the exact version the project needs.

## Tests

```bash
cd backend && source venv/bin/activate && pytest tests/ -v
```

`gateway/` has no test suite yet.

## Where things live

```
protocol/molly_tunnel_protocol/
  protocol.py       TunnelFrame / FrameType wire format (shared by both services)
  relay_token.py    mint (gateway) + verify (worker) for signed relay assertions

backend/app/
  api/              REST routers + the conversation WebSocket manager
  agent/            agent loop, context assembly, token budgeting, compaction
  llm/              provider abstraction (OpenAI-compatible + Gemini Live)
  tools/            tool implementations with risk tiers
  security/         path safety, risk classification, approval state machine
  storage/          SQLite, projects, images, files
  auth/             Ed25519 device pairing + token verification
  tunnel/           outbound fleet connection (channel, client, enrollment)
  skills/           filesystem-backed SKILL.md registry
  cli.py            CLI entry point

gateway/app/
  api/account.py        /auth/signup, /auth/login — real email/password accounts
  api/pairing.py        /worker/pairing-codes, /devices/pair
  api/admin_workers.py  enrollment tokens; list/revoke workers
  api/proxy.py          /w/{worker_id}/{path} REST reverse proxy
  api/worker_ws.py      /worker/connect — where workers dial in
  api/mobile_ws.py      /w/{worker_id}/ws/conversations/{id}
  tunnel/registry.py    WorkerConnection + DistributedWorkerConnection
  tunnel/bus.py         Redis pub/sub for multi-process routing (optional)
  models.py             Tenant, Worker, User, Device, RefreshToken, …

molly-app/src/
  api/          REST service layer (auth.ts holds the device-pairing calls)
  context/      AuthContext, WebSocketContext, ConversationsContext, TypographyContext
  screens/      one file per screen
  components/   presentational only — no data fetching
  theme/        design tokens
  types/api.ts  mirrors openapi.json — update this first if the spec changes
```

## Known gaps

- The device-pairing router in `backend/app/auth/router.py` — which defines
  `/auth/device/register` and `/auth/device/verify` — is **not mounted** in
  `backend/app/main.py`. Every router does enforce auth through
  `app.auth.dependencies.get_current_user`, but a freshly started self-hosted
  backend has no mounted endpoint for obtaining a token, which is exactly what
  `molly-app/src/api/auth.ts` calls.
- `gateway/` has no tests.
- There is no `LICENSE` file in the repository, although `backend/README.md`
  states MIT.
