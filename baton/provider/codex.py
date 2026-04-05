"""Codex CLI adapter.

Ported from gorchera/internal/provider/codex.go.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from baton.domain.types import Job, LeaderOutput, ProviderName, RoleName, role_for_task_type
from baton.provider.base import PhaseAdapter
from baton.provider.command import (
    CommandResult,
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


def _is_codex_model(model: str) -> bool:
    normalized = model.strip().lower()
    if not normalized:
        return True
    if normalized in ("opus", "sonnet", "haiku"):
        return False
    return normalized.startswith("gpt")


class CodexAdapter:
    """Runs prompts through the Codex CLI (codex exec)."""

    def __init__(self) -> None:
        self._executable = os.environ.get("BATON_CODEX_BIN", "codex")

    def name(self) -> ProviderName:
        return ProviderName.CODEX

    async def run_leader(self, job: Job) -> str:
        await self._ensure_ready()
        profile = job.role_profiles.profile_for(RoleName.LEADER, job.provider)
        return await self._run_structured(
            job.workspace_dir,
            build_leader_prompt(job),
            leader_schema(),
            profile.model,
            profile.effort,
        )

    async def run_planner(self, job: Job) -> str:
        await self._ensure_ready()
        profile = job.role_profiles.profile_for(RoleName.PLANNER, job.provider)
        return await self._run_structured(
            job.workspace_dir,
            build_planner_prompt(job),
            planner_schema(),
            profile.model,
            profile.effort,
        )

    async def run_evaluator(self, job: Job) -> str:
        await self._ensure_ready()
        profile = job.role_profiles.profile_for(RoleName.EVALUATOR, job.provider)
        return await self._run_structured(
            job.workspace_dir,
            build_evaluator_prompt(job),
            evaluator_schema(),
            profile.model,
            profile.effort,
        )

    async def run_worker(self, job: Job, task: LeaderOutput) -> str:
        await self._ensure_ready()
        profile = job.role_profiles.profile_for(role_for_task_type(task.task_type), job.provider)
        return await self._run_structured(
            job.workspace_dir,
            build_worker_prompt(job, task),
            worker_schema(),
            profile.model,
            profile.effort,
        )

    async def _ensure_ready(self) -> None:
        exe = self._executable or "codex"
        try:
            await probe_executable(exe, timeout=_PROBE_TIMEOUT, args=["--version"])
        except FileNotFoundError as exc:
            raise missing_executable_error(self.name(), exe, exc)
        except Exception as exc:
            raise probe_failed_error(self.name(), exe, exc)

    async def _run_structured(
        self,
        workspace_dir: str,
        prompt: str,
        schema: str,
        model: str,
        effort: str,
    ) -> str:
        # Write schema to a temp file
        base_dir = workspace_dir or tempfile.gettempdir()
        schema_dir = tempfile.mkdtemp(dir=base_dir, prefix="baton-codex-schema-")
        schema_path = os.path.join(schema_dir, "schema.json")
        Path(schema_path).write_text(schema)

        output_dir = tempfile.mkdtemp(dir=base_dir, prefix="baton-codex-")
        output_path = os.path.join(output_dir, "result.json")

        try:
            args = self._build_args(workspace_dir, schema_path, output_path, model, effort, "--ephemeral")
            try:
                await run_executable_with_stdin(
                    self._executable,
                    timeout=_RUN_TIMEOUT,
                    cwd=workspace_dir,
                    stdin_data=prompt,
                    args=args,
                )
            except SubprocessError as exc:
                if _should_retry_with_fresh(exc):
                    args = self._build_args(workspace_dir, schema_path, output_path, model, effort, "--fresh")
                    await run_executable_with_stdin(
                        self._executable,
                        timeout=_RUN_TIMEOUT,
                        cwd=workspace_dir,
                        stdin_data=prompt,
                        args=args,
                    )
                else:
                    raise classify_command_error(
                        self.name(), self._executable,
                        exc.result.stdout, exc.result.stderr, exc,
                    )
            except Exception as exc:
                raise classify_command_error(
                    self.name(), self._executable, "", "", exc,
                )

            try:
                data = Path(output_path).read_text()
            except OSError as exc:
                raise invalid_response_error(self.name(), self._executable, "failed to read codex output", exc)
            return data
        finally:
            _rmtree_safe(schema_dir)
            _rmtree_safe(output_dir)

    def _build_args(
        self,
        workspace_dir: str,
        schema_path: str,
        output_path: str,
        model: str,
        effort: str,
        session_flag: str,
    ) -> list[str]:
        args = [
            "exec", session_flag,
            "--skip-git-repo-check",
            "-s", "workspace-write",
            "--output-schema", schema_path,
            "-o", output_path,
            "-C", workspace_dir or ".",
            "-",  # read prompt from stdin
        ]
        if model.strip() and _is_codex_model(model):
            args.extend(["--model", model.strip()])
        if effort.strip():
            args.extend(["--effort", effort.strip()])
        return args


def _should_retry_with_fresh(exc: SubprocessError) -> bool:
    msg = str(exc).lower()
    return "--ephemeral" in msg and ("unexpected argument" in msg or "unknown option" in msg)


def _rmtree_safe(path: str) -> None:
    try:
        import shutil as _shutil
        _shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass
