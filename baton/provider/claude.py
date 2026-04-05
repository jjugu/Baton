"""Claude CLI adapter."""

from __future__ import annotations

import json
import os

from baton.domain.types import Job, LeaderOutput, ProviderName, RoleName, role_for_task_type
from baton.provider.base import PhaseAdapter
from baton.provider.command import (
    CommandResult,
    minify_json,
    probe_executable,
    run_executable_with_stdin,
    SubprocessError,
)
from baton.provider.errors import (
    classify_command_error,
    invalid_response_error,
    missing_executable_error,
    probe_failed_error,
)
from baton.provider.protocol import (
    build_evaluator_prompt,
    build_leader_prompt,
    build_planner_prompt,
    build_worker_prompt,
    evaluator_schema,
    leader_schema,
    planner_schema,
    worker_schema,
)

_PROBE_TIMEOUT = 5.0
_RUN_TIMEOUT = 1800.0  # 30 min


class ClaudeAdapter:
    """Runs prompts through the Claude CLI (claude -p)."""

    def __init__(self) -> None:
        self._executable = os.environ.get("BATON_CLAUDE_BIN", "claude")

    def name(self) -> ProviderName:
        return ProviderName.CLAUDE

    async def run_leader(self, job: Job) -> str:
        await self._ensure_ready()
        profile = job.role_profiles.profile_for(RoleName.LEADER, job.provider)
        return await self._run_structured(
            job.workspace_dir,
            build_leader_prompt(job),
            leader_schema(),
            profile,
        )

    async def run_planner(self, job: Job) -> str:
        await self._ensure_ready()
        profile = job.role_profiles.profile_for(RoleName.PLANNER, job.provider)
        return await self._run_structured(
            job.workspace_dir,
            build_planner_prompt(job),
            planner_schema(),
            profile,
        )

    async def run_evaluator(self, job: Job) -> str:
        await self._ensure_ready()
        profile = job.role_profiles.profile_for(RoleName.EVALUATOR, job.provider)
        return await self._run_structured(
            job.workspace_dir,
            build_evaluator_prompt(job),
            evaluator_schema(),
            profile,
        )

    async def run_worker(self, job: Job, task: LeaderOutput) -> str:
        await self._ensure_ready()
        profile = job.role_profiles.profile_for(role_for_task_type(task.task_type), job.provider)
        return await self._run_structured(
            job.workspace_dir,
            build_worker_prompt(job, task),
            worker_schema(),
            profile,
        )

    async def _ensure_ready(self) -> None:
        exe = self._executable or "claude"
        try:
            await probe_executable(exe, timeout=_PROBE_TIMEOUT, args=["--version"])
        except FileNotFoundError as exc:
            raise missing_executable_error(self.name(), exe, exc)
        except Exception as exc:
            raise probe_failed_error(self.name(), exe, exc)

    async def _run_structured(self, workspace_dir: str, prompt: str, schema: str, profile) -> str:
        min_schema = minify_json(schema)
        args = [
            "-p",
            "--permission-mode", "dontAsk",
            "--output-format", "json",
            "--json-schema", min_schema,
        ]
        if profile.model:
            args.extend(["--model", profile.model])
        args.append("--no-session-persistence")

        exe = self._executable or "claude"
        try:
            result = await run_executable_with_stdin(
                exe,
                timeout=_RUN_TIMEOUT,
                cwd=workspace_dir,
                stdin_data=prompt,
                args=args,
            )
        except SubprocessError as exc:
            raise classify_command_error(
                self.name(), exe,
                exc.result.stdout, exc.result.stderr, exc,
            )
        except Exception as exc:
            raise classify_command_error(self.name(), exe, "", "", exc)

        output = result.stdout or result.stderr
        if not output:
            raise invalid_response_error(self.name(), exe, "empty claude response")

        extracted = _extract_json_result(output)
        return extracted or output


def _extract_json_result(output: str) -> str:
    """Extract structured payload from Claude JSON envelope."""
    trimmed = output.strip()
    if not trimmed:
        return ""
    try:
        envelope = json.loads(trimmed)
    except json.JSONDecodeError:
        return ""
    if not isinstance(envelope, dict):
        return ""
    for key in ("structured_output", "parsed_output", "result"):
        val = envelope.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            return val.strip()
        # Already a parsed object -- re-serialize
        return json.dumps(val, separators=(",", ":"))
    return ""
