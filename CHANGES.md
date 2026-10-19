# Outbound file attachments — patch summary

Overlay these files onto your project at the matching paths (they replace the
originals 1:1). No new dependencies, no manual DB migration step — the sqlite
schema self-migrates on next startup.

## Backend

- **storage/database.py** — adds an `origin` column (`upload` | `generated`)
  to `files` and `images`, with a startup migration for existing DBs.
- **storage/files.py`, `storage/images.py`** — new `register_generated_file()`
  / `register_generated_image()`, which copy a file already on disk into
  conversation storage and give it a real `file_id`/`image_id`, same
  lifecycle as an upload (list/delete/cleanup all just work).
- **api/files.py`, `api/images.py`** — new `GET .../files/{id}/content` and
  `.../images/{id}/content` routes that stream the actual bytes. (Turns out
  even uploaded files couldn't be downloaded before this — only metadata was
  ever served.)
- **tools/sharing.py** (new) — the `share_file` tool. Point it at a path
  already on disk (e.g. something just written with `write_file`) and it
  validates the file and signals intent; it doesn't touch the DB itself
  since a tool has no `conversation_id` to work with.
- **tools/__init__.py** — registers `share_file` alongside the other tools.
- **agent/executor.py** — after a successful `share_file` call, registers the
  attachment (via the storage functions above), includes it on the
  `tool_completed` event, and rolls up the full list into `agent_completed`
  and the final assistant message's `metadata.attachments`.

## Frontend (molly-app)

- **types/api.ts** — `MessageAttachment` type; `Message.metadata` now types
  the optional `attachments` key; `FileResponse`/`ImageResponse` gained
  `origin`.
- **api/files.ts`, `api/images.ts`** — `contentUrl(conversationId, id)`
  helper. (The existing `resolveUrl(path)` doesn't correspond to a real
  route — there's no static file mount — so it's left in place but you
  likely want `contentUrl` instead.)
- **context/WebSocketContext.tsx** — typed the new `attachment`/`attachments`
  fields on `tool_completed`/`agent_completed`.
- **components/FilePreview.tsx** — added `onPress` (for opening a sent
  attachment) and `kind` (file vs image icon), alongside the existing
  `onRemove` used by the composer.
- **components/MessageBubble.tsx** — assistant messages now render any
  `metadata.attachments` as pressable file chips that open via
  `Linking.openURL`. (Note: neither user- nor assistant-side attachments
  were rendered in the bubble before this patch.)

## Things worth deciding yourselves

- **Downloads open in the system browser** (`Linking.openURL`), not a native
  save/share sheet — there's no `expo-file-system`/`expo-sharing` in
  `package.json` yet. Worth adding if you want a proper "Save to Files"
  flow.
- **No auth on the content routes** — matches the existing files/images
  routers (neither had a `Depends(current_user)` before this patch), but
  worth a look since these routes serve arbitrary server file content.
- **`share_file` risk level is `READ`** — same tier as `read_file`, so it
  runs without an approval prompt. If you want a heads-up/approval before
  Molly hands a file to the client, bump it to `LOW_RISK` in
  `tools/sharing.py`.
- The tool's docstring tells the model not to share secrets (`.env`, keys)
  unless explicitly asked — that's a prompt-level guardrail, not an
  enforced one.
