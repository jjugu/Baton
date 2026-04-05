"""Cross-validate baton/orchestrator/service.py against Go service.go.

Critical tests:
1. Evaluator gate invariant: done ONLY via _evaluate_completion
2. State transitions match Go
3. _prepare_job matches Go prepareJob
4. Resume/Cancel/Retry/Approve/Reject logic matches Go
5. Chain lifecycle
6. Constants match Go
7. Extra steps budget
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from baton.domain.types import (
    ChainGoal,
    ChainGoalStatus,
    ChainStatus,
    EvaluatorReport,
    Job,
    JobChain,
    JobStatus,
    LeaderOutput,
    PendingApproval,
    ProviderName,
    RoleProfiles,
    Step,
    StepStatus,
    WorkerOutput,
)
from baton.orchestrator.service import (
    CreateJobInput,
    MAX_RESUME_EXTRA_STEPS,
    PROVIDER_RETRY_BASE_DELAY,
    PROVIDER_RETRY_LIMIT,
    SCHEMA_RETRY_MAX,
    Service,
)
from baton.provider.mock import MockAdapter
from baton.provider.registry import Registry, SessionManager
from baton.store.artifact_store import ArtifactStore
from baton.store.state_store import StateStore


# ---------------------------------------------------------------------------
# Constants match Go
# ---------------------------------------------------------------------------

class TestConstants:
    def test_provider_retry_limit(self) -> None:
        """Go: providerRetryLimit = 3."""
        assert PROVIDER_RETRY_LIMIT == 3

    def test_provider_retry_base_delay(self) -> None:
        """Go: providerRetryBaseDelay = 250ms."""
        assert PROVIDER_RETRY_BASE_DELAY == 0.25

    def test_max_resume_extra_steps(self) -> None:
        """Go: maxResumeExtraSteps = 20."""
        assert MAX_RESUME_EXTRA_STEPS == 20

    def test_schema_retry_max(self) -> None:
        """Go: schemaRetryMax = 2."""
        assert SCHEMA_RETRY_MAX == 2


# ---------------------------------------------------------------------------
# Service construction
# ---------------------------------------------------------------------------

@pytest.fixture()
def service(tmp_path: Path) -> Service:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    reg = Registry()
    reg.register(MockAdapter())
    sm = SessionManager(reg)
    state = StateStore(tmp_path / "state")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    return Service(sm, state, artifacts, str(workspace))


# ---------------------------------------------------------------------------
# _prepare_job matches Go prepareJob
# ---------------------------------------------------------------------------

class TestPrepareJob:
    def test_default_values(self, service: Service) -> None:
        """Go: defaults to mock provider, 8 max_steps, starting status."""
        job = service._prepare_job(CreateJobInput(goal="test goal"))
        assert job.goal == "test goal"
        assert job.status == JobStatus.STARTING
        assert job.provider == "mock"
        assert job.max_steps >= 1
        assert job.id.startswith("job-")

    def test_pipeline_mode_normalized(self, service: Service) -> None:
        job = service._prepare_job(CreateJobInput(goal="test", pipeline_mode="LIGHT"))
        assert job.pipeline_mode == "light"

    def test_ambition_level_normalized(self, service: Service) -> None:
        job = service._prepare_job(CreateJobInput(goal="test", ambition_level="HIGH"))
        assert job.ambition_level == "high"

    def test_strictness_defaults_normal(self, service: Service) -> None:
        job = service._prepare_job(CreateJobInput(goal="test"))
        assert job.strictness_level == "normal"

    def test_context_mode_defaults_full(self, service: Service) -> None:
        job = service._prepare_job(CreateJobInput(goal="test"))
        assert job.context_mode == "full"

    def test_leader_context_summary_set(self, service: Service) -> None:
        """Go: fmt.Sprintf(\"Goal: %s\", strings.TrimSpace(input.Goal))."""
        job = service._prepare_job(CreateJobInput(goal="  build engine  "))
        assert job.leader_context_summary == "Goal: build engine"


# ---------------------------------------------------------------------------
# Evaluator gate invariant
# ---------------------------------------------------------------------------

class TestEvaluatorGateInvariant:
    """CORE INVARIANT: done is ONLY reachable through _evaluate_completion.

    We verify this by checking that the "complete" action in _run_loop_inner
    always calls _evaluate_completion before setting JobStatus.DONE."""

    def test_done_status_only_after_eval_pass(self, service: Service) -> None:
        """Structurally verify: grep the source for JobStatus.DONE assignments."""
        import inspect
        source = inspect.getsource(Service)

        # Find all lines that set status to DONE
        import re
        done_assignments = [
            line.strip()
            for line in source.split("\n")
            if re.search(r"\.status\s*=\s*JobStatus\.DONE", line)
        ]

        # There should be exactly ONE place: inside the "complete" action
        # after report.passed is True
        assert len(done_assignments) == 1, (
            f"Expected exactly 1 JobStatus.DONE assignment, found {len(done_assignments)}: {done_assignments}"
        )

    def test_evaluate_completion_called_before_done(self, service: Service) -> None:
        """The _evaluate_completion call must precede the DONE assignment."""
        import inspect
        source = inspect.getsource(Service._run_loop_inner)
        lines = source.split("\n")

        eval_line = None
        done_line = None
        for i, line in enumerate(lines):
            if "_evaluate_completion" in line and eval_line is None:
                eval_line = i
            if "JobStatus.DONE" in line and done_line is None:
                done_line = i

        assert eval_line is not None, "_evaluate_completion not found in _run_loop_inner"
        assert done_line is not None, "JobStatus.DONE not found in _run_loop_inner"
        assert eval_line < done_line, (
            f"_evaluate_completion (line {eval_line}) must come BEFORE "
            f"JobStatus.DONE (line {done_line})"
        )


# ---------------------------------------------------------------------------
# Cancel logic matches Go
# ---------------------------------------------------------------------------

class TestCancelLogic:
    @pytest.mark.asyncio
    async def test_cancel_sets_blocked(self, service: Service) -> None:
        """Go: Cancel sets status to blocked, not failed."""
        job = service._prepare_job(CreateJobInput(goal="test"))
        await service._state.save_job(job)

        result = await service.cancel(job.id, "test cancel")
        assert result.status == JobStatus.BLOCKED
        assert "cancelled by operator" in result.blocked_reason
        assert result.pending_approval is None

    @pytest.mark.asyncio
    async def test_cancel_done_raises(self, service: Service) -> None:
        """Go: Cannot cancel completed job."""
        job = service._prepare_job(CreateJobInput(goal="test"))
        job.status = JobStatus.DONE
        await service._state.save_job(job)

        with pytest.raises(ValueError, match="cannot cancel"):
            await service.cancel(job.id)


# ---------------------------------------------------------------------------
# Retry logic matches Go
# ---------------------------------------------------------------------------

class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_retry_only_blocked_or_failed(self, service: Service) -> None:
        """Go: retry is only allowed for blocked or failed jobs."""
        job = service._prepare_job(CreateJobInput(goal="test"))
        job.status = JobStatus.RUNNING
        await service._state.save_job(job)

        with pytest.raises(ValueError, match="retry is only allowed"):
            await service.retry(job.id)

    @pytest.mark.asyncio
    async def test_retry_increments_count(self, service: Service) -> None:
        """Go: job.RetryCount++."""
        job = service._prepare_job(CreateJobInput(goal="test"))
        job.status = JobStatus.BLOCKED
        job.blocked_reason = "test block"
        await service._state.save_job(job)

        # Mock _run_loop to capture the job state after retry mutations
        captured_job: list[Job] = []

        async def capture_run_loop(j: Job) -> Job:
            captured_job.append(j)
            return j

        with patch.object(service, "_run_loop", side_effect=capture_run_loop):
            await service.retry(job.id)
            assert len(captured_job) == 1
            assert captured_job[0].retry_count == 1
            assert captured_job[0].status == JobStatus.RUNNING


# ---------------------------------------------------------------------------
# Approve/Reject logic
# ---------------------------------------------------------------------------

class TestApproveReject:
    @pytest.mark.asyncio
    async def test_approve_no_pending_raises(self, service: Service) -> None:
        """Go: job has a pending approval; error if none."""
        job = service._prepare_job(CreateJobInput(goal="test"))
        job.status = JobStatus.BLOCKED
        await service._state.save_job(job)

        with pytest.raises(ValueError, match="no pending approval"):
            await service.approve(job.id)

    @pytest.mark.asyncio
    async def test_reject_no_pending_raises(self, service: Service) -> None:
        job = service._prepare_job(CreateJobInput(goal="test"))
        job.status = JobStatus.BLOCKED
        await service._state.save_job(job)

        with pytest.raises(ValueError, match="no pending approval"):
            await service.reject(job.id)


# ---------------------------------------------------------------------------
# Resume with pending approval
# ---------------------------------------------------------------------------

class TestResumePendingApproval:
    @pytest.mark.asyncio
    async def test_resume_with_pending_raises(self, service: Service) -> None:
        """Go: job has a pending approval; use approve or reject instead."""
        job = service._prepare_job(CreateJobInput(goal="test"))
        job.status = JobStatus.BLOCKED
        job.pending_approval = PendingApproval(
            step_index=0,
            reason="test",
            requested_at=datetime.now(timezone.utc),
            target="B",
            task_type="implement",
            task_text="do it",
        )
        await service._state.save_job(job)

        with pytest.raises(ValueError, match="pending approval"):
            await service.resume(job.id)


# ---------------------------------------------------------------------------
# Extra steps budget matches Go
# ---------------------------------------------------------------------------

class TestExtraStepsBudget:
    def test_apply_requires_max_steps_exceeded(self, service: Service) -> None:
        """Go: extra_steps is only valid when resuming a max_steps_exceeded blocked job."""
        job = service._prepare_job(CreateJobInput(goal="test"))
        job.status = JobStatus.BLOCKED
        job.blocked_reason = "other_reason"

        with pytest.raises(ValueError, match="max_steps_exceeded"):
            service._apply_extra_steps(job, 5)

    def test_apply_increments_budget(self, service: Service) -> None:
        job = service._prepare_job(CreateJobInput(goal="test"))
        job.status = JobStatus.BLOCKED
        job.blocked_reason = "max_steps_exceeded"
        original = job.max_steps

        service._apply_extra_steps(job, 5)
        assert job.max_steps == original + 5
        assert job.resume_extra_steps_used == 5
        assert job.blocked_reason == ""

    def test_budget_exhaustion(self, service: Service) -> None:
        """Go: resume extra step budget exhausted."""
        job = service._prepare_job(CreateJobInput(goal="test"))
        job.status = JobStatus.BLOCKED
        job.blocked_reason = "max_steps_exceeded"
        job.resume_extra_steps_used = MAX_RESUME_EXTRA_STEPS

        with pytest.raises(ValueError, match="budget exhausted"):
            service._apply_extra_steps(job, 1)

    def test_exceeds_remaining_budget(self, service: Service) -> None:
        job = service._prepare_job(CreateJobInput(goal="test"))
        job.status = JobStatus.BLOCKED
        job.blocked_reason = "max_steps_exceeded"
        job.resume_extra_steps_used = MAX_RESUME_EXTRA_STEPS - 3

        with pytest.raises(ValueError, match="exceeds remaining"):
            service._apply_extra_steps(job, 5)


# ---------------------------------------------------------------------------
# Steer
# ---------------------------------------------------------------------------

class TestSteer:
    @pytest.mark.asyncio
    async def test_steer_sets_directive(self, service: Service) -> None:
        """Go: job.SupervisorDirective = directive."""
        job = service._prepare_job(CreateJobInput(goal="test"))
        await service._state.save_job(job)

        result = await service.steer(job.id, "focus on performance")
        assert result.supervisor_directive == "focus on performance"


# ---------------------------------------------------------------------------
# Chain lifecycle
# ---------------------------------------------------------------------------

class TestChainLifecycle:
    @pytest.mark.asyncio
    async def test_start_chain_empty_goals_raises(self, service: Service) -> None:
        with pytest.raises(ValueError, match="at least one"):
            await service.start_chain([], str(Path(service.workspace_root)))

    @pytest.mark.asyncio
    async def test_pause_chain(self, service: Service) -> None:
        chain = JobChain(id="chain-test", goals=[
            ChainGoal(goal="step 1", provider=ProviderName.MOCK),
        ], status=ChainStatus.RUNNING)
        await service._state.save_chain(chain)

        result = await service.pause_chain("chain-test")
        assert result.status == ChainStatus.PAUSED

    @pytest.mark.asyncio
    async def test_cancel_chain(self, service: Service) -> None:
        chain = JobChain(id="chain-cancel", goals=[
            ChainGoal(goal="step 1", provider=ProviderName.MOCK),
        ], status=ChainStatus.RUNNING)
        await service._state.save_chain(chain)

        result = await service.cancel_chain("chain-cancel", "test reason")
        assert result.status == ChainStatus.CANCELLED


# ---------------------------------------------------------------------------
# Event notification
# ---------------------------------------------------------------------------

class TestEventNotification:
    def test_add_event(self, service: Service) -> None:
        job = service._prepare_job(CreateJobInput(goal="test"))
        service._add_event(job, "test_kind", "test message")
        assert len(job.events) == 1
        assert job.events[0].kind == "test_kind"

    def test_event_queue_nonfull(self, service: Service) -> None:
        job = service._prepare_job(CreateJobInput(goal="test"))
        service._add_event(job, "test", "msg")
        assert not service._event_queue.empty()


# ---------------------------------------------------------------------------
# Full mock pipeline (end-to-end with real service)
# ---------------------------------------------------------------------------

class TestFullMockPipeline:
    @pytest.mark.asyncio
    async def test_mock_job_reaches_done(self, tmp_path: Path) -> None:
        """Run a full job with MockAdapter and verify it reaches DONE."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        reg = Registry()
        reg.register(MockAdapter())
        sm = SessionManager(reg)
        state = StateStore(tmp_path / "state")
        artifacts = ArtifactStore(tmp_path / "artifacts")
        svc = Service(sm, state, artifacts, str(workspace))

        job = await svc.start(CreateJobInput(
            goal="build the engine",
            provider=ProviderName.MOCK,
            workspace_dir=str(workspace),
        ))

        assert job.status == JobStatus.DONE, (
            f"Expected DONE, got {job.status}. "
            f"Reason: {job.blocked_reason or job.failure_reason}"
        )
        assert len(job.steps) >= 3  # implement + search + test
        assert job.evaluator_report_ref != ""  # evaluator was called
