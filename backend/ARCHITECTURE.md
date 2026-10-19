# Molly Backend - Architecture Explanation

## Overview

Molly is an autonomous DevOps assistant implemented as a single multimodal LLM agent with 17 tools. The architecture prioritizes token efficiency, safety through approval flows, and production readiness on low-resource server.

## Core Design Principles

### 1. Single Multimodal Agent
- Molly IS the LLM - no separate vision agent
- Images are lightweight references until `view_image()` is called
- Actual image bytes only sent to LLM when Molly decides to inspect

### 2. Filesystem as Source of Truth
- No project-directory sandbox (`ALLOWED_PROJECT_ROOTS` explicitly rejected)
- Registered projects are metadata only
- Molly can discover and work with arbitrary paths
- OS permissions are the security boundary

### 3. Approval-First Philosophy
- Dangerous actions → approval request (not rejection)
- User can: APPROVE, REJECT, CORRECT
- Correction cancels original, feeds instruction back to agent
- Full audit trail in SQLite

### 4. Token Efficiency First
- Every tool has bounded output
- Context manager compacts history
- Image binaries never in conversation history
- Search → locate → read relevant section pattern

## Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        FastAPI Server                        │
├─────────────────────────────────────────────────────────────┤
│  REST API          │  WebSocket          │  Static Files    │
│  /conversations    │  /ws/conversations  │  (none)          │
│  /approvals        │  Events:            │                  │
│  /projects         │  - approval_required│                  │
│  /settings         │  - tool_started     │                  │
│  /health           │  - agent_completed  │                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Agent Executor                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Context Mgr │  │  State Mgr  │  │  Approval Engine    │  │
│  │ - Token budget│ │ - Iterations│ │ - Risk classifier   │  │
│  │ - Compaction  │ │ - Tool calls│ │ - State machine     │  │
│  │ - Image refs  │ │ - Cancellation│ │ - Correction flow  │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌─────────────────────┐ ┌─────────────┐ ┌─────────────┐
│   LLM Provider      │ │ Tool Registry│ │  Storage    │
│  (OpenAI-compat)    │ │ (17 tools)  │ │  (SQLite)   │
└─────────────────────┘ └─────────────┘ └─────────────┘
```

## Key Modules

### Agent Loop (`app/agent/executor.py`)
```python
# Core loop:
while not terminal:
    response = await llm.chat(messages, tools)
    if response.tool_calls:
        for tool_call in response.tool_calls:
            assessment = risk_classifier.classify(tool)
            if requires_approval(assessment):
                create_approval()
                wait_for_user()
                if corrected: feed_back_to_agent()
            execute_tool()
            add_tool_result()
    else:
        return final_response
```

### Context Manager (`app/agent/context.py`)
- Maintains `ConversationContext` with token budget
- Loads recent history + image references (not binaries)
- Compacts when exceeding `max_messages`
- Estimates tokens for budget enforcement

### Risk Classifier (`app/security/risk.py`)
- Pattern-based classification for commands
- Considers: command, arguments, cwd, sensitive paths
- Levels: READ → LOW → MODERATE → HIGH → DANGEROUS → CRITICAL
- Extensible for custom rules

### Permission Engine (`app/security/permissions.py`)
- State machine: PENDING → APPROVED/REJECTED/CORRECTED → EXECUTING → COMPLETED/FAILED
- Correction creates NEW approval flow, original cancelled
- Timeout handling (configurable)
- WebSocket events for real-time UI

### Tool Registry (`app/tools/registry.py`)
- Single source of truth for all 17 tools
- Generates OpenAI schemas from tool classes
- Risk level, timeout, output limits per tool
- No duplicate definitions

### LLM Provider (`app/llm/`)
- Abstract base class for providers
- OpenAI-compatible implementation
- Multimodal message conversion
- Streaming support

### Hands-Free Voice Mode (`app/llm/gemini_live.py`, `app/agent/live_executor.py`)
- Separate code path from the `LLMProvider` abstraction above, since the Gemini Live API is a
  stateful bidirectional audio WebSocket rather than a request/response chat completion.
- `LiveAgentExecutor` is AgentExecutor's voice counterpart: same risk classifier, same
  `PermissionEngine`, same tool registry, same `approval_required`/`tool_started`/`tool_completed`
  event vocabulary over the *same* `/ws/conversations/{id}` socket - so the app's existing
  approval card works unmodified whether the person taps it or answers Molly out loud.
- Approving a risky tool call by voice is a fixed, deliberately narrow word (default
  "confirm"/"cancel", see `app/agent/live_voice.py`) matched against Gemini's own transcription,
  not a general "did they sound like they agreed" judgment call.
- See `KNOWN_LIMITATIONS.md` for session-length and reconnection caveats.

### Storage (`app/storage/`)
- SQLite with schema for: conversations, messages, tasks, tool_calls, approvals, agent_runs, images, projects
- JSON project files for portability
- Image metadata + filesystem storage

## Data Flow Example

**User**: "Check why Mantis is returning 502"

```
1. POST /conversations/{id}/messages
   {"content": "Check why Mantis is returning 502"}

2. AgentExecutor.run()
   - Load context (recent msgs, project refs)
   - LLM: get_system_info, get_service_status("nginx")
   
3. Tool: get_service_status("nginx")
   - Returns: active=active, sub=running, pid=1234
   
4. LLM: execute_command("curl -I localhost:8000")
   - Risk: MODERATE → approval required
   
5. WebSocket: approval_required event
   User clicks APPROVE
   
6. Tool executes, returns 502 response
   
7. LLM: read_file("/var/www/mantis/config/nginx.conf")
   
8. LLM: edit_file(nginx.conf, fix_upstream)
   
9. LLM: execute_command("systemctl reload nginx")
   - Risk: MODERATE → approval required
   
10. User approves
   
11. LLM: execute_command("curl -I localhost:8000")
    - Returns 200 OK
    
12. Final response: "Fixed upstream config, Mantis now returns 200"
```

## Multimodal Flow

**User uploads screenshot of 502 error**

```
1. POST /conversations/{id}/images
   Returns: {image_id, path, mime_type, width, height}

2. User message with attachment:
   {"content": "Fix this", "attachments": [{"type": "image", "image_id": "img_abc"}]}

3. Agent context gets image_reference (not binary)
   
4. LLM decides to inspect → calls view_image("img_abc")
   
5. view_image tool validates, returns metadata + attach_to_next_request
   
6. Next LLM call includes actual image bytes (base64 data URL)
   
7. LLM visually reasons: "Screenshot shows nginx 502, upstream timeout"
   
8. Continues with server tools to diagnose
```

## Concurrency & Safety

- **Single-threaded agent per conversation** (WebSocket connection)
- **Asyncio** for I/O (LLM, tools, DB)
- **Process groups** for command execution (cleanup on timeout/cancel)
- **Atomic file writes** (temp file + rename)
- **SQLite WAL mode** for concurrent reads
- **Cancellation propagation** to subprocesses

## Scaling Considerations

| Aspect | Current | Scale Path |
|--------|---------|------------|
| DB | SQLite | PostgreSQL |
| Sessions | In-memory | Redis pub/sub |
| Images | Local FS | S3-compatible |
| Auth | None | OAuth2/OIDC proxy |
| Multi-user | Single tenant | Add user_id to all tables |

## Security Model

1. **OS Permissions**: Molly runs as dedicated user, `sudo` for privileged ops
2. **No Sandbox**: Full server access (by design)
3. **Approval Gate**: All MODERATE+ actions require user consent
4. **Audit Trail**: Every tool call + approval in SQLite
5. **Secret Handling**: API keys server-side only, redacted in logs
6. **Path Validation**: Canonicalization, no null bytes, traversal checks

## Extension Points

- **New Tools**: Add class, register in `app/tools/__init__.py`
- **New Providers**: Implement `LLMProvider` base class
- **Custom Risk Rules**: Extend `RiskClassifier`
- **New Storage**: Implement storage interfaces
- **Auth**: Add middleware + user_id to models