# Molly Backend

Autonomous DevOps Assistant API - A multimodal AI agent that operates Linux servers through natural language.

## Features

- **Full Server Control**: Inspect, modify, execute, and troubleshoot entire Linux servers
- **Multimodal**: Native image understanding (screenshots, diagrams, errors)
- **Approval System**: Dangerous actions require user approval with correction flow
- **Token Efficient**: Bounded outputs, context compaction, image references
- **Lightweight**: SQLite, no Docker/Redis/K8s, runs on low-resource server
- **Skills**: reusable on-demand instructions for recurring tasks - see Skills below
- **19 Tools**: System, filesystem, terminal, git, projects, vision, skills

## Quick Start

### Prerequisites

- Python 3.12+
- Ubuntu 22.04+ (or similar)
- OpenAI-compatible API key (OpenAI, Ollama, vLLM, etc.)

### Installation

```bash
cd /var/www/molly/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API key and settings
```

### Configuration

Edit `.env`:

```bash
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-api-key
LLM_MODEL=gpt-4o
```

### Run Server

```bash
python -m app.main
# Or
python -m app.cli serve
```

Server starts at `http://localhost:8000`

### CLI Usage

```bash
# Run a single command
python -m app.cli run "Check disk usage"

# List tools
python -m app.cli tools

# List projects
python -m app.cli projects
```

## API Endpoints

### Conversations
- `POST /conversations` - Create conversation (optional `mode`: `"general"` default, or `"bug_bounty"` - see Agent Modes below)
- `GET /conversations` - List conversations
- `GET /conversations/{id}` - Get conversation
- `GET /conversations/{id}/messages` - Get messages
- `POST /conversations/{id}/messages` - Add message
- `PATCH /conversations/{id}/settings` - Update `allow_all` and/or `mode`

### Images
- `POST /conversations/{id}/images` - Upload image
- `GET /conversations/{id}/images` - List images
- `GET /conversations/{id}/images/{image_id}` - Get image metadata

### Approvals
- `GET /approvals` - List approvals
- `GET /approvals/{id}` - Get approval
- `POST /approvals/{id}/approve` - Approve action
- `POST /approvals/{id}/reject` - Reject action
- `POST /approvals/{id}/correct` - Correct action

### Projects
- `GET /projects` - List projects
- `GET /projects/{id}` - Get project
- `POST /projects` - Create project
- `PUT /projects/{id}` - Update project

### Settings
- `GET /settings/provider` - Get provider config
- `PUT /settings/provider` - Update provider config
- `GET /settings/providers` - Get the full provider chain (primary + fallbacks) and retry settings
- `PUT /settings/providers` - Replace the provider chain and retry settings
- `POST /settings/provider/test` - Test a provider config without applying it
- `GET /settings/bug-bounty-model` - Get the bug_bounty-mode model override (stored in the DB, not .env - see Agent Modes above)
- `PUT /settings/bug-bounty-model` - Set/update the override (only `model` is required; everything else falls back to the primary provider)
- `DELETE /settings/bug-bounty-model` - Clear the override (bug_bounty mode goes back to using the primary provider/model)
- `POST /settings/bug-bounty-model/test` - Test an override config without saving it

### Skills
- `GET /skills` - List configured skills (name + description)
- `GET /skills/{name}` - Get a skill's full content (description, instructions, other files in its directory)
- `PUT /skills/{name}` - Create or update a skill
- `DELETE /skills/{name}` - Remove a skill

### WebSocket
- `WS /ws/conversations/{id}` - Real-time events

## WebSocket Events

```json
{
  "type": "approval_required",
  "approval_id": "appr_abc123",
  "tool": "execute_command",
  "risk_level": "DANGEROUS",
  "reason": "Recursive delete of production directory",
  "arguments": {"command": "rm -rf /var/www/mantis", "cwd": "/var/www"}
}
```

Event types: `assistant_message`, `tool_started`, `tool_output`, `approval_required`, `approval_updated`, `tool_completed`, `agent_completed`, `agent_error`, `image_attached`, `image_viewed`

## Tools

| Tool | Risk | Description |
|------|------|-------------|
| `get_system_info` | READ | OS, kernel, CPU, memory info |
| `get_disk_usage` | READ | Filesystem usage |
| `get_memory_usage` | READ | RAM and swap usage |
| `get_processes` | READ | Process list with filters |
| `get_service_status` | READ | systemd service status |
| `list_directory` | READ | Directory listing |
| `search_files` | READ | Find files by name/content |
| `read_file` | READ | Read file or line range |
| `write_file` | MODERATE | Create/replace file |
| `edit_file` | MODERATE | Targeted file edits |
| `execute_command` | HIGH/DANGEROUS | Shell command execution |
| `git_status` | READ | Git status |
| `git_diff` | READ | Git diff |
| `git_log` | READ | Git commit history |
| `list_projects` | READ | Registered projects |
| `get_project_context` | READ | Project metadata |
| `view_image` | READ | Load image for multimodal reasoning |
| `list_skills` | READ | List configured skills (name + description) |
| `read_skill` | READ | Load a skill's full instructions - see Skills below |

## Risk Levels

- `READ` - Read-only, no approval
- `LOW_RISK` - Minimal impact
- `MODERATE` - Modifies state, approval required
- `HIGH_RISK` - Significant system impact, approval required
- `DANGEROUS` - Destructive, approval required
- `CRITICAL` - Extreme risk, approval required

## Approval Flow

```
Molly proposes dangerous action
         ↓
   APPROVAL REQUIRED (WebSocket event)
         ↓
User: APPROVE / REJECT / CORRECT
         ↓
CORRECT: "Don't delete. Move to /tmp/backup."
         ↓
Original command CANCELLED
         ↓
Molly generates revised action
         ↓
New approval if needed
         ↓
Execute after approval
```

## Agent Modes

Each conversation has a `mode`, stored in its `metadata` (no separate
column/migration) and read fresh at the start of every
`AgentExecutor.run()` - so changing it takes effect on the next message,
same as the `allow_all` setting below.

- **`general`** (default) - operate this server: inspect, modify, troubleshoot.
- **`bug_bounty`** - authorized security testing / vulnerability research.
  Same tools, same risk classifier, same approval gate as `general` -
  this only changes the system prompt (see
  `app/agent/context.py`'s `BUG_BOUNTY_SYSTEM_PROMPT`) toward
  scope-and-authorization-first methodology (confirm the target is in a
  program's documented scope before active testing, minimal-impact
  proof-of-concept over maximizing damage, no exfiltration beyond what's
  needed to prove a finding, no persistence left on the target) and a
  structured finding write-up at the end (repro steps, impact, suggested
  severity/remediation) instead of the general-mode sysadmin framing.
  Nothing about this mode grants broader tool access or skips approvals
  - it does not turn off the safety rails, it changes what Molly is
  trying to do and how it reasons about risk to a *third party's* asset
  rather than the operator's own server. It can also use a different model
  than general-mode chats - see `GET/PUT/DELETE /settings/bug-bounty-model`
  in Settings below (stored in the DB, not .env, since it's a preference
  someone might change through the app rather than startup config).

Set it at creation or change it later:

```bash
# create a bug-bounty conversation
curl -X POST http://localhost:8000/conversations \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"title": "Acme program - api.acme.com", "mode": "bug_bounty"}'

# switch an existing conversation's mode (merges into metadata, like allow_all)
curl -X PATCH http://localhost:8000/conversations/<id>/settings \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"mode": "bug_bounty"}'

# CLI
molly run --mode bug_bounty "Enumerate subdomains for the Acme program - scope is *.acme.com per their policy"
```

The mobile app's "new chat" picker (see `NewChatSheet`) and the project
detail screen's "Ask Molly about this project" button both use this -
picking a mode there sends the same `mode` field shown above.

## Skills

A skill is reusable, on-demand instructions for a specific kind of task -
deploying a particular stack, following a house style, a recurring
maintenance procedure - the same idea as the SKILL.md convention Claude
itself uses. Skills live on disk as plain files, not in the DB:

```
data/skills/<skill-name>/
    SKILL.md          # required: --- frontmatter (name, description) --- then instructions
    (anything else)   # optional supporting files (scripts, templates)
```

Deliberately filesystem-based rather than a DB table: a skill is meant to
be inspectable/editable the same way any other file on the server is - `scp`,
`git`, a text editor, or Molly's own file tools - not hidden behind an
opaque row. See `app/skills/registry.py` for the (intentionally tiny,
dependency-free) frontmatter parser and path-safety validation.

**How Molly uses them:** every skill's name + description gets appended to
the system prompt as a short index (see `render_skills_index()` in
`app/agent/context.py`) - cheap to include even with many skills, since
it's just enough for Molly to judge relevance, not act on. When a skill
looks relevant to what it's doing, Molly calls the `read_skill(name)` tool
to load the full instructions (and see what other files, if any, live in
that skill's directory) before proceeding. `list_skills()` is also
available as a tool for re-checking mid-task.

```bash
# create a skill
curl -X PUT http://localhost:8000/skills/deploy-rails-app \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{
    "description": "Use when deploying or updating a Ruby on Rails app on this server.",
    "body": "# Steps\n1. bundle install\n2. RAILS_ENV=production rails db:migrate\n3. RAILS_ENV=production rails assets:precompile\n4. systemctl restart myapp"
  }'

# list / inspect / remove
curl http://localhost:8000/skills -H "Authorization: Bearer <token>"
curl http://localhost:8000/skills/deploy-rails-app -H "Authorization: Bearer <token>"
curl -X DELETE http://localhost:8000/skills/deploy-rails-app -H "Authorization: Bearer <token>"
```

Skill names are restricted to lowercase letters, digits, and hyphens
(they become directory names on disk) - `PUT`/`DELETE` reject anything
else with a 400 rather than silently sanitizing it.

The mobile app has a Skills screen (Settings → Skills) for creating,
editing, and deleting skills - it only manages each skill's SKILL.md
(description + instructions), same scope as `PUT /skills/{name}` above;
supporting files in a skill's directory still need to be managed directly
on the server.

## Architecture

```
backend/
├── app/
│   ├── main.py              # FastAPI app
│   ├── config.py            # Settings
│   ├── api/                 # REST + WebSocket
│   ├── agent/               # Agent loop, context, state
│   ├── llm/                 # Provider abstraction
│   ├── tools/               # 17 tool implementations
│   ├── security/            # Paths, risk, permissions
│   ├── storage/             # SQLite, projects, images
│   └── cli.py               # CLI entry point
├── data/
│   ├── projects/            # Project JSON files
│   ├── uploads/             # Image uploads
│   └── app.db               # SQLite database
└── tests/                   # Pytest suite
```

## Deployment on Ubuntu

### Systemd Service

```ini
# /etc/systemd/system/molly.service
[Unit]
Description=Molly Backend
After=network.target

[Service]
Type=exec
User=molly
Group=molly
WorkingDirectory=/var/www/molly/backend
Environment=PATH=/var/www/molly/backend/venv/bin
ExecStart=/var/www/molly/backend/venv/bin/python -m app.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo useradd -r -s /bin/bash -d /var/www/molly molly
sudo chown -R molly:molly /var/www/molly
sudo systemctl daemon-reload
sudo systemctl enable --now molly
```

### Nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name molly.yourdomain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Firewall

```bash
sudo ufw allow 8000/tcp  # Or just 80/443 with nginx
```

## Development

### Run Tests

```bash
cd /var/www/molly/backend
source venv/bin/activate
pytest tests/ -v
```

### Project Structure

See `backend/` structure above. Key modules:

- `app/agent/executor.py` - Core agent loop
- `app/agent/context.py` - Token budgeting, compaction
- `app/security/permissions.py` - Approval state machine
- `app/security/risk.py` - Risk classification
- `app/tools/` - All 17 tool implementations
- `app/llm/openai_compatible.py` - Provider adapter

## Known Limitations

1. **Single Provider**: Only OpenAI-compatible APIs supported
2. **No Streaming Tools**: Tool results returned after completion
3. **Local Only**: No built-in multi-user/auth (add reverse proxy auth)
4. **SQLite**: Not suitable for high-concurrency multi-instance
5. **No Sandbox**: Full server access - OS permissions are the boundary
6. **Image Cleanup**: Manual or time-based, not reference-counted

## License

MIT