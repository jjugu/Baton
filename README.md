# Baton

Python asyncio multi-agent orchestration engine.  
Director, Executor, Evaluator 3-agent pipeline for automated code generation and verification.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Claude Code MCP Integration](#claude-code-mcp-integration)
- [CLI Reference](#cli-reference)
- [HTTP API Server](#http-api-server)
- [MCP Tools](#mcp-tools)
- [Providers](#providers)
- [Configuration](#configuration)
- [Job Chains](#job-chains)
- [Harness (Process Management)](#harness-process-management)
- [Web Dashboard](#web-dashboard)
- [Development](#development)
- [License](#license)

---

## Overview

Baton orchestrates multiple AI agents in a structured pipeline to plan, implement, and verify code changes. Each job flows through a strict sequence:

```
Director (planning) -> Leader (decisions) -> Executor (implementation) -> Evaluator (gate)
```

The Evaluator gate is inviolable -- a job cannot reach `done` status without explicit evaluator approval. This prevents incomplete or incorrect work from being marked as complete.

Key features:

- **3-agent pipeline** with strict evaluator gate
- **3 providers**: Claude (Anthropic), Codex (OpenAI), Mock (testing)
- **Per-role model configuration** (e.g., opus for reasoning, sonnet for execution)
- **Job chains** for sequential multi-step workflows
- **Workspace isolation** via git worktrees
- **MCP server** for Claude Code integration
- **HTTP API** with SSE event streaming
- **Web dashboard** for real-time monitoring
- **CLI** with 22 subcommands

---

## Architecture

```
+-------------------------------------------------------------------+
|                        Orchestrator (Service)                      |
|                                                                    |
|  QUEUED -> STARTING -> PLANNING -> RUNNING -> DONE / FAILED       |
|                                                                    |
|  +------------+    +----------+    +-----------+    +-----------+  |
|  |  Director  | -> |  Leader  | -> |  Executor | -> | Evaluator |  |
|  | (planner)  |    | (decide) |    |  (worker) |    |  (gate)   |  |
|  +------------+    +----------+    +-----------+    +-----------+  |
|                         |                                          |
|                    [Engine Build/Test] (optional)                   |
+-------------------------------------------------------------------+
        |                    |                    |
   StateStore          ArtifactStore        ProcessManager
   (JSON files)        (.baton/artifacts)   (subprocess)
```

### Pipeline Phases

| Phase | Role | Model Tier | Purpose |
|-------|------|-----------|---------|
| Planning | Director | Heavy (opus) | Analyze goal, produce sprint contract with acceptance criteria |
| Leadership | Leader | Heavy (opus) | Decide next action: run_worker, run_system, complete, fail |
| Execution | Executor | Light (sonnet) | Implement tasks, produce artifacts |
| Verification | Evaluator | Heavy (opus) | Gate check: all criteria met before marking done |

### Core Invariants

- **Evaluator gate**: `done` status is never reached without passing `evaluateCompletion()`
- **No full log forwarding**: Agents pass artifact paths + summaries only, never entire conversation logs
- **Executor isolation**: Executors do not spawn workers; parallelism is managed by the orchestrator
- **Approval enforcement**: Steps requiring human approval cannot auto-pass

---

## Requirements

- **Python 3.12+**
- **git** (for workspace isolation mode)
- One of the following AI providers:
  - Anthropic API key (`ANTHROPIC_API_KEY`) for Claude provider
  - OpenAI API key for Codex provider
  - No key needed for Mock provider (testing)

---

## Installation

### From GitHub

```bash
pip install git+https://github.com/jjugu/Baton.git
```

### From source (development)

```bash
git clone https://github.com/jjugu/Baton.git
cd Baton
pip install -e ".[dev]"
```

### Verify installation

```bash
baton --help
```

---

## Quick Start

### 1. Start a job with Mock provider (no API key needed)

```bash
baton run \
  --goal "add a hello world endpoint to the API" \
  --provider mock \
  --max-steps 4
```

### 2. Start a job with Claude provider

```bash
export ANTHROPIC_API_KEY="sk-ant-..."

baton run \
  --goal "implement user authentication middleware" \
  --provider claude \
  --tech-stack python \
  --max-steps 10 \
  --constraints "use JWT tokens,don't modify existing tests" \
  --done "all tests pass,middleware is applied to protected routes"
```

### 3. Check job status

```bash
# Single job
baton status --job <job-id>

# All jobs
baton status --all
```

### 4. View events

```bash
baton events --job <job-id>
```

### 5. View artifacts

```bash
baton artifacts --job <job-id>
```

---

## Claude Code MCP Integration

Baton can run as an MCP (Model Context Protocol) server, exposing 18 tools directly inside Claude Code.

### Setup

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "baton": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "baton", "mcp"],
      "cwd": "/path/to/your/workspace"
    }
  }
}
```

Or if installed via pip:

```json
{
  "mcpServers": {
    "baton": {
      "type": "stdio",
      "command": "baton",
      "args": ["mcp"]
    }
  }
}
```

### Verify connection

Run `/mcp` in Claude Code. You should see `baton` listed as connected with 18 tools available.

### Usage in Claude Code

Once connected, Claude Code can use baton tools directly:

```
# Start a job
baton_start_job(goal="implement feature X", provider="claude")

# Check status (wait for completion)
baton_status(job_id="...", wait=true)

# View diff
baton_diff(job_id="...")
```

---

## CLI Reference

### Job Control

| Command | Description | Key Options |
|---------|------------|-------------|
| `baton run` | Start a new job | `--goal` (required), `--provider`, `--tech-stack`, `--max-steps`, `--constraints`, `--done`, `--workspace-mode`, `--strictness`, `--profiles-file` |
| `baton status` | Get job status | `--job <id>` or `--all` |
| `baton events` | Get job events | `--job <id>` |
| `baton artifacts` | Get artifact paths | `--job <id>` |
| `baton resume` | Resume blocked job | `--job <id>` |
| `baton approve` | Approve pending step | `--job <id>` |
| `baton reject` | Reject pending step | `--job <id>`, `--reason` |
| `baton retry` | Retry failed/blocked job | `--job <id>` |
| `baton cancel` | Cancel a job | `--job <id>`, `--reason` |

### Views

| Command | Description |
|---------|------------|
| `baton verification` | Verification view (checks, contracts) |
| `baton planning` | Planning view (scope, steps, criteria) |
| `baton evaluator` | Evaluator view (gate decision, score) |
| `baton profile` | Role profile configuration view |

### Server

| Command | Description | Key Options |
|---------|------------|-------------|
| `baton serve` | Start HTTP API server | `--addr` (default: 127.0.0.1:8080), `--workspace`, `--recover` |
| `baton stop` | Graceful shutdown | `--workspace` or `--addr` |
| `baton stream` | Stream SSE events (client) | `--job <id>`, `--server` |
| `baton mcp` | Start MCP stdio server | `--recover` |

### Harness

| Command | Description | Key Options |
|---------|------------|-------------|
| `baton harness-start` | Start a process | `--command` (required), `--job`, `--name`, `--timeout-seconds` |
| `baton harness-view` | View harness state | `--job <id>` |
| `baton harness-list` | List processes | `--job` (optional scope) |
| `baton harness-status` | Get process status | `--pid` (required) |
| `baton harness-stop` | Stop a process | `--pid` (required) |

---

## HTTP API Server

Start the API server:

```bash
baton serve --addr 127.0.0.1:8080 --workspace /path/to/repo
```

### Endpoints

**Jobs**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/jobs` | List all jobs |
| `POST` | `/jobs` | Start a new job |
| `GET` | `/jobs/{id}` | Get job details |
| `POST` | `/jobs/{id}/resume` | Resume blocked job |
| `POST` | `/jobs/{id}/approve` | Approve pending step |
| `POST` | `/jobs/{id}/reject` | Reject pending step |
| `POST` | `/jobs/{id}/retry` | Retry job |
| `POST` | `/jobs/{id}/cancel` | Cancel job |
| `POST` | `/jobs/{id}/steer` | Inject supervisor directive |
| `GET` | `/jobs/{id}/events` | List events |
| `GET` | `/jobs/{id}/events/stream` | SSE event stream |
| `GET` | `/jobs/{id}/artifacts` | Get artifacts |
| `GET` | `/jobs/{id}/verification` | Verification view |
| `GET` | `/jobs/{id}/planning` | Planning view |
| `GET` | `/jobs/{id}/evaluator` | Evaluator view |
| `GET` | `/jobs/{id}/profile` | Profile view |

**Chains**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/chains` | List all chains |
| `POST` | `/chains` | Start a chain |
| `GET` | `/chains/{id}` | Get chain status |

**Harness**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/harness/processes` | List global processes |
| `POST` | `/harness/processes` | Start a process |
| `GET` | `/harness/processes/{pid}` | Get process |
| `POST` | `/harness/processes/{pid}/stop` | Stop process |
| `GET` | `/jobs/{id}/harness/processes` | List job processes |
| `POST` | `/jobs/{id}/harness/processes` | Start job process |

**Admin**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Health check |
| `GET` | `/` | Web dashboard |
| `POST` | `/admin/shutdown` | Graceful shutdown |
| `POST` | `/admin/workspace` | Switch workspace |
| `GET` | `/admin/workspace` | Get current workspace |

### Example: Start a job via API

```bash
curl -X POST http://localhost:8080/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "add logging middleware",
    "provider": "claude",
    "tech_stack": "python",
    "max_steps": 8
  }'
```

### Example: Stream events via SSE

```bash
curl -N http://localhost:8080/jobs/<job-id>/events/stream
```

---

## MCP Tools

18 tools are exposed via the MCP server:

### Job Management

| Tool | Description |
|------|-------------|
| `baton_start_job` | Start a new job with full configuration |
| `baton_status` | Get job status (supports `wait=true` for blocking) |
| `baton_events` | Get recent events (`last_n` configurable) |
| `baton_artifacts` | Get artifact paths |
| `baton_resume` | Resume blocked job (`extra_steps` 1-20) |
| `baton_retry` | Retry failed/blocked job |
| `baton_list_jobs` | List all jobs |
| `baton_diff` | Show git diff for job workspace |

### Chain Management

| Tool | Description |
|------|-------------|
| `baton_start_chain` | Start sequential chain of jobs |
| `baton_chain_status` | Get chain status (supports `wait`) |
| `baton_pause_chain` | Pause after current goal completes |
| `baton_resume_chain` | Resume paused chain |
| `baton_cancel_chain` | Cancel chain |
| `baton_skip_chain_goal` | Skip current goal, advance to next |

### Approvals & Control

| Tool | Description |
|------|-------------|
| `baton_approve` | Approve pending approval |
| `baton_reject` | Reject pending approval |
| `baton_cancel` | Cancel a job |
| `baton_steer` | Inject supervisor directive into running job |

### baton_start_job Parameters

```
goal            (required) Job objective
provider        "mock" | "codex" | "claude" (default: "claude")
workspace_dir   Working directory (default: cwd)
workspace_mode  "shared" | "isolated" (default: "shared")
max_steps       Maximum execution steps (default: 8)
pipeline_mode   "light" | "balanced" | "full" (default: "balanced")
strictness_level "lenient" | "normal" | "strict" (default: "normal")
ambition_level  "low" | "medium" | "high" | "extreme" | "custom" (default: "medium")
role_overrides  Per-role provider/model overrides
prompt_overrides Per-role prompt overrides (director, executor, evaluator)
engine_build_cmd Build command (e.g., "go build ./...")
engine_test_cmd  Test command (e.g., "pytest")
pre_build_commands Commands to run before build
```

---

## Providers

### Claude (Anthropic)

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
baton run --goal "..." --provider claude
```

Default role profiles:
- **Heavy reasoning** (director, planner, leader, evaluator): `claude-opus`
- **Execution** (executor, reviewer, tester): `claude-sonnet`

### Codex (OpenAI)

```bash
baton run --goal "..." --provider codex
```

### Mock (Testing)

No API key required. Returns deterministic responses for all pipeline phases.

```bash
baton run --goal "..." --provider mock
```

### Custom Role Profiles

Create a JSON file with per-role provider/model overrides:

```json
{
  "director":  { "provider": "claude", "model": "opus" },
  "planner":   { "provider": "claude", "model": "opus" },
  "leader":    { "provider": "claude", "model": "opus" },
  "executor":  { "provider": "claude", "model": "sonnet" },
  "reviewer":  { "provider": "claude", "model": "sonnet" },
  "tester":    { "provider": "claude", "model": "sonnet" },
  "evaluator": { "provider": "claude", "model": "opus" }
}
```

```bash
baton run --goal "..." --provider claude --profiles-file profiles.json
```

---

## Configuration

### Workspace Structure

Baton creates a `.baton/` directory in your workspace:

```
.baton/
├── state/
│   ├── jobs/           # Job state (JSON per job)
│   │   └── {job-id}.json
│   └── chains/         # Chain state
│       └── {chain-id}.json
├── artifacts/          # Job artifacts
│   └── {job-id}/
│       ├── step-00-planning.json
│       ├── step-01-runtime_result.json
│       └── ...
├── leases/             # Job heartbeat leases
│   └── {job-id}.lease
└── serve.pid           # API server PID file
```

### Workspace Modes

**Shared** (default): All jobs work in the same directory. Simple, but jobs can interfere with each other.

```bash
baton run --goal "..." --workspace-mode shared
```

**Isolated**: Each job gets its own git worktree on a dedicated branch. Changes are isolated until merged.

```bash
baton run --goal "..." --workspace-mode isolated
```

### Job Status Lifecycle

```
queued -> starting -> planning -> running <-> waiting_leader
                                         <-> waiting_worker
                                         -> blocked (needs approval)
                                         -> done (evaluator passed)
                                         -> failed (evaluator rejected / max retries)
```

| Status | Description |
|--------|-------------|
| `queued` | Job created, not yet started |
| `starting` | Initializing workspace and provider |
| `planning` | Director is analyzing goal and creating sprint contract |
| `running` | Active execution loop |
| `waiting_leader` | Waiting for leader decision |
| `waiting_worker` | Waiting for executor to complete task |
| `blocked` | Requires human approval or intervention |
| `done` | Evaluator gate passed, job complete |
| `failed` | Evaluator rejected or unrecoverable error |

---

## Job Chains

Chains execute multiple goals sequentially, passing context between them:

### Via MCP

```
baton_start_chain(goals=[
  "scaffold the project structure",
  "implement the core API endpoints",
  "add comprehensive test coverage"
], provider="claude")
```

### Chain Operations

| Operation | Description |
|-----------|-------------|
| `baton_chain_status` | Get chain progress |
| `baton_pause_chain` | Pause after current goal |
| `baton_resume_chain` | Resume paused chain |
| `baton_cancel_chain` | Cancel entire chain |
| `baton_skip_chain_goal` | Skip current goal, advance |

### Chain Status Values

| Status | Description |
|--------|-------------|
| `running` | Chain is executing |
| `paused` | Paused, will resume on command |
| `done` | All goals completed |
| `failed` | A goal failed |
| `cancelled` | Manually cancelled |

---

## Harness (Process Management)

The harness system manages subprocesses (build servers, test runners, etc.) scoped to jobs or globally:

```bash
# Start a process
baton harness-start --command "npm run dev" --name "dev-server" --port 3000

# List running processes
baton harness-list

# Stop a process
baton harness-stop --pid 12345
```

Job-scoped processes are automatically tracked with the job lifecycle:

```bash
# Start process scoped to a job
baton harness-start --job <job-id> --command "pytest --watch" --name "test-watcher"

# View job harness state
baton harness-view --job <job-id>
```

---

## Web Dashboard

The built-in web dashboard provides real-time monitoring:

```bash
baton serve --addr 127.0.0.1:8080
```

Open `http://127.0.0.1:8080` in your browser to view:

- Active jobs and their status
- Event streams
- Step progress and artifacts
- Approval requests

---

## Development

### Setup

```bash
git clone https://github.com/jjugu/Baton.git
cd Baton
pip install -e ".[dev]"
```

### Run tests

```bash
pytest
```

### Project structure

```
baton/
├── cli.py                  # CLI entry point (Typer, 22 commands)
├── domain/
│   ├── types.py            # Core types, enums, models (Pydantic v2)
│   └── errors.py           # Domain exceptions
├── orchestrator/
│   ├── service.py          # Main state machine & orchestration loop
│   ├── planning.py         # Sprint contract generation
│   ├── evaluator.py        # Evaluator gate logic
│   ├── verification.py     # Verification contracts
│   ├── workspace.py        # Git worktree management
│   ├── job_runtime.py      # Job leases & heartbeats
│   └── parallel.py         # Parallel worker planning
├── provider/
│   ├── base.py             # Adapter protocol (interface)
│   ├── protocol.py         # Prompt schemas & JSON contracts
│   ├── registry.py         # Provider registry & session manager
│   ├── claude.py           # Claude (Anthropic) adapter
│   ├── codex.py            # Codex (OpenAI) adapter
│   └── mock.py             # Mock adapter (testing)
├── mcp/
│   └── server.py           # MCP JSON-RPC stdio server (18 tools)
├── api/
│   ├── server.py           # FastAPI application
│   ├── routes.py           # HTTP endpoints
│   └── views.py            # View builders
├── store/
│   ├── state_store.py      # JSON file persistence
│   └── artifact_store.py   # Artifact materialization
├── runtime/
│   ├── lifecycle.py        # Process manager
│   ├── runner.py           # Command execution
│   └── policy.py           # Security policies
└── web/
    ├── index.html           # Dashboard UI
    ├── app.js
    └── style.css
```

### Dependencies

| Package | Purpose |
|---------|---------|
| pydantic >= 2.0 | Data validation & serialization |
| fastapi >= 0.110 | HTTP API framework |
| uvicorn >= 0.30 | ASGI server |
| typer >= 0.12 | CLI framework |
| sse-starlette >= 2.0 | Server-Sent Events |

### Dev dependencies

| Package | Purpose |
|---------|---------|
| pytest >= 8.0 | Test framework |
| pytest-asyncio >= 0.24 | Async test support |
| httpx >= 0.27 | HTTP client for API tests |

---

## License

MIT
