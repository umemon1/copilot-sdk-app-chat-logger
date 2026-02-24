# Copilot Chat Logger

A terminal-based Copilot Chat client that logs every prompt, response, tool call, and error to PostgreSQL using GitHub Copilot SDK hooks. Includes a web dashboard for Product Managers to review developer sessions.

## Architecture

```
Developer Terminal (chat.py)
  └─ github-copilot-sdk (CopilotClient + hooks)
       ├─ asyncpg → PostgreSQL (logs all interactions)
       └─ JSON-RPC → Copilot CLI → GitHub Copilot API

PM Dashboard (FastAPI :8081)
  └─ reads from PostgreSQL
```

## Prerequisites

- **Python 3.11+**
- **Docker & Docker Compose** (for PostgreSQL + dashboard)
- **GitHub Copilot CLI** installed and authenticated:
  ```bash
  # Install Copilot CLI (see https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli)
  copilot --version   # verify it's installed
  ```

## Quick Start

### 1. Start PostgreSQL + Dashboard

```bash
docker compose up -d
```

This starts:
- **PostgreSQL** on port 5432 (auto-runs schema.sql)
- **Dashboard** on http://localhost:8081/dashboard/

### 2. Set up Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Start chatting (logged)

```bash
python chat.py
```

Options:
```bash
python chat.py --model gpt-4.1          # specify model
python chat.py --developer alice         # override developer name
```

### 4. View logs

Open http://localhost:8081/dashboard/ in your browser.

## What Gets Logged

| SDK Hook                | Data Captured                    | DB Table      |
|------------------------|----------------------------------|---------------|
| `onSessionStart`       | Developer, timestamp, cwd, model | `sessions`    |
| `onUserPromptSubmitted`| Full prompt text                 | `prompt_logs` |
| `onPreToolUse`         | Tool name, arguments             | `tool_logs`   |
| `onPostToolUse`        | Tool name, result                | `tool_logs`   |
| `onErrorOccurred`      | Error message, context           | `error_logs`  |
| `onSessionEnd`         | End reason, duration             | `sessions`    |

Response text and duration are captured when the streamed response completes (`session.idle` event).

## Project Structure

```
copilot-chat-logger/
├── chat.py                  # Terminal chat app (SDK + hooks)
├── db.py                    # Async PostgreSQL connection + insert functions
├── schema.sql               # Database table definitions
├── requirements.txt         # Python dependencies
├── docker-compose.yml       # PostgreSQL + dashboard services
├── Dockerfile               # Dashboard container image
├── hooks/
│   ├── copilot-hook.js      # VS Code hook handler
│   └── settings.json        # Hook configuration
├── dashboard/
│   ├── app.py               # FastAPI dashboard + log ingestion API
│   ├── static/
│   │   └── style.css
│   └── templates/
│       ├── base.html         # Jinja2 base layout (Pico CSS)
│       ├── sessions.html     # Sessions list page
│       └── detail.html       # Session detail page
└── README.md
```

## Configuration

| Environment Variable | Default                                              | Description         |
|---------------------|------------------------------------------------------|---------------------|
| `DATABASE_URL`      | `postgresql://copilot:copilot@localhost:5432/copilot_logger` | PostgreSQL connection |

## Dashboard Features

- **Sessions list** — paginated, filterable by developer
- **Session detail** — full conversation (prompts + responses displayed as chat bubbles), tool call timeline, error log
- **Stats header** — total sessions, unique developers, total prompts, average response time
- **Log ingestion API** — `POST /api/logs` for future VS Code extension integration

## VS Code Integration (Copilot Chat Hook System)

The logger integrates with VS Code Copilot Chat via its shell-command hook system. When Copilot Chat runs in VS Code, every session start, prompt, tool call, and session end fires a hook that posts to the dashboard API.

### How it works

```
VS Code (Copilot Chat)
  └─ Hook system reads hooks/settings.json
       └─ For each hook event → runs: node copilot-hook.js <HookType>
            └─ Receives JSON on stdin → maps to dashboard format
                 └─ POST http://localhost:8081/api/logs
```

### Setup

1. **Start the dashboard** (if not already running):
   ```bash
   cd ~/copilot-chat-logger
   docker compose up -d
   ```

2. **Configure hooks** — the hook configuration is in `hooks/settings.json` inside this repo. It registers the hook commands that fire on each Copilot Chat event.

3. **Use Copilot Chat in VS Code** — open VS Code, start a Copilot Chat session, and all interactions are automatically logged.

4. **View logs** at http://localhost:8081/dashboard/

### Hook Configuration

The hooks are configured in `hooks/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      { "matcher": "", "hooks": [{ "type": "command", "command": "node /path/to/copilot-hook.js SessionStart" }] }
    ],
    "UserPromptSubmit": [
      { "matcher": "", "hooks": [{ "type": "command", "command": "node /path/to/copilot-hook.js UserPromptSubmit" }] }
    ],
    "PreToolUse": [
      { "matcher": "*", "hooks": [{ "type": "command", "command": "node /path/to/copilot-hook.js PreToolUse" }] }
    ],
    "PostToolUse": [
      { "matcher": "*", "hooks": [{ "type": "command", "command": "node /path/to/copilot-hook.js PostToolUse" }] }
    ],
    "Stop": [
      { "matcher": "", "hooks": [{ "type": "command", "command": "node /path/to/copilot-hook.js Stop" }] }
    ],
    "SessionEnd": [
      { "matcher": "", "hooks": [{ "type": "command", "command": "node /path/to/copilot-hook.js SessionEnd" }] }
    ]
  }
}
```

Replace `/path/to/copilot-hook.js` with the actual path (e.g., `~/copilot-chat-logger/hooks/copilot-hook.js`).

**Location:**
- `hooks/settings.json` — included in this repo, project-specific

### Hook Types Captured

| Hook Event          | Data Logged                          | Dashboard Type |
|---------------------|--------------------------------------|---------------|
| `SessionStart`      | Developer, source, working directory | `session_start` |
| `UserPromptSubmit`  | Full prompt text                     | `prompt`        |
| `PreToolUse`        | Tool name, input arguments           | `tool` (pre)    |
| `PostToolUse`       | Tool name, input, response           | `tool` (post)   |
| `PostToolUseFailure`| Tool name, error message             | `error`         |
| `Stop`              | Stop reason                          | `session_end`   |
| `SessionEnd`        | End reason                           | `session_end`   |
| `Notification`      | Title, message                       | `prompt`        |

### Environment Variables

| Variable              | Default                          | Description                    |
|-----------------------|----------------------------------|--------------------------------|
| `COPILOT_LOGGER_URL`  | `http://localhost:8081/api/logs`  | Dashboard API endpoint         |
