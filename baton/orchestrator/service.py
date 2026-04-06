"""Orchestrator service -- core loop, job lifecycle, chain management.

The evaluator gate (evaluateCompletion) is NEVER bypassed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from baton.domain.errors import JobNotFoundError, ChainNotFoundError
from baton.domain.types import (
    ChainContext,
    ChainGoal,
    ChainGoalStatus,
    ChainStatus,
    EvaluatorReport,
    Event,
    Job,
    JobChain,
    JobStatus,
    LeaderOutput,
    PendingApproval,
    ProviderName,
    RoleProfiles,
    RoleName,
    SprintContract,
    Step,
    StepStatus,
    TokenUsage,
    WorkerOutput,
    default_role_profiles,
    is_terminal,
    normalize_ambition_level,
    normalize_pipeline_mode,
    role_for_task_type,
)
from baton.provider.errors import ErrorAction, ProviderError
from baton.provider.registry import SessionManager
from baton.store.artifact_store import ArtifactStore
from baton.store.state_store import StateStore
from baton.orchestrator.automated_check import run_automated_checks
from baton.orchestrator.evaluator import (
    apply_evaluator_job_state,
    deterministic_evaluator_report,
    merge_evaluator_report,
    validate_evaluator_report,
)
from baton.orchestrator.job_runtime import (
    JobLease,
    new_service_instance_id,
    run_heartbeat,
)
from baton.orchestrator.parallel import build_worker_plans, WorkerPlan
from baton.orchestrator.planning import (
    build_planning_artifact,
    build_sprint_contract,
    planning_markdown,
    validate_planning_artifact,
)
from baton.orchestrator.verification import (
    InternalVerificationContract,
    build_persisted_verification_contract,
    build_verification_contract,
    resolve_verification_contract,
    verification_contract_path,
    verification_contract_prompt,
)
from baton.orchestrator.workspace import (
    collect_workspace_diff_summary,
    prepare_workspace_dir,
    validate_workspace_dir,
)
from baton.runtime.runner import Runner
from baton.runtime.lifecycle import ProcessManager
from baton.runtime.policy import default_policy

_log = logging.getLogger(__name__)

PROVIDER_RETRY_LIMIT = 3
PROVIDER_RETRY_BASE_DELAY = 0.25
MAX_RESUME_EXTRA_STEPS = 20
SCHEMA_RETRY_MAX = 2


class EventNotification:
    __slots__ = ("job_id", "kind", "message")

    def __init__(self, job_id: str, kind: str, message: str) -> None:
        self.job_id = job_id
        self.kind = kind
        self.message = message


class CreateJobInput:
    def __init__(
        self,
        *,
        goal: str = "",
        tech_stack: str = "",
        workspace_dir: str = "",
        workspace_mode: str = "",
        constraints: list[str] | None = None,
        done_criteria: list[str] | None = None,
        provider: ProviderName = ProviderName.MOCK,
        role_profiles: RoleProfiles | None = None,
        role_overrides: dict[str, Any] | None = None,
        max_steps: int = 8,
        pipeline_mode: str = "",
        strictness_level: str = "",
        ambition_level: str = "",
        ambition_text: str = "",
        context_mode: str = "",
        pre_build_commands: list[str] | None = None,
        engine_build_cmd: str = "",
        engine_test_cmd: str = "",
        prompt_overrides: dict[str, str] | None = None,
        chain_id: str = "",
        chain_goal_index: int = 0,
    ) -> None:
        self.goal = goal
        self.tech_stack = tech_stack
        self.workspace_dir = workspace_dir
        self.workspace_mode = workspace_mode
        self.constraints = constraints or []
        self.done_criteria = done_criteria or []
        self.provider = provider
        self.role_profiles = role_profiles or RoleProfiles()
        self.role_overrides = role_overrides or {}
        self.max_steps = max_steps
        self.pipeline_mode = pipeline_mode
        self.strictness_level = strictness_level
        self.ambition_level = ambition_level
        self.ambition_text = ambition_text
        self.context_mode = context_mode
        self.pre_build_commands = pre_build_commands or []
        self.engine_build_cmd = engine_build_cmd
        self.engine_test_cmd = engine_test_cmd
        self.prompt_overrides = prompt_overrides or {}
        self.chain_id = chain_id
        self.chain_goal_index = chain_goal_index


class Service:
    """Orchestrator service -- manages job lifecycle through the state machine."""

    def __init__(
        self,
        sessions: SessionManager,
        state: StateStore,
        artifacts: ArtifactStore,
        workspace_root: str,
    ) -> None:
        self._sessions = sessions
        self._state = state
        self._artifacts = artifacts
        self._workspace_root = workspace_root
        self._instance_id = new_service_instance_id()
        self._event_queue: asyncio.Queue[EventNotification] = asyncio.Queue(maxsize=100)
        self._lock = asyncio.Lock()
        self._running_jobs: set[str] = set()
        self._job_cache: dict[str, Job] = {}
        self._cache_lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()
        self._bg_tasks: set[asyncio.Task] = set()
        self._lease = JobLease(
            lease_dir=f"{workspace_root or '.'}/.baton/leases",
            instance_id=self._instance_id,
        )
        self._runner = Runner(policy=default_policy())
        self._processes = ProcessManager(policy=default_policy())

    @property
    def workspace_root(self) -> str:
        return self._workspace_root

    @property
    def event_queue(self) -> asyncio.Queue[EventNotification]:
        return self._event_queue

    # -- Public API ---------------------------------------------------------

    async def start(self, input: CreateJobInput) -> Job:
        job = self._prepare_job(input)
        self._add_event(job, "job_created", "job created")
        self._touch(job)
        await self._save_and_cache(job)
        return await self._run_loop(job)

    async def start_async(self, input: CreateJobInput) -> Job:
        """Create job synchronously; run loop in background."""
        job = self._prepare_job(input)
        self._add_event(job, "job_created", "job created")
        self._touch(job)
        await self._save_and_cache(job)
        task = asyncio.create_task(self._run_loop(job))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return job

    async def get(self, job_id: str) -> Job:
        async with self._cache_lock:
            cached = self._job_cache.get(job_id)
            if cached is not None:
                return cached.model_copy(deep=True)
        return await self._state.load_job(job_id)

    async def list_jobs(self) -> list[Job]:
        return await self._state.list_jobs()

    async def resume(self, job_id: str, extra_steps: int = 0) -> Job:
        job = await self._state.load_job(job_id)
        if job.status in (JobStatus.DONE, JobStatus.FAILED):
            return job
        if job.pending_approval is not None:
            raise ValueError("job has a pending approval; use approve or reject instead")
        if extra_steps > 0:
            self._apply_extra_steps(job, extra_steps)
            await self._save_and_cache(job)
        self._add_event(job, "job_resumed", "job resumed")
        return await self._run_loop(job)

    async def cancel(self, job_id: str, reason: str = "") -> Job:
        job = await self._state.load_job(job_id)
        if job.status == JobStatus.DONE:
            raise ValueError("cannot cancel completed job")
        reason = reason.strip() or "operator cancelled job"
        job.status = JobStatus.BLOCKED
        job.blocked_reason = f"cancelled by operator: {reason}"
        job.failure_reason = ""
        job.pending_approval = None
        job.leader_context_summary = job.blocked_reason
        self._add_event(job, "job_cancelled", job.blocked_reason)
        self._touch(job)
        await self._save_and_cache(job)
        await self._handle_chain_terminal(job)
        return job

    async def retry(self, job_id: str) -> Job:
        job = await self._state.load_job(job_id)
        if job.status not in (JobStatus.BLOCKED, JobStatus.FAILED):
            raise ValueError("retry is only allowed for blocked or failed jobs")
        job.retry_count += 1
        job.status = JobStatus.RUNNING
        job.blocked_reason = ""
        job.failure_reason = ""
        job.pending_approval = None
        job.leader_context_summary = f"retry #{job.retry_count} requested"
        self._add_event(job, "job_retry_requested", job.leader_context_summary)
        self._touch(job)
        await self._save_and_cache(job)
        return await self._run_loop(job)

    async def approve(self, job_id: str) -> Job:
        job = await self._state.load_job(job_id)
        if job.pending_approval is None:
            raise ValueError("no pending approval for job")
        pending = job.pending_approval
        job.pending_approval = None
        job.blocked_reason = ""
        job.failure_reason = ""
        job.status = JobStatus.RUNNING
        job.leader_context_summary = f"operator approved step {pending.step_index}"
        self._add_event(job, "job_approved", job.leader_context_summary)
        self._touch(job)
        await self._save_and_cache(job)
        if is_terminal(job.status):
            return job
        return await self._run_loop(job)

    async def reject(self, job_id: str, reason: str = "") -> Job:
        job = await self._state.load_job(job_id)
        if job.pending_approval is None:
            raise ValueError("no pending approval for job")
        reason = reason.strip() or "operator rejected pending approval"
        job.status = JobStatus.BLOCKED
        job.blocked_reason = reason
        job.failure_reason = ""
        job.pending_approval = None
        job.leader_context_summary = reason
        self._add_event(job, "job_rejected", reason)
        self._touch(job)
        await self._save_and_cache(job)
        await self._handle_chain_terminal(job)
        return job

    async def steer(self, job_id: str, directive: str) -> Job:
        job = await self._state.load_job(job_id)
        job.supervisor_directive = directive.strip()
        self._add_event(job, "supervisor_directive", directive.strip())
        self._touch(job)
        await self._save_and_cache(job)
        return job

    # -- Chain API ----------------------------------------------------------

    async def start_chain(self, goals: list[ChainGoal], workspace_dir: str) -> JobChain:
        validate_workspace_dir(workspace_dir)
        if not goals:
            raise ValueError("at least one chain goal is required")
        now = datetime.now(timezone.utc)
        chain = JobChain(
            id=f"chain-{int(now.timestamp() * 1000)}",
            goals=[],
            current_index=0,
            status=ChainStatus.RUNNING,
            created_at=now,
            updated_at=now,
        )
        for i, g in enumerate(goals):
            chain.goals.append(ChainGoal(
                goal=g.goal.strip(),
                provider=g.provider or ProviderName.MOCK,
                pipeline_mode=normalize_pipeline_mode(g.pipeline_mode),
                strictness_level=g.strictness_level.strip().lower() or "normal",
                ambition_level=normalize_ambition_level(g.ambition_level),
                max_steps=g.max_steps if g.max_steps > 0 else 8,
                status=ChainGoalStatus.PENDING,
            ))
        await self._state.save_chain(chain)
        await self._start_chain_goal(chain, workspace_dir, 0, None)
        return chain

    async def get_chain(self, chain_id: str) -> JobChain:
        return await self._state.load_chain(chain_id)

    async def list_chains(self) -> list[JobChain]:
        return await self._state.list_chains()

    async def pause_chain(self, chain_id: str) -> JobChain:
        chain = await self._state.load_chain(chain_id)
        if chain.status in (ChainStatus.DONE, ChainStatus.FAILED, ChainStatus.CANCELLED):
            return chain
        chain.status = ChainStatus.PAUSED
        chain.updated_at = datetime.now(timezone.utc)
        await self._state.save_chain(chain)
        return chain

    async def resume_chain(self, chain_id: str) -> JobChain:
        chain = await self._state.load_chain(chain_id)
        if chain.status in (ChainStatus.DONE, ChainStatus.FAILED, ChainStatus.CANCELLED):
            return chain
        chain.status = ChainStatus.RUNNING
        chain.updated_at = datetime.now(timezone.utc)
        await self._state.save_chain(chain)
        await self._advance_chain(chain)
        return await self._state.load_chain(chain.id)

    async def cancel_chain(self, chain_id: str, reason: str = "") -> JobChain:
        chain = await self._state.load_chain(chain_id)
        if chain.status in (ChainStatus.DONE, ChainStatus.FAILED, ChainStatus.CANCELLED):
            return chain
        reason = reason.strip() or "operator cancelled chain"
        chain.status = ChainStatus.CANCELLED
        if 0 <= chain.current_index < len(chain.goals):
            current = chain.goals[chain.current_index]
            if current.status in (ChainGoalStatus.PENDING, ChainGoalStatus.RUNNING):
                current.status = ChainGoalStatus.FAILED
        chain.updated_at = datetime.now(timezone.utc)
        await self._state.save_chain(chain)
        return chain

    async def skip_chain_goal(self, chain_id: str) -> JobChain:
        chain = await self._state.load_chain(chain_id)
        if chain.status in (ChainStatus.DONE, ChainStatus.FAILED, ChainStatus.CANCELLED):
            return chain
        if not (0 <= chain.current_index < len(chain.goals)):
            raise ValueError(f"chain current index out of range: {chain.current_index}")
        chain.goals[chain.current_index].status = ChainGoalStatus.SKIPPED
        if chain.current_index == len(chain.goals) - 1:
            chain.status = ChainStatus.DONE
        chain.updated_at = datetime.now(timezone.utc)
        await self._state.save_chain(chain)
        if chain.status != ChainStatus.DONE:
            await self._start_chain_goal(chain, self._workspace_root, chain.current_index + 1, None)
        return await self._state.load_chain(chain.id)

    async def shutdown(self) -> None:
        self._shutdown_event.set()
        for task in list(self._bg_tasks):
            task.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)

    # -- Core loop ----------------------------------------------------------

    async def _run_loop(self, job: Job) -> Job:
        if not self._claim_job_run(job.id):
            _log.info("suppressing duplicate run_loop for job %s", job.id)
            return job

        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            run_heartbeat(self._lease, job.id, job.workspace_dir, stop_event)
        )
        try:
            return await self._run_loop_inner(job)
        finally:
            stop_event.set()
            await heartbeat_task
            self._release_job_run(job.id)
            self._lease.remove_lease(job.id)
            if is_terminal(job.status):
                async with self._cache_lock:
                    self._job_cache.pop(job.id, None)

    async def _run_loop_inner(self, job: Job) -> Job:
        # Planning phase
        if not job.planning_artifacts or not job.sprint_contract_ref.strip():
            job.status = JobStatus.PLANNING
            await self._cache_update(job)
            await self._ensure_planning(job)
            if is_terminal(job.status):
                return job

        completion_retry_pending = False
        completion_retry_step_count = 0
        consecutive_summarizes = 0

        while job.current_step < job.max_steps:
            if self._shutdown_event.is_set():
                return await self._block_job(job, "orchestrator shutdown")

            job.status = JobStatus.WAITING_LEADER
            self._touch(job)
            self._add_event(job, "leader_requested", "requesting leader action")
            if not completion_retry_pending:
                await self._save_and_cache(job)

            # Run leader phase
            try:
                raw_leader = await self._sessions.run_leader(job)
            except ProviderError as exc:
                if exc.recommended_action == ErrorAction.BLOCK:
                    return await self._block_job(job, f"leader execution blocked: {exc}")
                return await self._fail_job(job, f"leader execution failed: {exc}")

            self._collect_tokens(job)

            # Parse leader output with schema retry
            leader = await self._parse_with_retry(
                job, raw_leader, LeaderOutput, "leader",
                lambda: self._sessions.run_leader(job),
            )
            if leader is None:
                return job  # fail_job already called
            job.supervisor_directive = ""

            # Cap consecutive summarizes
            if leader.action == "summarize":
                if consecutive_summarizes >= 2:
                    leader.action = "complete"
                    consecutive_summarizes = 0
                else:
                    consecutive_summarizes += 1
            else:
                consecutive_summarizes = 0

            # Dispatch based on action
            match leader.action:
                case "run_worker" | "run_workers":
                    if completion_retry_pending:
                        job.blocked_reason = ""
                        completion_retry_pending = False
                    await self._run_worker_step(job, leader)
                    if is_terminal(job.status):
                        return job

                case "run_system":
                    if completion_retry_pending:
                        job.blocked_reason = ""
                        completion_retry_pending = False
                    await self._run_system_step(job, leader)
                    if is_terminal(job.status):
                        return job

                case "summarize":
                    if completion_retry_pending:
                        job.blocked_reason = ""
                        completion_retry_pending = False
                    job.summary = leader.reason
                    job.leader_context_summary = leader.next_hint
                    self._add_event(job, "leader_summary", "leader emitted a summary")
                    self._touch(job)
                    await self._save_and_cache(job)

                case "complete":
                    # CORE INVARIANT: evaluateCompletion is NEVER bypassed
                    if completion_retry_pending and len(job.steps) == completion_retry_step_count:
                        job.status = JobStatus.BLOCKED
                        self._touch(job)
                        await self._save_and_cache(job)
                        return job

                    report = await self._evaluate_completion(job)
                    if report.passed:
                        job.status = JobStatus.DONE
                        job.summary = leader.reason
                        self._add_event(job, "job_completed", leader.reason)
                        self._touch(job)
                        await self._save_and_cache(job)
                        await self._handle_chain_completion(job)
                        return job
                    else:
                        if report.status in ("blocked", "failed"):
                            job.leader_context_summary = report.reason
                            completion_retry_pending = True
                            completion_retry_step_count = len(job.steps)
                            continue
                        return job

                case "fail":
                    return await self._fail_job(job, leader.reason)

                case "blocked":
                    return await self._block_job(job, leader.reason)

                case _:
                    return await self._fail_job(job, f"unrecognized leader action: {leader.action!r}")

        return await self._block_job(job, "max_steps_exceeded")

    # -- Worker step --------------------------------------------------------

    async def _run_worker_step(self, job: Job, leader: LeaderOutput) -> None:
        try:
            plans = build_worker_plans(leader)
        except ValueError as exc:
            await self._block_job(job, f"parallel fan-out blocked: {exc}")
            return

        if len(plans) > 1:
            await self._run_parallel_workers(job, plans)
            return

        task = plans[0].task
        job.status = JobStatus.WAITING_WORKER
        job.current_step += 1
        step = Step(
            index=job.current_step,
            target=task.target,
            task_type=task.task_type,
            task_text=task.task_text,
            status=StepStatus.ACTIVE,
            started_at=datetime.now(timezone.utc),
        )
        job.steps.append(step)
        self._add_event(job, "worker_requested", f"{task.target}:{task.task_type}")
        self._touch(job)
        await self._save_and_cache(job)

        try:
            raw_worker = await self._sessions.run_worker(job, task)
        except ProviderError as exc:
            last = job.steps[-1]
            last.finished_at = datetime.now(timezone.utc)
            if exc.recommended_action == ErrorAction.BLOCK:
                last.status = StepStatus.BLOCKED
                last.blocked_reason = str(exc)
                self._add_event(job, "worker_blocked", str(exc))
                await self._block_job(job, str(exc))
            else:
                last.status = StepStatus.FAILED
                last.error_reason = str(exc)
                self._add_event(job, "worker_failed", str(exc))
                await self._fail_job(job, str(exc))
            return

        self._collect_tokens(job, job.steps[-1] if job.steps else None)

        worker = await self._parse_with_retry(
            job, raw_worker, WorkerOutput, "worker",
            lambda: self._sessions.run_worker(job, task),
        )
        if worker is None:
            return  # fail_job already called

        artifact_paths = self._artifacts.materialize_worker_artifacts(
            job.id, step.index, worker
        )

        last = job.steps[-1]
        last.summary = worker.summary
        last.artifacts = artifact_paths
        last.blocked_reason = worker.blocked_reason
        last.error_reason = worker.error_reason
        last.finished_at = datetime.now(timezone.utc)

        match worker.status:
            case "success":
                last.diff_summary = collect_workspace_diff_summary(job.workspace_dir or self._workspace_root)
                last.status = StepStatus.SUCCEEDED
                job.status = JobStatus.RUNNING
                job.failure_reason = ""
                self._add_event(job, "worker_succeeded", worker.summary)
            case "blocked":
                reason = worker.blocked_reason or worker.summary or "worker blocked"
                last.status = StepStatus.BLOCKED
                last.blocked_reason = reason
                self._add_event(job, "worker_blocked", reason)
                await self._block_job(job, reason)
                return
            case "failed":
                reason = worker.error_reason or worker.summary or "worker failed"
                last.status = StepStatus.FAILED
                last.error_reason = reason
                job.status = JobStatus.RUNNING
                job.failure_reason = reason
                self._add_event(job, "worker_failed", reason)

        job.leader_context_summary = last.summary or worker.summary
        self._touch(job)
        await self._save_and_cache(job)

    async def _run_parallel_workers(self, job: Job, plans: list[WorkerPlan]) -> None:
        """Execute multiple worker plans concurrently (max 2)."""
        async def run_one(plan: WorkerPlan) -> tuple[WorkerPlan, str | None, Exception | None]:
            try:
                raw = await self._sessions.run_worker(job, plan.task)
                self._collect_tokens(job)
                return plan, raw, None
            except Exception as exc:
                return plan, None, exc

        results = await asyncio.gather(*(run_one(p) for p in plans))
        for plan, raw, exc in results:
            job.current_step += 1
            step = Step(
                index=job.current_step,
                target=plan.task.target,
                task_type=plan.task.task_type,
                task_text=plan.task.task_text,
                status=StepStatus.ACTIVE,
                started_at=datetime.now(timezone.utc),
            )
            job.steps.append(step)
            last = job.steps[-1]
            last.finished_at = datetime.now(timezone.utc)

            if exc is not None:
                last.status = StepStatus.FAILED
                last.error_reason = str(exc)
                self._add_event(job, "worker_failed", str(exc))
                continue

            try:
                worker = WorkerOutput.model_validate_json(raw)
            except Exception as parse_exc:
                last.status = StepStatus.FAILED
                last.error_reason = f"parse error: {parse_exc}"
                continue

            artifact_paths = self._artifacts.materialize_worker_artifacts(job.id, step.index, worker)
            last.summary = worker.summary
            last.artifacts = artifact_paths
            if worker.status == "success":
                last.status = StepStatus.SUCCEEDED
                self._add_event(job, "worker_succeeded", worker.summary)
            elif worker.status == "blocked":
                last.status = StepStatus.BLOCKED
                last.blocked_reason = worker.blocked_reason or "blocked"
            else:
                last.status = StepStatus.FAILED
                last.error_reason = worker.error_reason or "failed"

        # Check if any step blocked/failed the job
        for s in job.steps:
            if s.status == StepStatus.BLOCKED:
                await self._block_job(job, s.blocked_reason)
                return

        job.status = JobStatus.RUNNING
        self._touch(job)
        await self._save_and_cache(job)

    # -- System step --------------------------------------------------------

    async def _run_system_step(self, job: Job, leader: LeaderOutput) -> None:
        if leader.system_action is None:
            await self._block_job(job, "run_system requires system_action")
            return

        from baton.runtime.types import Request, Category

        job.current_step += 1
        step = Step(
            index=job.current_step,
            target="SYS",
            task_type=leader.task_type,
            task_text=leader.task_text,
            status=StepStatus.ACTIVE,
            started_at=datetime.now(timezone.utc),
        )
        job.steps.append(step)
        self._add_event(job, "system_requested", f"SYS:{leader.task_type}")
        self._touch(job)
        await self._save_and_cache(job)

        sa = leader.system_action
        try:
            cat = Category(sa.type.lower()) if sa.type else Category.COMMAND
        except ValueError:
            cat = Category.COMMAND

        req = Request(
            category=cat,
            command=sa.command,
            args=sa.args,
            dir=sa.workdir or job.workspace_dir or self._workspace_root,
        )
        try:
            result = await self._runner.run(req)
        except Exception as exc:
            last = job.steps[-1]
            last.status = StepStatus.FAILED
            last.error_reason = str(exc)
            last.finished_at = datetime.now(timezone.utc)
            self._add_event(job, "system_failed", str(exc))
            job.failure_reason = str(exc)
            self._touch(job)
            await self._save_and_cache(job)
            return

        self._artifacts.materialize_system_result(job.id, step.index, result.model_dump())
        last = job.steps[-1]
        last.finished_at = datetime.now(timezone.utc)
        if result.exit_code == 0:
            last.status = StepStatus.SUCCEEDED
            last.summary = result.stdout[:500] if result.stdout else "system command succeeded"
            self._add_event(job, "system_succeeded", last.summary)
        else:
            last.status = StepStatus.FAILED
            last.error_reason = result.stderr[:500] if result.stderr else f"exit code {result.exit_code}"
            self._add_event(job, "system_failed", last.error_reason)
            job.failure_reason = last.error_reason

        job.status = JobStatus.RUNNING
        self._touch(job)
        await self._save_and_cache(job)

    # -- Planning -----------------------------------------------------------

    async def _ensure_planning(self, job: Job) -> None:
        if job.planning_artifacts and job.sprint_contract_ref.strip():
            return

        try:
            raw = await self._sessions.run_planner(job)
            self._collect_tokens(job)
        except ProviderError as exc:
            if "unsupported" in str(exc).lower():
                await self._persist_planning(job, build_planning_artifact(job))
                return
            await self._fail_job(job, f"planner execution failed: {exc}")
            return

        try:
            planner_output = PlanningArtifact.model_validate_json(raw)
            validate_planning_artifact(planner_output, job)
        except Exception as exc:
            await self._persist_planning(job, build_planning_artifact(job))
            return

        if job.strictness_level == "auto":
            if planner_output.recommended_strictness in ("strict", "normal", "lenient"):
                job.strictness_level = planner_output.recommended_strictness
            else:
                job.strictness_level = "normal"
            if planner_output.recommended_max_steps > 0:
                job.max_steps = planner_output.recommended_max_steps

        planning = build_planning_artifact(job, planner_output)
        await self._persist_planning(job, planning)

    async def _persist_planning(self, job: Job, planning: PlanningArtifact) -> None:
        from baton.domain.types import PlanningArtifact as PA
        spec_path = self._artifacts.materialize_text_artifact(
            job.id, "product_spec.md", planning_markdown(planning)
        )
        plan_path = self._artifacts.materialize_json_artifact(
            job.id, "execution_plan.json", planning.model_dump()
        )
        contract = build_sprint_contract(job, planning)
        contract_path = self._artifacts.materialize_json_artifact(
            job.id, "sprint_contract.json", contract.model_dump()
        )
        job.sprint_contract_ref = contract_path

        verification = build_verification_contract(job, planning, contract, [spec_path, plan_path, contract_path])
        ver_path = self._artifacts.materialize_json_artifact(
            job.id, "verification_contract.json", verification.to_dict()
        )

        job.verification_contract = build_persisted_verification_contract(
            job, planning, contract, verification, ver_path
        )
        job.verification_contract_ref = ver_path
        job.planning_artifacts = [spec_path, plan_path, contract_path, ver_path]
        invariants = list(job.constraints) + list(planning.invariants_to_preserve)
        job.constraints = _unique(invariants)
        job.summary = planning.summary
        job.leader_context_summary = planning.summary
        self._add_event(job, "job_planned", f"planned {len(job.planning_artifacts)} artifacts")
        self._touch(job)
        await self._save_and_cache(job)

    # -- Evaluator gate (CORE INVARIANT) ------------------------------------

    async def _evaluate_completion(self, job: Job) -> EvaluatorReport:
        """The completion gate -- NEVER bypassed. done requires passing this."""
        try:
            verification, ver_path = resolve_verification_contract(job)
        except FileNotFoundError:
            planning = build_planning_artifact(job)
            sprint = build_sprint_contract(job, planning)
            verification = build_verification_contract(
                job, planning, sprint, job.planning_artifacts
            )
            ver_path = verification_contract_path(job)

        sprint = build_sprint_contract(job, build_planning_artifact(job))

        # Run mechanical checks
        if job.verification_contract and job.verification_contract.automated_checks:
            job.pre_check_results = run_automated_checks(
                job.workspace_dir or self._workspace_root,
                job.verification_contract.automated_checks,
                job.steps,
            )

        try:
            raw = await self._sessions.run_evaluator(job)
            self._collect_tokens(job)
        except ProviderError as exc:
            if "unsupported" in str(exc).lower():
                provider_report = deterministic_evaluator_report(job, verification, sprint)
            else:
                return EvaluatorReport(
                    status="failed",
                    passed=False,
                    score=0,
                    reason=f"evaluator execution failed: {exc}",
                    contract_ref=job.sprint_contract_ref,
                )
        else:
            try:
                provider_report = EvaluatorReport.model_validate_json(raw)
            except Exception:
                provider_report = deterministic_evaluator_report(job, verification, sprint)

        report = merge_evaluator_report(job, verification, sprint, provider_report)
        report_path = self._artifacts.materialize_json_artifact(
            job.id, "evaluator_report.json", report.model_dump()
        )
        job.evaluator_report_ref = report_path
        apply_evaluator_job_state(job, report)

        if report.status == "failed":
            self._add_event(job, "evaluation_failed", report.reason)
        elif report.status == "passed":
            self._add_event(job, "evaluation_passed", report.reason)
        else:
            self._add_event(job, "evaluation_blocked", report.reason)

        self._touch(job)
        await self._save_and_cache(job)
        return report

    # -- Schema retry -------------------------------------------------------

    async def _parse_with_retry(
        self,
        job: Job,
        raw: str,
        model_cls: type,
        phase: str,
        retry_fn,
    ):
        """Parse raw output; retry up to SCHEMA_RETRY_MAX times on parse failure."""
        for attempt in range(SCHEMA_RETRY_MAX + 1):
            try:
                obj = model_cls.model_validate_json(raw)
                job.schema_retry_hint = ""
                return obj
            except Exception as exc:
                if attempt >= SCHEMA_RETRY_MAX:
                    job.schema_retry_hint = ""
                    await self._fail_job(
                        job, f"{phase} schema validation failed after {SCHEMA_RETRY_MAX + 1} attempts: {exc}"
                    )
                    return None
                hint = str(exc)
                self._add_event(job, "schema_retry", f"{phase} schema retry {attempt + 1}/{SCHEMA_RETRY_MAX}: {hint}")
                job.schema_retry_hint = hint
                try:
                    raw = await retry_fn()
                except Exception as retry_exc:
                    job.schema_retry_hint = ""
                    await self._fail_job(job, f"{phase} schema retry failed: {retry_exc}")
                    return None
        return None

    # -- Chain helpers ------------------------------------------------------

    async def _start_chain_goal(
        self, chain: JobChain, workspace_dir: str, index: int, chain_ctx: ChainContext | None,
    ) -> None:
        if not (0 <= index < len(chain.goals)):
            raise ValueError(f"chain goal index out of range: {index}")
        goal = chain.goals[index]
        input_ = CreateJobInput(
            goal=goal.goal,
            provider=goal.provider,
            workspace_dir=workspace_dir,
            max_steps=goal.max_steps,
            pipeline_mode=goal.pipeline_mode,
            strictness_level=goal.strictness_level,
            ambition_level=goal.ambition_level,
            role_profiles=default_role_profiles(goal.provider),
            chain_id=chain.id,
            chain_goal_index=index,
        )
        job = self._prepare_job(input_)
        job.chain_context = chain_ctx
        goal.job_id = job.id
        goal.status = ChainGoalStatus.RUNNING
        chain.current_index = index
        chain.status = ChainStatus.RUNNING
        chain.updated_at = datetime.now(timezone.utc)
        await self._state.save_chain(chain)

        self._add_event(job, "job_created", "job created")
        self._touch(job)
        await self._save_and_cache(job)
        task = asyncio.create_task(self._run_loop(job))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _advance_chain(self, chain: JobChain) -> None:
        if chain.status in (ChainStatus.DONE, ChainStatus.FAILED, ChainStatus.PAUSED, ChainStatus.CANCELLED):
            return
        if not (0 <= chain.current_index < len(chain.goals)):
            return
        current = chain.goals[chain.current_index]
        if not current.job_id:
            return
        try:
            job = await self._state.load_job(current.job_id)
        except JobNotFoundError:
            return

        if job.status == JobStatus.DONE:
            current.status = ChainGoalStatus.DONE
            if chain.current_index == len(chain.goals) - 1:
                chain.status = ChainStatus.DONE
                chain.updated_at = datetime.now(timezone.utc)
                await self._state.save_chain(chain)
                return
            chain.updated_at = datetime.now(timezone.utc)
            await self._state.save_chain(chain)
            prev_ctx = None
            if job.summary or job.evaluator_report_ref:
                prev_ctx = ChainContext(
                    summary=job.summary,
                    evaluator_report_ref=job.evaluator_report_ref,
                )
            await self._start_chain_goal(chain, job.workspace_dir, chain.current_index + 1, prev_ctx)
        elif job.status in (JobStatus.BLOCKED, JobStatus.FAILED):
            current.status = ChainGoalStatus.FAILED
            chain.status = ChainStatus.FAILED
            chain.updated_at = datetime.now(timezone.utc)
            await self._state.save_chain(chain)

    async def _handle_chain_completion(self, job: Job) -> None:
        if not job.chain_id.strip():
            return
        try:
            chain = await self._state.load_chain(job.chain_id)
        except ChainNotFoundError:
            return
        if chain.status == ChainStatus.CANCELLED:
            return
        await self._advance_chain(chain)

    async def _handle_chain_terminal(self, job: Job) -> None:
        if not job.chain_id.strip():
            return
        try:
            chain = await self._state.load_chain(job.chain_id)
        except ChainNotFoundError:
            return
        if chain.status in (ChainStatus.DONE, ChainStatus.FAILED, ChainStatus.CANCELLED):
            return
        if 0 <= job.chain_goal_index < len(chain.goals):
            chain.goals[job.chain_goal_index].status = ChainGoalStatus.FAILED
        chain.status = ChainStatus.FAILED
        chain.updated_at = datetime.now(timezone.utc)
        await self._state.save_chain(chain)

    # -- Job preparation ----------------------------------------------------

    def _prepare_job(self, input: CreateJobInput) -> Job:
        now = datetime.now(timezone.utc)
        job_id = f"job-{int(now.timestamp() * 1000)}"
        max_steps = max(input.max_steps, 1)
        provider = input.provider or ProviderName.MOCK
        role_profiles = input.role_profiles.normalize(provider)

        workspace_dir, requested_dir, mode = prepare_workspace_dir(
            self._workspace_root, input.workspace_dir, job_id, input.workspace_mode,
        )

        return Job(
            id=job_id,
            goal=input.goal.strip(),
            tech_stack=input.tech_stack.strip(),
            workspace_dir=workspace_dir,
            requested_workspace_dir=requested_dir,
            workspace_mode=mode,
            constraints=list(input.constraints),
            done_criteria=list(input.done_criteria),
            pipeline_mode=normalize_pipeline_mode(input.pipeline_mode),
            strictness_level=input.strictness_level.strip().lower() or "normal",
            ambition_level=normalize_ambition_level(input.ambition_level),
            ambition_text=input.ambition_text.strip(),
            context_mode=input.context_mode.strip().lower() or "full",
            role_profiles=role_profiles,
            role_overrides=input.role_overrides,
            pre_build_commands=list(input.pre_build_commands),
            engine_build_cmd=input.engine_build_cmd.strip(),
            engine_test_cmd=input.engine_test_cmd.strip(),
            prompt_overrides=input.prompt_overrides,
            chain_id=input.chain_id.strip(),
            chain_goal_index=input.chain_goal_index,
            status=JobStatus.STARTING,
            provider=provider,
            max_steps=max_steps,
            created_at=now,
            updated_at=now,
            leader_context_summary=f"Goal: {input.goal.strip()}",
        )

    # -- Helpers ------------------------------------------------------------

    async def _fail_job(self, job: Job, reason: str) -> Job:
        job.status = JobStatus.FAILED
        job.failure_reason = reason
        self._add_event(job, "job_failed", reason)
        self._touch(job)
        await self._save_and_cache(job)
        await self._handle_chain_terminal(job)
        return job

    async def _block_job(self, job: Job, reason: str) -> Job:
        job.status = JobStatus.BLOCKED
        job.blocked_reason = reason
        self._add_event(job, "job_blocked", reason)
        self._touch(job)
        await self._save_and_cache(job)
        await self._handle_chain_terminal(job)
        return job

    def _claim_job_run(self, job_id: str) -> bool:
        if job_id in self._running_jobs:
            return False
        self._running_jobs.add(job_id)
        return True

    def _release_job_run(self, job_id: str) -> None:
        self._running_jobs.discard(job_id)

    def _add_event(self, job: Job, kind: str, message: str) -> None:
        job.events.append(Event(
            time=datetime.now(timezone.utc),
            kind=kind,
            message=message,
        ))
        try:
            self._event_queue.put_nowait(
                EventNotification(job_id=job.id, kind=kind, message=message)
            )
        except asyncio.QueueFull:
            pass

    def _touch(self, job: Job) -> None:
        job.updated_at = datetime.now(timezone.utc)

    async def _cache_update(self, job: Job) -> None:
        async with self._cache_lock:
            self._job_cache[job.id] = job.model_copy(deep=True)

    def _collect_tokens(self, job: Job, step: Step | None = None) -> None:
        """Accumulate token usage from the last provider call."""
        usage = self._sessions.last_token_usage
        if usage.total_tokens == 0:
            return
        job.token_usage.input_tokens += usage.input_tokens
        job.token_usage.output_tokens += usage.output_tokens
        job.token_usage.total_tokens += usage.total_tokens
        job.token_usage.estimated_cost_usd += usage.estimated_cost_usd
        if step is not None:
            step.token_usage.input_tokens += usage.input_tokens
            step.token_usage.output_tokens += usage.output_tokens
            step.token_usage.total_tokens += usage.total_tokens
            step.token_usage.estimated_cost_usd += usage.estimated_cost_usd
        self._sessions.last_token_usage = TokenUsage()

    async def _save_and_cache(self, job: Job) -> None:
        """Persist job to disk and update in-memory cache atomically."""
        await self._state.save_job(job)
        await self._cache_update(job)

    def _apply_extra_steps(self, job: Job, extra: int) -> None:
        if extra <= 0:
            return
        if job.status != JobStatus.BLOCKED or job.blocked_reason != "max_steps_exceeded":
            raise ValueError("extra_steps only valid for max_steps_exceeded blocked jobs")
        remaining = MAX_RESUME_EXTRA_STEPS - job.resume_extra_steps_used
        if remaining <= 0:
            raise ValueError("resume extra step budget exhausted")
        if extra > remaining:
            raise ValueError(f"extra_steps exceeds remaining budget: requested={extra} remaining={remaining}")
        job.max_steps += extra
        job.resume_extra_steps_used += extra
        job.blocked_reason = ""
        job.failure_reason = ""
        self._add_event(job, "job_resume_extra_steps", f"extended max steps by {extra} to {job.max_steps}")
        self._touch(job)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
