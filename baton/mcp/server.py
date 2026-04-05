"""MCP JSON-RPC 2.0 stdio server for baton.

Reads newline-delimited JSON-RPC 2.0 requests from stdin and writes
responses to stdout. All 18 tools are exposed as baton_* tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from typing import Any, TYPE_CHECKING

from baton.domain.types import (
    ChainGoal,
    ChainStatus,
    Event,
    Job,
    JobChain,
    JobStatus,
    PendingApproval,
    ProviderName,
    RoleOverride,
    RoleProfiles,
    Step,
    StepStatus,
    TokenUsage,
    WorkspaceMode,
    default_role_profiles,
    is_terminal,
)
from baton.orchestrator.service import (
    CreateJobInput,
    EventNotification,
    Service as OrchestratorService,
)

logger = logging.getLogger("baton.mcp")

# ---------------------------------------------------------------------------
# Polling constants
# ---------------------------------------------------------------------------

STATUS_WAIT_POLL_INTERVAL = 2.0  # seconds
STATUS_WAIT_TIMEOUT = 300.0  # 5 minutes
STATUS_WAIT_DEFAULT = 30.0  # default wait timeout


# ---------------------------------------------------------------------------
# JSON-RPC types
# ---------------------------------------------------------------------------

class _RPCError:
    __slots__ = ("code", "message")

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


def _ok_resp(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error_resp(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _text_result(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _json_result(v: Any) -> dict[str, Any]:
    text = json.dumps(v, indent=2, default=str)
    return _text_result(text)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

def _role_override_profile_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "provider": {"type": "string"},
            "model": {"type": "string"},
        },
    }


def _role_overrides_schema() -> dict[str, Any]:
    profile = _role_override_profile_schema()
    return {
        "type": "object",
        "description": (
            "Optional map of role name to {provider, model} overrides. "
            "Supports director-era roles and legacy planner/leader/tester compatibility."
        ),
        "properties": {
            "director": profile,
            "planner": profile,
            "leader": profile,
            "executor": profile,
            "reviewer": profile,
            "tester": profile,
            "evaluator": profile,
        },
    }


def _bounded_int_schema(description: str, minimum: int, maximum: int) -> dict[str, Any]:
    return {
        "type": "integer",
        "description": description,
        "minimum": minimum,
        "maximum": maximum,
    }


def _tool_list() -> list[dict[str, Any]]:
    return [
        {
            "name": "baton_start_job",
            "description": (
                "Start a new Baton job. Pipeline: director -> executor -> "
                "[engine build/test] -> evaluator (code review + gate). "
                "pipeline_mode controls evaluator depth (light/balanced/full)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Natural-language goal for the job (required)"},
                    "provider": {"type": "string", "description": "Provider name: mock | codex | claude", "default": "claude"},
                    "workspace_dir": {"type": "string", "description": "Absolute path of the workspace directory"},
                    "workspace_mode": {"type": "string", "description": "Workspace mode: shared | isolated.", "default": "shared"},
                    "max_steps": {"type": "integer", "description": "Maximum leader steps", "default": 8},
                    "pipeline_mode": {
                        "type": "string",
                        "description": "Pipeline mode: light | balanced | full.",
                        "default": "balanced",
                        "enum": ["light", "balanced", "full"],
                    },
                    "strictness_level": {
                        "type": "string",
                        "description": "Evaluator judgment aggressiveness: lenient | normal | strict.",
                        "default": "normal",
                    },
                    "ambition_level": {
                        "type": "string",
                        "description": "Worker autonomy scope.",
                        "default": "medium",
                        "enum": ["low", "medium", "high", "extreme", "custom"],
                    },
                    "ambition_text": {"type": "string", "description": "Custom ambition text."},
                    "context_mode": {
                        "type": "string",
                        "description": "Leader context mode: full | summary | minimal | auto.",
                        "default": "full",
                    },
                    "role_overrides": _role_overrides_schema(),
                    "pre_build_commands": {
                        "type": "array",
                        "description": "Commands to run before engine verification.",
                        "items": {"type": "string"},
                    },
                    "engine_build_cmd": {"type": "string", "description": "Override engine build command."},
                    "engine_test_cmd": {"type": "string", "description": "Override engine test command."},
                    "prompt_overrides": {
                        "type": "object",
                        "description": "Per-role prompt overrides. Keys: director, executor, evaluator.",
                    },
                },
                "required": ["goal"],
            },
        },
        {
            "name": "baton_start_chain",
            "description": "Start a sequential chain of jobs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workspace_dir": {"type": "string", "description": "Absolute path of the workspace directory"},
                    "goals": {
                        "type": "array",
                        "description": "Sequential goals to execute",
                        "items": {
                            "type": "object",
                            "properties": {
                                "goal": {"type": "string", "description": "Natural-language goal"},
                                "provider": {"type": "string", "description": "Provider name"},
                                "strictness_level": {"type": "string", "default": "normal"},
                                "ambition_level": {"type": "string", "default": "medium", "enum": ["low", "medium", "high", "extreme", "custom"]},
                                "ambition_text": {"type": "string"},
                                "context_mode": {"type": "string", "default": "full"},
                                "max_steps": {"type": "integer", "default": 8},
                                "role_overrides": _role_overrides_schema(),
                                "pre_build_commands": {"type": "array", "items": {"type": "string"}},
                                "engine_build_cmd": {"type": "string"},
                                "engine_test_cmd": {"type": "string"},
                            },
                            "required": ["goal"],
                        },
                    },
                },
                "required": ["goals", "workspace_dir"],
            },
        },
        {
            "name": "baton_list_jobs",
            "description": "List all jobs.",
            "inputSchema": {"type": "object"},
        },
        {
            "name": "baton_status",
            "description": (
                "Get job status. wait=true blocks until terminal state "
                "(default 30s, wait_timeout=0 for 5min)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID"},
                    "wait": {"type": "boolean", "description": "Wait for terminal state", "default": False},
                    "wait_timeout": {"type": "integer", "description": "Wait timeout in seconds", "default": 30},
                    "compact": {"type": "boolean", "description": "Return compact status", "default": True},
                },
                "required": ["job_id"],
            },
        },
        {
            "name": "baton_chain_status",
            "description": "Get chain status. wait=true blocks until terminal state.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "chain_id": {"type": "string", "description": "Chain ID"},
                    "wait": {"type": "boolean", "default": False},
                    "wait_timeout": {"type": "integer", "default": 30},
                },
                "required": ["chain_id"],
            },
        },
        {
            "name": "baton_pause_chain",
            "description": "Pause a sequential job chain after the current goal completes.",
            "inputSchema": {
                "type": "object",
                "properties": {"chain_id": {"type": "string", "description": "Chain ID"}},
                "required": ["chain_id"],
            },
        },
        {
            "name": "baton_resume_chain",
            "description": "Resume a paused sequential job chain.",
            "inputSchema": {
                "type": "object",
                "properties": {"chain_id": {"type": "string", "description": "Chain ID"}},
                "required": ["chain_id"],
            },
        },
        {
            "name": "baton_cancel_chain",
            "description": "Cancel a sequential job chain.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "chain_id": {"type": "string", "description": "Chain ID"},
                    "reason": {"type": "string", "description": "Cancellation reason"},
                },
                "required": ["chain_id"],
            },
        },
        {
            "name": "baton_skip_chain_goal",
            "description": "Skip the current goal in a chain and advance to the next.",
            "inputSchema": {
                "type": "object",
                "properties": {"chain_id": {"type": "string", "description": "Chain ID"}},
                "required": ["chain_id"],
            },
        },
        {
            "name": "baton_events",
            "description": "Get recent events for a job.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID"},
                    "last_n": {"type": "integer", "description": "Number of recent events", "default": 10},
                },
                "required": ["job_id"],
            },
        },
        {
            "name": "baton_artifacts",
            "description": "Get artifact paths produced by a job.",
            "inputSchema": {
                "type": "object",
                "properties": {"job_id": {"type": "string", "description": "Job ID"}},
                "required": ["job_id"],
            },
        },
        {
            "name": "baton_approve",
            "description": "Approve a pending approval on a job.",
            "inputSchema": {
                "type": "object",
                "properties": {"job_id": {"type": "string", "description": "Job ID"}},
                "required": ["job_id"],
            },
        },
        {
            "name": "baton_reject",
            "description": "Reject a pending approval on a job.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID"},
                    "reason": {"type": "string", "description": "Rejection reason"},
                },
                "required": ["job_id"],
            },
        },
        {
            "name": "baton_retry",
            "description": "Retry a blocked or failed job.",
            "inputSchema": {
                "type": "object",
                "properties": {"job_id": {"type": "string", "description": "Job ID"}},
                "required": ["job_id"],
            },
        },
        {
            "name": "baton_cancel",
            "description": "Cancel a job.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID"},
                    "reason": {"type": "string", "description": "Cancellation reason"},
                },
                "required": ["job_id"],
            },
        },
        {
            "name": "baton_resume",
            "description": (
                "Resume a blocked job from its current state. "
                "Supply extra_steps (1-20) for max_steps_exceeded resumes."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID"},
                    "extra_steps": _bounded_int_schema(
                        "Optional max_steps extension for blocked resumes.", 1, 20,
                    ),
                },
                "required": ["job_id"],
            },
        },
        {
            "name": "baton_steer",
            "description": "Inject a supervisor directive into a running job.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID"},
                    "message": {"type": "string", "description": "Supervisor directive"},
                },
                "required": ["job_id", "message"],
            },
        },
        {
            "name": "baton_diff",
            "description": "Show the current git diff for a job workspace.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID"},
                    "pathspec": {"type": "string", "description": "Optional git pathspec"},
                },
                "required": ["job_id"],
            },
        },
    ]


# ---------------------------------------------------------------------------
# Compact status view
# ---------------------------------------------------------------------------

def _compact_job_status(job: Job) -> dict[str, Any]:
    steps = []
    for s in job.steps:
        cs: dict[str, Any] = {
            "index": s.index,
            "target": s.target,
            "task_type": s.task_type,
            "status": s.status,
            "summary": s.summary,
            "started_at": str(s.started_at),
        }
        if s.error_reason:
            cs["error_reason"] = s.error_reason
        steps.append(cs)

    events = job.events
    if len(events) > 10:
        events = events[-10:]
    event_dicts = [e.model_dump(mode="json") for e in events]

    result: dict[str, Any] = {
        "id": job.id,
        "status": job.status,
        "provider": job.provider,
        "current_step": job.current_step,
        "max_steps": job.max_steps,
        "steps": steps,
        "events": event_dicts,
        "created_at": str(job.created_at),
        "updated_at": str(job.updated_at),
    }
    if job.summary:
        result["summary"] = job.summary
    if job.blocked_reason:
        result["blocked_reason"] = job.blocked_reason
    if job.failure_reason:
        result["failure_reason"] = job.failure_reason
    if job.leader_context_summary:
        result["leader_context_summary"] = job.leader_context_summary
    if job.pending_approval is not None:
        result["pending_approval"] = job.pending_approval.model_dump(mode="json")
    if job.chain_id:
        result["chain_id"] = job.chain_id
        result["chain_goal_index"] = job.chain_goal_index
    result["token_usage"] = job.token_usage.model_dump(mode="json")
    return result


# ---------------------------------------------------------------------------
# Argument helpers
# ---------------------------------------------------------------------------

def _str_arg(args: dict[str, Any], key: str) -> str:
    v = args.get(key, "")
    return v if isinstance(v, str) else ""


def _str_arg_default(args: dict[str, Any], key: str, default: str) -> str:
    v = _str_arg(args, key).strip()
    return v if v else default


def _require_str_arg(args: dict[str, Any], key: str) -> str:
    v = _str_arg(args, key).strip()
    if not v:
        raise ValueError(f"{key} is required")
    return v


def _int_arg_default(args: dict[str, Any], key: str, default: int) -> int:
    v = args.get(key)
    if isinstance(v, (int, float)):
        n = int(v)
        return n if n > 0 else default
    return default


def _int_arg(args: dict[str, Any], key: str) -> tuple[int, bool]:
    v = args.get(key)
    if isinstance(v, (int, float)):
        n = int(v)
        return n, True
    return 0, False


def _bool_arg_default(args: dict[str, Any], key: str, default: bool) -> bool:
    v = args.get(key)
    return v if isinstance(v, bool) else default


def _str_slice_arg(args: dict[str, Any], key: str) -> list[str] | None:
    raw = args.get(key)
    if not isinstance(raw, list):
        return None
    out = [s for s in raw if isinstance(s, str)]
    return out or None


def _parse_role_overrides(raw: dict[str, Any]) -> dict[str, RoleOverride]:
    result: dict[str, RoleOverride] = {}
    for role, val in raw.items():
        if not isinstance(val, dict):
            continue
        ro = RoleOverride()
        p = val.get("provider")
        if isinstance(p, str) and p:
            ro.provider = ProviderName(p)
        m = val.get("model")
        if isinstance(m, str):
            ro.model = m
        result[role] = ro
    return result


def _parse_prompt_overrides(args: dict[str, Any]) -> dict[str, str] | None:
    raw = args.get("prompt_overrides")
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(v, str) and v.strip():
            out[k] = v
    return out or None


def _validate_pipeline_mode(mode: str) -> None:
    if mode not in ("light", "balanced", "full"):
        raise ValueError("pipeline_mode must be one of light, balanced, or full")


def _validate_workspace_dir(path: str) -> None:
    if not path or not path.strip():
        return
    if not os.path.isabs(path):
        raise ValueError(f"workspace_dir must be an absolute path: {path}")
    if not os.path.isdir(path):
        raise ValueError(f"workspace_dir does not exist: {path}")


def _optional_extra_steps(args: dict[str, Any]) -> int:
    raw = args.get("extra_steps")
    if raw is None:
        return 0
    value, ok = _int_arg({"extra_steps": raw}, "extra_steps")
    if not ok:
        raise ValueError("extra_steps must be an integer")
    if value < 1 or value > 20:
        raise ValueError("extra_steps must be between 1 and 20")
    return value


def _status_wait_duration(args: dict[str, Any], wait: bool) -> float:
    if not wait:
        return 0.0
    seconds, ok = _int_arg(args, "wait_timeout")
    if not ok:
        return min(STATUS_WAIT_TIMEOUT, STATUS_WAIT_DEFAULT)
    if seconds == 0:
        return STATUS_WAIT_TIMEOUT
    if seconds > 0:
        return float(seconds)
    return STATUS_WAIT_DEFAULT


# ---------------------------------------------------------------------------
# Terminal state helpers
# ---------------------------------------------------------------------------

_TERMINAL_JOB_STATUSES = frozenset({"done", "failed", "blocked", "cancelled"})
_TERMINAL_CHAIN_STATUSES = frozenset({
    ChainStatus.DONE.value,
    ChainStatus.FAILED.value,
    ChainStatus.CANCELLED.value,
})

_MIGHT_PRODUCE_TERMINAL = frozenset({
    "job_blocked", "job_failed", "job_completed", "job_cancelled", "job_interrupted",
})
_CLEARS_TERMINAL_STATE = frozenset({
    "job_created", "job_resumed", "job_retry_requested", "job_approved",
})


def _is_terminal_job_status(status: str | JobStatus) -> bool:
    return str(status) in _TERMINAL_JOB_STATUSES


def _is_terminal_chain_status(status: str) -> bool:
    return status in _TERMINAL_CHAIN_STATUSES


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class Server:
    """MCP stdio JSON-RPC 2.0 server exposing baton tools."""

    def __init__(self, service: OrchestratorService) -> None:
        self._service = service
        self._lock = asyncio.Lock()
        self._writer = sys.stdout
        self._done = asyncio.Event()
        self._last_terminal: dict[str, str] = {}
        self._terminal_lock = asyncio.Lock()

    # -- output --

    def _write_message(self, msg: Any) -> None:
        try:
            data = json.dumps(msg, default=str)
        except (TypeError, ValueError) as exc:
            logger.error("marshal error: %s", exc)
            return
        self._write_raw_line(data)

    def _write_raw_line(self, data: str) -> None:
        try:
            self._writer.write(data + "\n")
            self._writer.flush()
        except OSError as exc:
            logger.error("write error: %s", exc)

    def _send_notification(self, method: str, params: Any) -> None:
        self._write_message({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        })

    # -- event relay --

    async def _listen_events(self) -> None:
        ch = self._service.event_queue
        if ch is None:
            return
        while not self._done.is_set():
            try:
                event = await asyncio.wait_for(ch.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except Exception:
                return
            self._handle_event_notification(event)

    def _handle_event_notification(self, event: EventNotification) -> None:
        self._send_notification("notifications/message", {
            "level": "info",
            "logger": "baton",
            "data": {
                "job_id": event.job_id,
                "kind": event.kind,
                "message": event.message,
            },
        })

        if event.kind in _CLEARS_TERMINAL_STATE:
            self._last_terminal.pop(event.job_id, None)
        if event.kind in _MIGHT_PRODUCE_TERMINAL:
            asyncio.create_task(self._await_and_send_terminal(event.job_id))

    async def _await_and_send_terminal(self, job_id: str) -> None:
        try:
            deadline = asyncio.get_event_loop().time() + 3.0
            while asyncio.get_event_loop().time() < deadline:
                try:
                    job = await self._service.get(job_id)
                except Exception:
                    await asyncio.sleep(0.025)
                    continue
                if _is_terminal_job_status(job.status):
                    summary = job.summary or job.blocked_reason or job.failure_reason or ""
                    extra = _isolated_worktree_extra(job)
                    self._send_job_terminal(job.id, str(job.status), summary, extra)
                    return
                await asyncio.sleep(0.025)
        except Exception as exc:
            logger.warning("terminal notification error for job %s: %s", job_id, exc)

    def _send_job_terminal(
        self,
        job_id: str,
        status: str,
        summary: str,
        extra: dict[str, Any] | None,
    ) -> None:
        signature = f"{status}\x00{summary}"
        if self._last_terminal.get(job_id) == signature:
            return
        self._last_terminal[job_id] = signature

        payload: dict[str, Any] = {
            "job_id": job_id,
            "status": status,
            "summary": summary,
        }
        if extra:
            payload.update(extra)
        self._send_notification("notifications/job_terminal", payload)

    # -- main loop --

    async def run(self) -> None:
        """Run the MCP server, reading from stdin until EOF."""
        listener = asyncio.create_task(self._listen_events())
        try:
            if sys.platform == "win32":
                # Windows ProactorEventLoop does not support connect_read_pipe
                # on stdin. Use a thread-based reader instead.
                await self._run_stdin_threaded()
            else:
                loop = asyncio.get_event_loop()
                reader = asyncio.StreamReader()
                transport, _ = await loop.connect_read_pipe(
                    lambda: asyncio.StreamReaderProtocol(reader),
                    sys.stdin,
                )
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    resp = await self._handle_message(text)
                    if resp is not None:
                        self._write_message(resp)
        finally:
            self._done.set()
            listener.cancel()
            try:
                await listener
            except asyncio.CancelledError:
                pass

    async def _run_stdin_threaded(self) -> None:
        """Read stdin lines via a background thread (Windows-safe)."""
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.buffer.readline)
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            resp = await self._handle_message(text)
            if resp is not None:
                self._write_message(resp)

    def run_sync(self) -> None:
        """Synchronous entry point for CLI usage."""
        asyncio.run(self.run())

    # -- message routing --

    async def _handle_message(self, raw: str) -> dict[str, Any] | None:
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            return _error_resp(None, -32700, "parse error")

        req_id = req.get("id")
        method = req.get("method", "")

        # Notifications have no id and need no response
        if req_id is None and method == "notifications/initialized":
            return None
        if req_id is None and method.startswith("notifications/"):
            return None

        if method == "initialize":
            return self._handle_initialize(req_id)
        if method == "initialized":
            return None
        if method == "tools/list":
            return _ok_resp(req_id, {"tools": _tool_list()})
        if method == "tools/call":
            return await self._handle_tool_call(req)
        return _error_resp(req_id, -32601, f"method not found: {method}")

    def _handle_initialize(self, req_id: Any) -> dict[str, Any]:
        return _ok_resp(req_id, {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "baton", "version": "0.1.0"},
            "capabilities": {
                "tools": {},
                "logging": {},
            },
        })

    async def _handle_tool_call(self, req: dict[str, Any]) -> dict[str, Any]:
        req_id = req.get("id")
        params = req.get("params", {})
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}

        dispatch = {
            "baton_start_job": self._tool_start_job,
            "baton_start_chain": self._tool_start_chain,
            "baton_list_jobs": self._tool_list_jobs,
            "baton_status": self._tool_status,
            "baton_chain_status": self._tool_chain_status,
            "baton_pause_chain": self._tool_pause_chain,
            "baton_resume_chain": self._tool_resume_chain,
            "baton_cancel_chain": self._tool_cancel_chain,
            "baton_skip_chain_goal": self._tool_skip_chain_goal,
            "baton_events": self._tool_events,
            "baton_artifacts": self._tool_artifacts,
            "baton_approve": self._tool_approve,
            "baton_reject": self._tool_reject,
            "baton_retry": self._tool_retry,
            "baton_cancel": self._tool_cancel,
            "baton_resume": self._tool_resume,
            "baton_steer": self._tool_steer,
            "baton_diff": self._tool_diff,
        }

        handler = dispatch.get(name)
        if handler is None:
            return _error_resp(req_id, -32602, f"unknown tool: {name}")

        try:
            result = await handler(arguments)
            return _ok_resp(req_id, result)
        except Exception as exc:
            return _ok_resp(req_id, _text_result(f"error: {exc}"))

    # -- tool implementations --

    async def _tool_start_job(self, args: dict[str, Any]) -> dict[str, Any]:
        goal = _str_arg(args, "goal").strip()
        if not goal:
            raise ValueError("goal is required")

        provider = ProviderName(_str_arg_default(args, "provider", "claude"))
        workspace_dir = _str_arg(args, "workspace_dir")
        workspace_mode = _str_arg_default(args, "workspace_mode", WorkspaceMode.SHARED.value)
        max_steps = _int_arg_default(args, "max_steps", 8)
        pipeline_mode = _str_arg_default(args, "pipeline_mode", "balanced")
        strictness_level = _str_arg_default(args, "strictness_level", "normal")
        ambition_level = _str_arg_default(args, "ambition_level", "medium")
        ambition_text = _str_arg(args, "ambition_text")
        context_mode = _str_arg_default(args, "context_mode", "full")

        _validate_workspace_dir(workspace_dir)
        _validate_pipeline_mode(pipeline_mode)

        role_overrides = None
        ro_raw = args.get("role_overrides")
        if isinstance(ro_raw, dict):
            role_overrides = _parse_role_overrides(ro_raw)

        pre_build_cmds = _str_slice_arg(args, "pre_build_commands")
        engine_build_cmd = _str_arg(args, "engine_build_cmd")
        engine_test_cmd = _str_arg(args, "engine_test_cmd")
        prompt_overrides = _parse_prompt_overrides(args)

        input_data = CreateJobInput(
            goal=goal,
            provider=provider,
            workspace_dir=workspace_dir,
            workspace_mode=workspace_mode,
            max_steps=max_steps,
            pipeline_mode=pipeline_mode,
            strictness_level=strictness_level,
            ambition_level=ambition_level,
            ambition_text=ambition_text,
            context_mode=context_mode,
            role_profiles=default_role_profiles(provider),
            role_overrides=role_overrides,
            pre_build_commands=pre_build_cmds,
            engine_build_cmd=engine_build_cmd,
            engine_test_cmd=engine_test_cmd,
            prompt_overrides=prompt_overrides,
        )

        job = await self._service.start_async(input_data)
        return _json_result(job.model_dump(mode="json"))

    async def _tool_start_chain(self, args: dict[str, Any]) -> dict[str, Any]:
        workspace_dir = _require_str_arg(args, "workspace_dir")
        _validate_workspace_dir(workspace_dir)

        raw_goals = args.get("goals")
        if not isinstance(raw_goals, list) or not raw_goals:
            raise ValueError("goals is required")

        goals: list[ChainGoal] = []
        for i, raw_goal in enumerate(raw_goals):
            if not isinstance(raw_goal, dict):
                raise ValueError(f"goals[{i}] must be an object")
            g = _str_arg(raw_goal, "goal").strip()
            if not g:
                raise ValueError(f"goals[{i}].goal is required")

            provider_str = _str_arg(raw_goal, "provider")
            provider = ProviderName(provider_str) if provider_str else ProviderName.CLAUDE

            ro = None
            ro_raw = raw_goal.get("role_overrides")
            if isinstance(ro_raw, dict):
                ro = _parse_role_overrides(ro_raw)

            goal = ChainGoal(
                goal=g,
                provider=provider,
                strictness_level=_str_arg_default(raw_goal, "strictness_level", "normal"),
                ambition_level=_str_arg_default(raw_goal, "ambition_level", "medium"),
                ambition_text=_str_arg(raw_goal, "ambition_text"),
                context_mode=_str_arg_default(raw_goal, "context_mode", "full"),
                max_steps=_int_arg_default(raw_goal, "max_steps", 8),
                role_overrides=ro or {},
                pre_build_commands=_str_slice_arg(raw_goal, "pre_build_commands") or [],
                engine_build_cmd=_str_arg(raw_goal, "engine_build_cmd"),
                engine_test_cmd=_str_arg(raw_goal, "engine_test_cmd"),
            )
            po = _parse_prompt_overrides(raw_goal)
            if po:
                goal.prompt_overrides = po
            goals.append(goal)

        chain = await self._service.start_chain(goals, workspace_dir)
        return _json_result({"chain_id": chain.id})

    async def _tool_list_jobs(self, args: dict[str, Any]) -> dict[str, Any]:
        jobs = await self._service.list_jobs()
        return _json_result([j.model_dump(mode="json") for j in jobs])

    async def _tool_status(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = _require_str_arg(args, "job_id")
        wait = _bool_arg_default(args, "wait", False)
        timeout = _status_wait_duration(args, wait)

        job = await self._get_job_status(job_id, wait, timeout)
        compact = _bool_arg_default(args, "compact", True)
        if compact:
            return _json_result(_compact_job_status(job))
        return _json_result(job.model_dump(mode="json"))

    async def _get_job_status(self, job_id: str, wait: bool, timeout: float) -> Job:
        if not wait:
            return await self._service.get(job_id)

        deadline = asyncio.get_event_loop().time() + timeout
        last_job: Job | None = None
        last_err: Exception | None = None

        while True:
            try:
                job = await self._service.get(job_id)
                last_job = job
                last_err = None
                if _is_terminal_job_status(job.status):
                    return job
            except Exception as exc:
                last_err = exc

            now = asyncio.get_event_loop().time()
            if now >= deadline:
                if last_job is not None:
                    return last_job
                raise last_err or ValueError(f"job not found: {job_id}")

            await asyncio.sleep(STATUS_WAIT_POLL_INTERVAL)

    async def _tool_chain_status(self, args: dict[str, Any]) -> dict[str, Any]:
        chain_id = _require_str_arg(args, "chain_id")
        wait = _bool_arg_default(args, "wait", False)
        timeout = _status_wait_duration(args, wait)

        chain = await self._get_chain_status(chain_id, wait, timeout)
        return _json_result(chain.model_dump(mode="json"))

    async def _get_chain_status(self, chain_id: str, wait: bool, timeout: float) -> JobChain:
        if not wait:
            return await self._service.get_chain(chain_id)

        deadline = asyncio.get_event_loop().time() + timeout
        last_chain: JobChain | None = None
        last_err: Exception | None = None

        while True:
            try:
                chain = await self._service.get_chain(chain_id)
                last_chain = chain
                last_err = None
                if _is_terminal_chain_status(chain.status):
                    return chain
            except Exception as exc:
                last_err = exc

            now = asyncio.get_event_loop().time()
            if now >= deadline:
                if last_chain is not None:
                    return last_chain
                raise last_err or ValueError(f"chain not found: {chain_id}")

            await asyncio.sleep(STATUS_WAIT_POLL_INTERVAL)

    async def _tool_pause_chain(self, args: dict[str, Any]) -> dict[str, Any]:
        chain_id = _require_str_arg(args, "chain_id")
        chain = await self._service.pause_chain(chain_id)
        return _json_result(chain.model_dump(mode="json"))

    async def _tool_resume_chain(self, args: dict[str, Any]) -> dict[str, Any]:
        chain_id = _require_str_arg(args, "chain_id")
        chain = await self._service.resume_chain(chain_id)
        return _json_result(chain.model_dump(mode="json"))

    async def _tool_cancel_chain(self, args: dict[str, Any]) -> dict[str, Any]:
        chain_id = _require_str_arg(args, "chain_id")
        reason = _str_arg(args, "reason")
        chain = await self._service.cancel_chain(chain_id, reason)
        return _json_result(chain.model_dump(mode="json"))

    async def _tool_skip_chain_goal(self, args: dict[str, Any]) -> dict[str, Any]:
        chain_id = _require_str_arg(args, "chain_id")
        chain = await self._service.skip_chain_goal(chain_id)
        return _json_result(chain.model_dump(mode="json"))

    async def _tool_events(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = _require_str_arg(args, "job_id")
        last_n = _int_arg_default(args, "last_n", 10)

        job = await self._service.get(job_id)
        events = job.events
        if last_n > 0 and len(events) > last_n:
            events = events[-last_n:]
        return _json_result([e.model_dump(mode="json") for e in events])

    async def _tool_artifacts(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = _require_str_arg(args, "job_id")
        job = await self._service.get(job_id)

        all_artifacts: list[str] = list(job.planning_artifacts)
        for step in job.steps:
            all_artifacts.extend(step.artifacts)
        return _json_result(all_artifacts)

    async def _tool_approve(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = _require_str_arg(args, "job_id")
        # Get snapshot before async approve
        job = await self._service.get(job_id)
        # Run approve in background (it re-enters runLoop which blocks)
        asyncio.create_task(self._bg_approve(job_id))
        return _json_result({
            "job_id": job.id,
            "status": str(job.status),
            "message": "approval submitted; job is resuming in background",
        })

    async def _bg_approve(self, job_id: str) -> None:
        try:
            await self._service.approve(job_id)
        except Exception as exc:
            logger.error("Approve failed for job %s: %s", job_id, exc)

    async def _tool_reject(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = _require_str_arg(args, "job_id")
        reason = _str_arg(args, "reason")
        job = await self._service.reject(job_id, reason)
        return _json_result(job.model_dump(mode="json"))

    async def _tool_retry(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = _require_str_arg(args, "job_id")
        job = await self._service.get(job_id)
        asyncio.create_task(self._bg_retry(job_id))
        return _json_result({
            "job_id": job.id,
            "status": str(job.status),
            "message": "retry submitted; job is resuming in background",
        })

    async def _bg_retry(self, job_id: str) -> None:
        try:
            await self._service.retry(job_id)
        except Exception as exc:
            logger.error("Retry failed for job %s: %s", job_id, exc)

    async def _tool_cancel(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = _require_str_arg(args, "job_id")
        reason = _str_arg(args, "reason")
        job = await self._service.cancel(job_id, reason)
        return _json_result(job.model_dump(mode="json"))

    async def _tool_resume(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = _require_str_arg(args, "job_id")
        extra_steps = _optional_extra_steps(args)
        job = await self._service.get(job_id)
        asyncio.create_task(self._bg_resume(job_id, extra_steps))
        snapshot: dict[str, Any] = {
            "job_id": job.id,
            "status": str(job.status),
            "message": "resume submitted; job is resuming in background",
        }
        if extra_steps > 0:
            snapshot["extra_steps"] = extra_steps
        return _json_result(snapshot)

    async def _bg_resume(self, job_id: str, extra_steps: int) -> None:
        try:
            await self._service.resume(job_id, extra_steps=extra_steps)
        except Exception as exc:
            logger.error("Resume failed for job %s: %s", job_id, exc)

    async def _tool_steer(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = _str_arg(args, "job_id").strip()
        message = _str_arg(args, "message").strip()
        if not job_id or not message:
            raise ValueError("job_id and message are required")
        job = await self._service.steer(job_id, message)
        return _json_result({
            "status": "steered",
            "leader_context_summary": job.leader_context_summary,
            "supervisor_directive": job.supervisor_directive,
        })

    async def _tool_diff(self, args: dict[str, Any]) -> dict[str, Any]:
        job_id = _require_str_arg(args, "job_id")
        job = await self._service.get(job_id)

        workspace_dir = (job.workspace_dir or "").strip()
        if not workspace_dir:
            raise ValueError(f"workspace path is missing for job: {job_id}")
        if not os.path.isdir(workspace_dir):
            raise ValueError(f"workspace path not found: {workspace_dir}")

        # Verify git worktree
        try:
            subprocess.run(
                ["git", "-C", workspace_dir, "rev-parse", "--is-inside-work-tree"],
                capture_output=True, check=True, timeout=10,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise ValueError(f"workspace is not a git worktree: {workspace_dir}")

        git_args = ["git", "-C", workspace_dir, "diff", "HEAD"]
        pathspec = _str_arg(args, "pathspec").strip()
        if pathspec:
            if ".." in pathspec:
                raise ValueError(f"pathspec must not contain '..': {pathspec!r}")
            if pathspec.startswith(":"):
                raise ValueError(f"pathspec must not start with ':': {pathspec!r}")
            git_args.extend(["--", pathspec])

        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}
        try:
            result = subprocess.run(
                git_args, capture_output=True, text=True, timeout=10, env=env,
            )
        except subprocess.TimeoutExpired:
            raise ValueError("git diff timed out after 10s")

        if result.returncode != 0:
            raise ValueError(f"git diff failed: {result.stderr.strip()}")

        output = result.stdout.strip()
        if not output:
            return _text_result("no changes")
        return _text_result(output)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _isolated_worktree_extra(job: Job) -> dict[str, Any] | None:
    if job.workspace_mode != WorkspaceMode.ISOLATED.value:
        return None

    extra: dict[str, Any] = {
        "workspace_mode": job.workspace_mode,
        "workspace_dir": job.workspace_dir,
    }
    if job.requested_workspace_dir:
        extra["requested_workspace_dir"] = job.requested_workspace_dir

    if job.workspace_dir:
        try:
            result = subprocess.run(
                ["git", "-C", job.workspace_dir, "diff", "--stat"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                stat = result.stdout.strip()
                if stat:
                    extra["diff_stat"] = stat
        except (subprocess.SubprocessError, OSError):
            pass

    return extra
