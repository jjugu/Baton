"""Async subprocess runner.

Ported from gorchera/internal/runtime/runner.go.
Uses asyncio.create_subprocess_exec instead of os/exec.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time as _time
from datetime import datetime, timezone

from baton.runtime.policy import Policy, PolicyError, default_policy
from baton.runtime.types import Category, Request, Result

# Safe env vars propagated to subprocesses (secrets excluded)
_SAFE_ENV_KEYS: list[str] = [
    "PATH", "SYSTEMROOT", "HOME", "TEMP", "TMP",
    "LOCALAPPDATA", "APPDATA", "USERPROFILE",
    "COMSPEC", "PATHEXT",
    "GOCACHE", "GOPATH", "GOROOT", "GOPROXY",
    "GONOSUMCHECK", "GONOSUMDB", "GONOPROXY", "GOFLAGS",
    "GOTMPDIR", "CGO_ENABLED",
]


def _minimal_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in _SAFE_ENV_KEYS:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    return env


class NotAllowedError(Exception):
    """The runtime policy rejected the command."""


class Runner:
    """Runs commands as subprocesses with policy enforcement and output limits."""

    def __init__(
        self,
        policy: Policy | None = None,
        *,
        default_timeout: float = 300.0,
        default_max_output: int = 1 << 20,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self.policy = policy or default_policy()
        self.default_timeout = default_timeout
        self.default_max_output = default_max_output
        self.extra_env = extra_env or {}

    async def run(self, req: Request) -> Result:
        timeout = req.timeout_seconds if req.timeout_seconds > 0 else self.default_timeout
        max_output = req.max_output_bytes if req.max_output_bytes > 0 else self.default_max_output

        try:
            self.policy.allows(req.category, req.command)
        except PolicyError as exc:
            raise NotAllowedError(str(exc)) from exc

        env = _minimal_env()
        env.update(self.extra_env)
        for item in req.env:
            if "=" in item:
                k, v = item.split("=", 1)
                env[k] = v

        started_at = datetime.now(timezone.utc)
        try:
            proc = await asyncio.create_subprocess_exec(
                req.command, *req.args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=req.dir or None,
                env=env,
            )
        except FileNotFoundError as exc:
            raise NotAllowedError(f"command not found: {req.command}") from exc

        timed_out = False
        try:
            raw_stdout, raw_stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            raw_stdout, raw_stderr = await proc.communicate()

        finished_at = datetime.now(timezone.utc)
        duration = (finished_at - started_at).total_seconds()

        stdout_text, trunc_out = _limit_output(raw_stdout, max_output)
        stderr_text, trunc_err = _limit_output(raw_stderr, max_output)

        exit_code = proc.returncode or 0
        if timed_out and exit_code == 0:
            exit_code = 1

        return Result(
            category=req.category,
            command=req.command,
            args=list(req.args),
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
            timed_out=timed_out,
            truncated_stdout=trunc_out,
            truncated_stderr=trunc_err,
        )


def _limit_output(data: bytes, limit: int) -> tuple[str, bool]:
    """Decode and truncate output to *limit* bytes."""
    if len(data) <= limit:
        return data.decode(errors="replace"), False
    return data[:limit].decode(errors="replace"), True
