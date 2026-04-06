"""Provider subprocess command utilities.

Provides async wrappers for probing and running CLI executables.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import Callable

_log = logging.getLogger(__name__)

# Type for real-time line callbacks
LineCallback = Callable[[str], None]


# Safe env vars for provider subprocesses (includes API keys)
_PROVIDER_ENV_KEYS: list[str] = [
    "PATH", "SYSTEMROOT", "HOME", "TEMP", "TMP",
    "LOCALAPPDATA", "APPDATA", "USERPROFILE",
    "COMSPEC", "PATHEXT",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "ANTHROPIC_BASE_URL",
]


def provider_env(extra: list[str] | None = None) -> dict[str, str]:
    """Build a minimal environment for provider subprocesses."""
    env: dict[str, str] = {}
    for key in _PROVIDER_ENV_KEYS:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    for item in extra or []:
        if "=" in item:
            k, v = item.split("=", 1)
            env[k] = v
    return env


@dataclass
class CommandResult:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""


async def probe_executable(
    executable: str,
    timeout: float = 5.0,
    args: list[str] | None = None,
) -> CommandResult:
    """Check that *executable* is on PATH and responds to *args*."""
    path = shutil.which(executable)
    if path is None:
        raise FileNotFoundError(f"executable not found: {executable}")

    proc = await asyncio.create_subprocess_exec(
        path, *(args or []),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        raw_out, raw_err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"probe timed out for {executable}")

    return CommandResult(
        exit_code=proc.returncode or 0,
        stdout=raw_out.decode(errors="replace"),
        stderr=raw_err.decode(errors="replace"),
    )


async def run_executable_with_stdin(
    executable: str,
    *,
    timeout: float = 120.0,
    cwd: str = "",
    env_extra: list[str] | None = None,
    stdin_data: str = "",
    args: list[str] | None = None,
    on_stderr: LineCallback | None = None,
) -> CommandResult:
    """Run *executable* with optional stdin, capturing stdout/stderr.

    If *on_stderr* is provided, stderr lines are streamed to the callback
    in real time (line-by-line) while still being collected for the final
    CommandResult.
    """
    path = shutil.which(executable)
    if path is None:
        raise FileNotFoundError(f"executable not found: {executable}")

    env = provider_env(env_extra)
    proc = await asyncio.create_subprocess_exec(
        path, *(args or []),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd or None,
        env=env,
    )

    # Feed stdin
    if proc.stdin is not None:
        if stdin_data:
            proc.stdin.write(stdin_data.encode())
        proc.stdin.close()

    if on_stderr is not None:
        # Stream stderr line-by-line while collecting stdout in bulk
        try:
            raw_out, raw_err = await asyncio.wait_for(
                _stream_stderr(proc, on_stderr),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise TimeoutError(f"provider command timed out: {executable}")
    else:
        # Original batch mode
        try:
            raw_out, raw_err = await asyncio.wait_for(
                _batch_communicate(proc),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise TimeoutError(f"provider command timed out: {executable}")

    await proc.wait()

    result = CommandResult(
        exit_code=proc.returncode or 0,
        stdout=raw_out.decode(errors="replace"),
        stderr=raw_err.decode(errors="replace"),
    )
    if proc.returncode and proc.returncode != 0:
        raise subprocess_error(executable, result)
    return result


async def _batch_communicate(proc: asyncio.subprocess.Process) -> tuple[bytes, bytes]:
    """Read stdout and stderr in one shot (original behavior)."""
    raw_out, raw_err = await proc.communicate()
    return raw_out, raw_err


async def _stream_stderr(
    proc: asyncio.subprocess.Process,
    on_stderr: LineCallback,
) -> tuple[bytes, bytes]:
    """Read stdout in bulk, stream stderr line-by-line to callback."""
    stderr_chunks: list[bytes] = []

    async def _read_stderr() -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            stderr_chunks.append(line)
            text = line.decode(errors="replace").rstrip("\n\r")
            if text:
                try:
                    on_stderr(text)
                except Exception:
                    _log.debug("on_stderr callback error", exc_info=True)

    async def _read_stdout() -> bytes:
        assert proc.stdout is not None
        return await proc.stdout.read()

    raw_out, _ = await asyncio.gather(_read_stdout(), _read_stderr())
    return raw_out, b"".join(stderr_chunks)


class SubprocessError(Exception):
    """Raised when a provider subprocess exits non-zero."""

    def __init__(self, executable: str, result: CommandResult) -> None:
        self.executable = executable
        self.result = result
        output = "\n".join(filter(None, [result.stdout.strip(), result.stderr.strip()]))
        super().__init__(output or f"{executable} exited with code {result.exit_code}")


def subprocess_error(executable: str, result: CommandResult) -> SubprocessError:
    return SubprocessError(executable, result)


def minify_json(s: str) -> str:
    """Compact a JSON string to a single line."""
    try:
        return json.dumps(json.loads(s), separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        return s
