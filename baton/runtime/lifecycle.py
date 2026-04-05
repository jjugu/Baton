"""Process lifecycle manager -- start/stop/watch long-running processes.

Uses asyncio instead of goroutines + sync.Mutex.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from baton.runtime.policy import Policy, PolicyError, default_policy
from baton.runtime.runner import NotAllowedError, _minimal_env
from baton.runtime.types import (
    Category,
    ProcessHandle,
    ProcessState,
    Request,
    StartRequest,
)


class ProcessNotFoundError(Exception):
    pass


class ProcessManager:
    """Manages long-running subprocess lifecycles."""

    def __init__(
        self,
        policy: Policy | None = None,
        *,
        extra_env: dict[str, str] | None = None,
        default_timeout: float = 300.0,
    ) -> None:
        self.policy = policy or default_policy()
        self.extra_env = extra_env or {}
        self.default_timeout = default_timeout
        self._lock = asyncio.Lock()
        self._processes: dict[int, _ProcessRecord] = {}

    async def start(self, req: StartRequest) -> ProcessHandle:
        timeout = req.timeout_seconds if req.timeout_seconds > 0 else self.default_timeout
        log_dir = req.log_dir or tempfile.gettempdir()

        try:
            self.policy.allows(req.category, req.command)
        except PolicyError as exc:
            raise NotAllowedError(str(exc)) from exc

        Path(log_dir).mkdir(parents=True, exist_ok=True)
        log_name = _process_log_name(req.name, req.command)
        log_path = os.path.join(log_dir, log_name)
        log_file = open(log_path, "wb")

        env = _minimal_env()
        env.update(self.extra_env)
        for item in req.env:
            if "=" in item:
                k, v = item.split("=", 1)
                env[k] = v

        started_at = datetime.now(timezone.utc)
        proc = await asyncio.create_subprocess_exec(
            req.command, *req.args,
            stdout=log_file,
            stderr=log_file,
            cwd=req.dir or None,
            env=env,
        )

        handle = ProcessHandle(
            pid=proc.pid,
            name=req.name,
            category=req.category,
            command=req.command,
            args=list(req.args),
            port=req.port,
            log_path=log_path,
            state=ProcessState.RUNNING,
            started_at=started_at,
            running=True,
        )

        record = _ProcessRecord(
            handle=handle,
            process=proc,
            log_file=log_file,
            done=asyncio.Event(),
        )

        async with self._lock:
            self._processes[proc.pid] = record

        # Watch in background
        asyncio.create_task(self._watch(proc.pid, record))
        return handle

    async def stop(self, pid: int) -> ProcessHandle:
        record = await self._get_record(pid)
        async with self._lock:
            record.stop_requested = True
        record.process.kill()
        await record.done.wait()
        return await self.status(pid)

    async def status(self, pid: int) -> ProcessHandle:
        record = await self._get_record(pid)
        async with self._lock:
            return record.handle.model_copy()

    async def list_all(self) -> list[ProcessHandle]:
        async with self._lock:
            handles = [r.handle.model_copy() for r in self._processes.values()]
        handles.sort(key=lambda h: (h.started_at, h.pid))
        return handles

    async def find_by_name(self, name: str) -> list[ProcessHandle]:
        needle = _normalize_name(name)
        if not needle:
            return []
        async with self._lock:
            handles = [
                r.handle.model_copy()
                for r in self._processes.values()
                if _normalize_name(r.handle.name) == needle
            ]
        handles.sort(key=lambda h: (h.started_at, h.pid))
        return handles

    async def find_by_category(self, category: Category) -> list[ProcessHandle]:
        async with self._lock:
            handles = [
                r.handle.model_copy()
                for r in self._processes.values()
                if r.handle.category == category
            ]
        handles.sort(key=lambda h: (h.started_at, h.pid))
        return handles

    async def wait(self, pid: int) -> ProcessHandle:
        record = await self._get_record(pid)
        await record.done.wait()
        return await self.status(pid)

    async def _get_record(self, pid: int) -> _ProcessRecord:
        async with self._lock:
            record = self._processes.get(pid)
            if record is None:
                raise ProcessNotFoundError(f"process {pid} not found")
            return record

    async def _watch(self, pid: int, record: _ProcessRecord) -> None:
        returncode = await record.process.wait()
        finished_at = datetime.now(timezone.utc)
        exit_code = returncode if returncode is not None else -1

        async with self._lock:
            stop_requested = record.stop_requested

        if stop_requested:
            state = ProcessState.STOPPED
        elif returncode != 0:
            state = ProcessState.FAILED
        else:
            state = ProcessState.EXITED

        async with self._lock:
            record.handle.finished_at = finished_at
            record.handle.exit_code = exit_code
            record.handle.state = state
            record.handle.running = False
            if returncode != 0 and state == ProcessState.FAILED:
                record.handle.error = f"exit code {exit_code}"
            if record.log_file is not None:
                record.log_file.close()
                record.log_file = None
            record.done.set()


class _ProcessRecord:
    __slots__ = ("handle", "process", "log_file", "done", "stop_requested")

    def __init__(
        self,
        handle: ProcessHandle,
        process: asyncio.subprocess.Process,
        log_file: object,
        done: asyncio.Event,
    ) -> None:
        self.handle = handle
        self.process = process
        self.log_file = log_file
        self.done = done
        self.stop_requested = False


def _process_log_name(name: str, command: str) -> str:
    base = name.strip() or os.path.basename(command)
    base = _sanitize_component(base)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S.%f")[:21]
    return f"{base}-{ts}.log"


def _sanitize_component(value: str) -> str:
    value = value.strip()
    if not value:
        return "process"
    return value.replace(os.sep, "-").replace(" ", "-").replace(":", "-")


def _normalize_name(value: str) -> str:
    value = value.strip().lower()
    return value.replace(os.sep, "-").replace("/", "-").replace("\\", "-").replace(" ", "-").replace(":", "-")
