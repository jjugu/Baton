"""Cross-validate orchestrator submodules against Go equivalents.

Tests:
- automated_check.py: All 4 check types
- evaluator.py: merge, deterministic report, missing steps
- planning.py: build_planning_artifact, build_sprint_contract
- parallel.py: worker plan fan-out, max 2, disjoint targets
- workspace.py: validate_workspace_dir
- job_runtime.py: validate_lease_id, heartbeat timing constants
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from baton.domain.types import (
    AutomatedCheck,
    AutomatedCheckResult,
    ChangedFile,
    EvaluatorReport,
    Job,
    LeaderOutput,
    PlanningArtifact,
    ProviderName,
    SprintContract,
    Step,
    StepStatus,
    VerificationContract,
    WorkerTask,
)


# ---------------------------------------------------------------------------
# automated_check.py
# ---------------------------------------------------------------------------

class TestAutomatedChecks:
    def test_grep_pattern_found(self, tmp_path: Path) -> None:
        (tmp_path / "main.go").write_text("func main() {}")
        from baton.orchestrator.automated_check import run_automated_checks
        checks = [AutomatedCheck(type="grep", pattern="func main", file="*.go", description="main func")]
        results = run_automated_checks(str(tmp_path), checks, [])
        assert results[0].status == "passed"

    def test_grep_pattern_not_found(self, tmp_path: Path) -> None:
        (tmp_path / "main.go").write_text("package main")
        from baton.orchestrator.automated_check import run_automated_checks
        checks = [AutomatedCheck(type="grep", pattern="nonexistent_func", file="*.go", description="missing")]
        results = run_automated_checks(str(tmp_path), checks, [])
        assert results[0].status == "failed"

    def test_file_exists_pass(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("hello")
        from baton.orchestrator.automated_check import run_automated_checks
        checks = [AutomatedCheck(type="file_exists", path="README.md", description="readme")]
        results = run_automated_checks(str(tmp_path), checks, [])
        assert results[0].status == "passed"

    def test_file_exists_fail(self, tmp_path: Path) -> None:
        from baton.orchestrator.automated_check import run_automated_checks
        checks = [AutomatedCheck(type="file_exists", path="missing.txt", description="missing")]
        results = run_automated_checks(str(tmp_path), checks, [])
        assert results[0].status == "failed"

    def test_file_unchanged_pass(self) -> None:
        from baton.orchestrator.automated_check import run_automated_checks
        steps = [Step(index=0, target="B", task_type="implement", task_text="test",
                      changed_files=[ChangedFile(path="other.go", action="modified")])]
        checks = [AutomatedCheck(type="file_unchanged", path="go.mod", description="go.mod stable")]
        results = run_automated_checks("", checks, steps)
        assert results[0].status == "passed"

    def test_file_unchanged_fail(self) -> None:
        from baton.orchestrator.automated_check import run_automated_checks
        steps = [Step(index=0, target="B", task_type="implement", task_text="test",
                      changed_files=[ChangedFile(path="go.mod", action="modified")])]
        checks = [AutomatedCheck(type="file_unchanged", path="go.mod", description="go.mod stable")]
        results = run_automated_checks("", checks, steps)
        assert results[0].status == "failed"

    def test_no_new_deps_pass(self) -> None:
        from baton.orchestrator.automated_check import run_automated_checks
        steps = [Step(index=0, target="B", task_type="implement", task_text="test",
                      changed_files=[ChangedFile(path="main.go", action="modified")])]
        checks = [AutomatedCheck(type="no_new_deps", description="no deps")]
        results = run_automated_checks("", checks, steps)
        assert results[0].status == "passed"

    def test_no_new_deps_fail(self) -> None:
        from baton.orchestrator.automated_check import run_automated_checks
        steps = [Step(index=0, target="B", task_type="implement", task_text="test",
                      changed_files=[ChangedFile(path="go.mod", action="modified")])]
        checks = [AutomatedCheck(type="no_new_deps", description="no deps")]
        results = run_automated_checks("", checks, steps)
        assert results[0].status == "failed"

    def test_unknown_type_skipped(self) -> None:
        from baton.orchestrator.automated_check import run_automated_checks
        checks = [AutomatedCheck(type="future_check", description="unknown")]
        results = run_automated_checks("", checks, [])
        assert results[0].status == "skipped"


# ---------------------------------------------------------------------------
# evaluator.py
# ---------------------------------------------------------------------------

class TestEvaluator:
    def _job(self, steps: list[Step] | None = None) -> Job:
        return Job(
            id="test", goal="test", provider=ProviderName.MOCK,
            steps=steps or [],
        )

    def test_merge_passes_when_no_missing(self) -> None:
        from baton.orchestrator.evaluator import merge_evaluator_report
        from baton.orchestrator.verification import InternalVerificationContract
        job = self._job([
            Step(index=0, target="B", task_type="implement", task_text="t", status=StepStatus.SUCCEEDED),
        ])
        sprint = SprintContract(required_step_types=["implement"])
        report = EvaluatorReport(status="passed", passed=True, score=100, reason="good")
        result = merge_evaluator_report(job, InternalVerificationContract(), sprint, report)
        assert result.passed is True

    def test_merge_overrides_when_missing(self) -> None:
        from baton.orchestrator.evaluator import merge_evaluator_report
        from baton.orchestrator.verification import InternalVerificationContract
        job = self._job()
        sprint = SprintContract(required_step_types=["implement", "test"])
        report = EvaluatorReport(status="passed", passed=True, score=100, reason="good")
        result = merge_evaluator_report(job, InternalVerificationContract(), sprint, report)
        assert result.passed is False
        assert result.status == "failed"
        assert set(result.missing_step_types) == {"implement", "test"}

    def test_deterministic_report_pass(self) -> None:
        from baton.orchestrator.evaluator import deterministic_evaluator_report
        from baton.orchestrator.verification import InternalVerificationContract
        job = self._job([
            Step(index=0, target="B", task_type="implement", task_text="t", status=StepStatus.SUCCEEDED),
        ])
        sprint = SprintContract(required_step_types=["implement"])
        report = deterministic_evaluator_report(job, InternalVerificationContract(), sprint)
        assert report.passed is True
        assert report.status == "passed"

    def test_deterministic_report_fail(self) -> None:
        from baton.orchestrator.evaluator import deterministic_evaluator_report
        from baton.orchestrator.verification import InternalVerificationContract
        job = self._job()
        sprint = SprintContract(required_step_types=["implement", "test"])
        report = deterministic_evaluator_report(job, InternalVerificationContract(), sprint)
        assert report.passed is False

    def test_missing_required_steps(self) -> None:
        from baton.orchestrator.evaluator import missing_required_steps
        job = self._job([
            Step(index=0, target="B", task_type="implement", task_text="t", status=StepStatus.SUCCEEDED),
        ])
        assert missing_required_steps(job, ["implement", "test"]) == ["test"]


# ---------------------------------------------------------------------------
# planning.py
# ---------------------------------------------------------------------------

class TestPlanning:
    def test_build_planning_artifact_from_job(self) -> None:
        from baton.orchestrator.planning import build_planning_artifact
        job = Job(id="test", goal="build engine", provider=ProviderName.MOCK,
                  constraints=["no breaking changes"])
        plan = build_planning_artifact(job)
        assert plan.goal == "build engine"
        assert "no breaking changes" in plan.invariants_to_preserve

    def test_build_sprint_contract(self) -> None:
        from baton.orchestrator.planning import build_sprint_contract
        job = Job(id="test", goal="build engine", provider=ProviderName.MOCK,
                  strictness_level="normal")
        plan = PlanningArtifact(
            goal="build engine",
            proposed_steps=["implement core", "review code", "test suite"],
        )
        sc = build_sprint_contract(job, plan)
        assert "implement" in sc.required_step_types
        assert "review" in sc.required_step_types
        assert "test" in sc.required_step_types
        assert sc.threshold_require_eval is True

    def test_sprint_contract_lenient_no_eval(self) -> None:
        from baton.orchestrator.planning import build_sprint_contract
        job = Job(id="test", goal="test", provider=ProviderName.MOCK,
                  strictness_level="lenient")
        plan = PlanningArtifact(goal="test")
        sc = build_sprint_contract(job, plan)
        assert sc.threshold_require_eval is False


# ---------------------------------------------------------------------------
# parallel.py
# ---------------------------------------------------------------------------

class TestParallel:
    def test_single_worker(self) -> None:
        from baton.orchestrator.parallel import build_worker_plans
        leader = LeaderOutput(action="run_worker", target="B", task_type="implement", task_text="do it")
        plans = build_worker_plans(leader)
        assert len(plans) == 1
        assert plans[0].task.target == "B"

    def test_parallel_workers(self) -> None:
        from baton.orchestrator.parallel import build_worker_plans
        leader = LeaderOutput(
            action="run_workers",
            tasks=[
                WorkerTask(target="B", task_type="implement", task_text="first"),
                WorkerTask(target="C", task_type="search", task_text="second"),
            ],
        )
        plans = build_worker_plans(leader)
        assert len(plans) == 2

    def test_max_2_workers(self) -> None:
        from baton.orchestrator.parallel import build_worker_plans
        leader = LeaderOutput(
            action="run_workers",
            tasks=[
                WorkerTask(target="B", task_type="implement", task_text="1"),
                WorkerTask(target="C", task_type="search", task_text="2"),
                WorkerTask(target="D", task_type="test", task_text="3"),
            ],
        )
        with pytest.raises(ValueError, match="max_parallel_workers"):
            build_worker_plans(leader)

    def test_disjoint_targets_required(self) -> None:
        from baton.orchestrator.parallel import build_worker_plans
        leader = LeaderOutput(
            action="run_workers",
            tasks=[
                WorkerTask(target="B", task_type="implement", task_text="1"),
                WorkerTask(target="B", task_type="search", task_text="2"),
            ],
        )
        with pytest.raises(ValueError, match="disjoint"):
            build_worker_plans(leader)

    def test_empty_tasks_raises(self) -> None:
        from baton.orchestrator.parallel import build_worker_plans
        leader = LeaderOutput(action="run_workers", tasks=[])
        with pytest.raises(ValueError):
            build_worker_plans(leader)


# ---------------------------------------------------------------------------
# workspace.py
# ---------------------------------------------------------------------------

class TestWorkspace:
    def test_validate_empty_passes(self) -> None:
        from baton.orchestrator.workspace import validate_workspace_dir
        validate_workspace_dir("")  # should not raise

    def test_validate_relative_raises(self) -> None:
        from baton.orchestrator.workspace import validate_workspace_dir, WorkspaceError
        with pytest.raises(WorkspaceError, match="absolute"):
            validate_workspace_dir("relative/path")

    def test_validate_nonexistent_raises(self) -> None:
        from baton.orchestrator.workspace import validate_workspace_dir, WorkspaceError
        # Use a Windows-compatible absolute path that does not exist
        nonexistent = os.path.join(os.path.abspath(os.sep), "nonexistent_baton_qa_test")
        with pytest.raises(WorkspaceError, match="does not exist"):
            validate_workspace_dir(nonexistent)

    def test_normalize_workspace_mode(self) -> None:
        from baton.orchestrator.workspace import normalize_workspace_mode
        assert normalize_workspace_mode("isolated") == "isolated"
        assert normalize_workspace_mode("ISOLATED") == "isolated"
        assert normalize_workspace_mode("shared") == "shared"
        assert normalize_workspace_mode("garbage") == "shared"


# ---------------------------------------------------------------------------
# job_runtime.py
# ---------------------------------------------------------------------------

class TestJobRuntime:
    def test_validate_lease_id_valid(self) -> None:
        from baton.orchestrator.job_runtime import validate_lease_id
        validate_lease_id("job-001")  # should not raise
        validate_lease_id("my_job.v2")  # should not raise

    def test_validate_lease_id_dot(self) -> None:
        from baton.orchestrator.job_runtime import validate_lease_id
        with pytest.raises(ValueError, match="reserved"):
            validate_lease_id(".")

    def test_validate_lease_id_traversal(self) -> None:
        from baton.orchestrator.job_runtime import validate_lease_id
        with pytest.raises(ValueError):
            validate_lease_id("../etc")

    def test_timing_constants(self) -> None:
        """Go: heartbeat=15s, stale=45s."""
        from baton.orchestrator.job_runtime import LEASE_HEARTBEAT_INTERVAL, LEASE_STALE_AFTER
        assert LEASE_HEARTBEAT_INTERVAL == 15.0
        assert LEASE_STALE_AFTER == 45.0

    def test_instance_id_format(self) -> None:
        from baton.orchestrator.job_runtime import new_service_instance_id
        id_ = new_service_instance_id()
        assert id_.startswith("svc-")
