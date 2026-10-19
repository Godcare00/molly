# Molly — mobile app

React Native + Expo + TypeScript client for the Molly backend
(`https://molly.devs.surf`), built directly against its OpenAPI spec.

## Setup

```bash
npm install
npx expo start
```

Requires the Expo Go app or a dev build for `expo-secure-store` /
`expo-image-picker`. iOS 15+ / Android 8+.

## Architecture

```
src/
  api/            REST service layer (one file per backend tag), thin fetch client
                  with automatic token refresh in client.ts
  context/        AuthContext (device pairing/session), WebSocketContext
                  (live events), ConversationsContext (chat list + active id)
  hooks/          useConversation (history + streaming merge), useApprovals
  navigation/     Root switch (auth vs. app) → bottom tabs → per-tab stacks
  screens/        One file per screen
  components/     Reusable, presentational only — no data fetching
  theme/          Design tokens (color, spacing, radius, type)
  types/api.ts    Mirrors the OpenAPI schemas 1:1 — update this first if the
                  backend spec changes
  utils/          Secure storage wrapper, Ed25519 keypair/signing helpers
```

## Auth: passwordless device pairing

The backend has no password endpoints — `/auth/device/register` and
`/auth/device/verify` are the entire auth surface. This app treats
**pairing this device as login**:

1. Generate an Ed25519 keypair on-device (`tweetnacl`). The private key
   never leaves the device — it's stored in `expo-secure-store`
   (Keychain / Keystore), never in the JS bundle, logs, or over the wire.
2. `POST /auth/device/register` with the public key (PEM/SPKI) → backend
   returns a challenge string.
3. Sign the challenge locally, `POST /auth/device/verify` with the
   signature → backend returns an access/refresh token pair.
4. Tokens are stored in SecureStore; `client.ts` refreshes the access
   token transparently on 401s and de-dupes concurrent refreshes.

**Assumption to confirm with backend:** the challenge is signed as raw
UTF-8 bytes of the challenge string (`signChallenge` in
`utils/ed25519.ts`). If the backend actually expects the challenge
base64-decoded first, that's a one-line change in that function.

There is currently no user self-registration endpoint in the spec —
user accounts appear to be provisioned some other way (invite, admin
console, etc.) before a device can pair to them. Flag this if that's
not the case.

## Servers / VPS tab — intentionally omitted

The OpenAPI spec has **no endpoints** for VPS listing, pairing, or
live CPU/RAM/disk/swap metrics — despite that being the centerpiece of
the original mockups. Rather than build a UI against endpoints that
don't exist, this build ships **Chat, Projects, Activity** in the tab
bar only. `/projects` *does* exist and its schema (`path`, `stack`,
`services`, `environment`, `repository`, `branch`) maps closely to
what the mockups actually show for "Servers" — worth checking whether
that's the intended entity, or whether VPS management is meant to
arrive as a future REST resource or purely over WebSocket.

When server endpoints exist, add: `src/api/servers.ts`, a `Server`
type, a `ServersScreen`/`ServerDetailScreen`, and a tab entry in
`MainTabs.tsx` — the existing patterns (Projects tab) are a direct
template.

## WebSocket protocol — provisional, needs backend confirmation

OpenAPI doesn't document WebSocket routes, so `context/WebSocketContext.tsx`
implements a reasonable placeholder protocol, documented in full at the
top of that file:

- Connect: `wss://molly.devs.surf/ws?token=<access_token>`
- Client → server: `subscribe` / `unsubscribe` (per conversation), `ping`
- Server → client: `message.delta`, `message.complete`, `tool.update`,
  `approval.created` / `approval.updated`, `task.status`, `pong`

Everything downstream (`useConversation`, `useApprovals`, `ChatScreen`)
only depends on the `WsEvent` union in that one file, so updating it to
match the real protocol is a contained change — reconnection (backoff),
heartbeat, and per-conversation subscription bookkeeping are already
handled and shouldn't need to move.

## Activity tab

There's no `/activity` or `/tasks` endpoint in the spec, so the
Activity screen is derived from `GET /approvals` (pending, approved,
rejected, corrected), grouped by day. If the backend later exposes a
richer task/event log, swap the data source in `ActivityScreen.tsx`
and extend `ActivityItem` in `types/api.ts`.

## Security notes

- VPS credentials are never requested or stored on-device — servers
  authenticate to the backend independently of the mobile client.
- LLM provider API keys are entered in Settings and sent straight to
  `PUT /settings/provider`; the mobile app never stores or displays a
  full key (the GET response is expected to come back masked, per the
  backend's own doc comment on that endpoint).
- Device private key + tokens live only in SecureStore.

## Known follow-ups

- Wire real push notifications for approvals (currently in-app only).
- Offline queueing for sent messages (currently: optimistic UI +
  rollback on failure, no persistent outbox).
- Add the Servers tab once its endpoints exist.
