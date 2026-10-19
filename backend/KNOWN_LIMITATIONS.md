# Known Limitations

## Architecture

1. **Provider Support**: Native Anthropic (Messages API) and OpenAI-compatible APIs (OpenAI, Ollama, vLLM, Groq, OpenRouter, etc.) are supported. Multiple providers can be chained with automatic retry-then-failover (see `/settings/providers`), but Gemini and other wire protocols still need a new `LLMProvider` implementation for **text mode** — Gemini is only wired up for hands-free voice mode (`app/llm/gemini_live.py`), which is a separate code path, not a `LLMProvider`.

2. **Single-Tenant**: No built-in multi-user support or authentication. Designed for single-user server operation. Add reverse proxy auth (nginx auth_basic, OAuth2 Proxy, etc.) for multi-user.

3. **In-Memory WebSocket State**: Active connections and running agents stored in process memory. Not suitable for horizontal scaling without Redis pub/sub.

4. **SQLite Concurrency**: SQLite with WAL mode handles moderate concurrency but not high-throughput multi-instance deployments. Consider PostgreSQL for production clusters.

## Agent Capabilities

5. **No Parallel Tool Execution**: Tools execute sequentially in the agent loop. No `auto` parallel tool calling.

6. **No Streaming Tool Results**: Tool results returned after full completion. No progressive output for long-running commands.

7. **Fixed Tool Set**: 17 tools locked for V1. Adding tools requires code changes (though registry makes it straightforward).

8. **No Built-in Skills/Plugins**: No plugin system for domain-specific extensions. All logic in core tools or LLM prompting.

## Approval System

9. **Blocking Approvals**: Agent pauses entirely while waiting for approval. No concurrent task processing.

10. **No Approval Delegation**: Can't pre-approve patterns or delegate to policies. Every MODERATE+ action requires explicit user action.

11. **Timeout Handling**: Expired approvals move to EXPIRED state but don't automatically clean up agent state. Manual handling needed.

12. **Correction Limitations**: Corrections feed back as user messages. Complex corrections may confuse the agent.

## Image Handling

13. **Local Storage Only**: Images stored on local filesystem. No S3/CDN integration.

14. **Manual Cleanup**: Time-based and count-based cleanup only. No reference counting (images persist even if conversation deleted).

15. **Format Support**: PNG, JPEG, WebP, GIF only. No HEIC, AVIF, or RAW.

16. **Size Limits**: Configurable max size (default 10MB). Large screenshots may exceed.

## File Handling

16a. **Any File Type Accepted**: Uploads aren't gated by extension or content — same posture as the rest of Molly's unsandboxed server access (see #29). `read_file` decides how to render each one back (text/archive/PDF/binary summary).

16b. **Archive Entry Reads Are Bounded**: `read_file` caps any single zip/office-archive entry at 5MB to avoid a single-entry zip-bomb; listing entries itself doesn't decompress anything.

16c. **PDF Text Extraction Only**: `read_file` extracts text via pypdf. Scanned/image-only PDFs return little or no text (no OCR).

## Tool Limitations

17. **execute_command**: 
    - No interactive/TTY support (no `sudo -A`, no interactive prompts)
    - No background job management (fire-and-forget)
    - Shell=True by default (injection risk mitigated by approval)

18. **search_files**: Uses `find` + `grep` - not indexed. Slow on large filesystems.

19. **read_file**: Text, zip-family archives (list/read entries), and PDFs (text extraction) are supported. Other binary formats (images aside — use view_image — and anything pypdf/zipfile can't parse) return a metadata summary (mime type, size, hex preview) rather than content.

20. **edit_file**: Line-based operations. No AST-aware editing for code.

21. **Git tools**: Require git CLI. No libgit2/pygit2 for performance.

## Token/Context Management

22. **Rough Token Estimation**: Character-based (4 chars ≈ 1 token). Not model-accurate.

23. **No Semantic Compaction**: Compaction keeps recent messages, summarizes older. No importance scoring.

24. **Image Tokens Not Counted**: Image tokens not included in context budget estimation.

## Operations

25. **No Metrics/Observability**: No Prometheus metrics, no structured logging beyond stdout.

26. **No Rate Limiting**: API endpoints not rate-limited. Add at reverse proxy.

27. **No Backup/Restore**: SQLite backup requires manual `cp` or `.backup` command.

28. **No Health Checks for Tools**: Tool failures surface as errors, no circuit breaker.

## Security

29. **Full server Access**: By design - Molly has same access as the OS user. No sandbox.

30. **Command Injection**: `execute_command` uses `shell=True`. Mitigated by approval but not eliminated.

31. **Path Traversal**: Validated but not sandboxed. `../../etc/passwd` resolves to `/etc/passwd`.

32. **No Encryption at Rest**: SQLite and images unencrypted. Use LUKS/dm-crypt for disk encryption.

## Testing

33. **Integration Tests Limited**: Most tests are unit tests with mocks. No full end-to-end test suite.

34. **No Chaos Testing**: No fault injection for network, disk, or process failures.

35. **No Load Testing**: Concurrent user/agent load not validated.

## Hands-Free Voice Mode

39a. **Session Length Cap**: Gemini Live connections are limited by Google to roughly 10 minutes (per `live_session_max_minutes`). Molly closes the session proactively and the person has to tap the mic again to start a new one — there's no automatic reconnect-and-resume yet, so context from before the cutoff isn't carried into the new session (Gemini's own `session_resumption` handle isn't wired up).

39b. **Foreground Only**: No background mode, no wake word. The session ends if the app is backgrounded or the chat screen is left. This is a deliberate v1 scoping choice, not a technical ceiling - `react-native-audio-api` does support background audio if this is revisited.

39c. **Voice Confirmation Is a Fixed Vocabulary**: Approving/rejecting a risky tool call by voice only recognizes the exact configured words (default "confirm"/"cancel", see `live_voice_confirm_words`/`live_voice_cancel_words`), deliberately conservative to avoid a misheard "yes" approving something destructive. Anything else falls through to the in-app approval card (or a timeout).

39d. **One Live Session Per Conversation**: Only one Gemini Live session can be active per conversation's socket at a time; starting live mode while a text-mode agent run is already going isn't a supported combination (the UI only exposes the mic when nothing else is running).

39e. **No Session Resumption Across Reconnects**: A dropped WebSocket (app backgrounded, network blip) ends the Gemini Live session entirely rather than resuming it - see 39a.



36. **Systemd Only**: No Kubernetes/Docker Compose/Helm charts provided.

37. **No Zero-Downtime Deploy**: Restarting service drops active WebSocket connections.

38. **Manual Config**: `.env` file, no config management (Consul, etcd, etc.).

39. **Log Rotation**: Uses journald. No built-in log rotation for application logs.

## Future Work (Post-V1)

- [ ] Additional provider wire protocols (Gemini, local GGUF)
- [ ] Plugin system for custom tools
- [ ] PostgreSQL backend option
- [ ] Redis-backed session/WebSocket scaling
- [ ] OAuth2/OIDC authentication
- [ ] Prometheus metrics + Grafana dashboards
- [ ] Structured JSON logging
- [ ] AST-aware code editing tools
- [ ] Interactive command support (pty)
- [ ] Background job management
- [ ] Semantic context compaction with embeddings
- [ ] Image token counting
- [ ] S3-compatible image storage
- [ ] Reference-counted image cleanup
- [ ] Approval policies/pre-approvals
- [ ] Multi-user with RBAC
- [ ] Kubernetes deployment manifests
- [ ] Zero-downtime deployment strategy
- [ ] Gemini Live session resumption across reconnects/time-limit cutoffs
- [ ] Background/wake-word hands-free voice mode