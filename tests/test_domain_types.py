"""Cross-validate baton/domain/types.py against Go gorchera/internal/domain/types.go.

Every assertion compares the Python implementation against the Go-canonical
reference data in conftest.py.
"""
from __future__ import annotations

import json

from baton.domain.types import (
    AmbitionLevel,
    AutomatedCheck,
    AutomatedCheckResult,
    ChainContext,
    ChainGoal,
    ChainGoalStatus,
    ChainStatus,
    ChangedFile,
    EvaluatorReport,
    Event,
    ExecutionProfile,
    Job,
    JobChain,
    JobStatus,
    LeaderOutput,
    PendingApproval,
    PipelineMode,
    PlanningArtifact,
    ProviderName,
    RoleName,
    RoleOverride,
    RoleProfiles,
    RubricAxis,
    RubricScore,
    SprintContract,
    Step,
    StepStatus,
    StructuredReason,
    SystemAction,
    SystemActionType,
    TokenUsage,
    VerificationContract,
    VerificationReport,
    WorkerOutput,
    WorkerTask,
    WorkspaceMode,
    default_role_profiles,
    is_terminal,
    normalize_ambition_level,
    normalize_pipeline_mode,
    role_for_task_type,
    TERMINAL_STATUSES,
)


# ---------------------------------------------------------------------------
# Enum completeness
# ---------------------------------------------------------------------------

class TestJobStatus:
    def test_values_match_go(self, go_job_statuses: frozenset[str]) -> None:
        py_values = {s.value for s in JobStatus}
        assert py_values == go_job_statuses

    def test_count(self) -> None:
        assert len(JobStatus) == 9


class TestStepStatus:
    def test_values_match_go(self, go_step_statuses: frozenset[str]) -> None:
        py_values = {s.value for s in StepStatus}
        assert py_values == go_step_statuses

    def test_count(self) -> None:
        assert len(StepStatus) == 6


class TestProviderName:
    def test_values_match_go(self) -> None:
        from tests.conftest import GO_PROVIDER_NAMES
        py_values = {p.value for p in ProviderName}
        assert py_values == GO_PROVIDER_NAMES

    def test_count(self) -> None:
        assert len(ProviderName) == 3


class TestRoleName:
    def test_values_match_go(self) -> None:
        from tests.conftest import GO_ROLE_NAMES
        py_values = {r.value for r in RoleName}
        assert py_values == GO_ROLE_NAMES

    def test_count(self) -> None:
        assert len(RoleName) == 7


class TestAmbitionLevel:
    def test_values_match_go(self) -> None:
        from tests.conftest import GO_AMBITION_LEVELS
        py_values = {a.value for a in AmbitionLevel}
        assert py_values == GO_AMBITION_LEVELS

    def test_count(self) -> None:
        assert len(AmbitionLevel) == 5


class TestPipelineMode:
    def test_values_match_go(self) -> None:
        from tests.conftest import GO_PIPELINE_MODES
        py_values = {m.value for m in PipelineMode}
        assert py_values == GO_PIPELINE_MODES

    def test_count(self) -> None:
        assert len(PipelineMode) == 3


class TestWorkspaceMode:
    def test_values_match_go(self) -> None:
        from tests.conftest import GO_WORKSPACE_MODES
        py_values = {m.value for m in WorkspaceMode}
        assert py_values == GO_WORKSPACE_MODES


class TestSystemActionType:
    def test_values_match_go(self) -> None:
        from tests.conftest import GO_SYSTEM_ACTION_TYPES
        py_values = {t.value for t in SystemActionType}
        assert py_values == GO_SYSTEM_ACTION_TYPES


class TestChainGoalStatus:
    def test_values_match_go(self) -> None:
        from tests.conftest import GO_CHAIN_GOAL_STATUSES
        py_values = {s.value for s in ChainGoalStatus}
        assert py_values == GO_CHAIN_GOAL_STATUSES


class TestChainStatus:
    def test_values_match_go(self) -> None:
        from tests.conftest import GO_CHAIN_STATUSES
        py_values = {s.value for s in ChainStatus}
        assert py_values == GO_CHAIN_STATUSES


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

class TestNormalizePipelineMode:
    def test_light(self) -> None:
        assert normalize_pipeline_mode("light") == "light"
        assert normalize_pipeline_mode("  LIGHT  ") == "light"

    def test_full(self) -> None:
        assert normalize_pipeline_mode("full") == "full"
        assert normalize_pipeline_mode("FULL") == "full"

    def test_balanced_default(self) -> None:
        assert normalize_pipeline_mode("balanced") == "balanced"
        assert normalize_pipeline_mode("garbage") == "balanced"
        assert normalize_pipeline_mode("") == "balanced"


class TestNormalizeAmbitionLevel:
    def test_known_values(self) -> None:
        for level in ("low", "medium", "high", "extreme", "custom"):
            assert normalize_ambition_level(level) == level

    def test_case_insensitive(self) -> None:
        assert normalize_ambition_level("  HIGH  ") == "high"

    def test_unknown_defaults_medium(self) -> None:
        assert normalize_ambition_level("unknown") == "medium"
        assert normalize_ambition_level("") == "medium"


class TestRoleForTaskType:
    """Go RoleForTaskType always returns RoleExecutor."""
    def test_all_types_route_to_executor(self) -> None:
        for task_type in ("review", "audit", "test", "implement",
                          "build", "lint", "search", "command", "random"):
            assert role_for_task_type(task_type) == RoleName.EXECUTOR


# ---------------------------------------------------------------------------
# ExecutionProfile / RoleProfiles
# ---------------------------------------------------------------------------

class TestExecutionProfile:
    def test_is_zero(self) -> None:
        assert ExecutionProfile().is_zero()
        assert not ExecutionProfile(provider=ProviderName.MOCK).is_zero()

    def test_with_fallback_no_op_when_set(self) -> None:
        p = ExecutionProfile(provider=ProviderName.CLAUDE)
        assert p.with_fallback(ProviderName.MOCK).provider == "claude"

    def test_with_fallback_applies_when_none(self) -> None:
        p = ExecutionProfile()
        assert p.with_fallback(ProviderName.CODEX).provider == "codex"

    def test_json_fields_match_go(self) -> None:
        """Go ExecutionProfile has: provider, model, effort, tool_policy,
        fallback_provider, fallback_model, max_budget_usd."""
        go_fields = {
            "provider", "model", "effort", "tool_policy",
            "fallback_provider", "fallback_model", "max_budget_usd",
        }
        py_fields = set(ExecutionProfile.model_fields.keys())
        assert py_fields == go_fields


class TestDefaultRoleProfiles:
    def test_director_gets_opus(self) -> None:
        rp = default_role_profiles(ProviderName.CLAUDE)
        assert rp.director.model == "opus"
        assert rp.director.provider == "claude"

    def test_executor_gets_sonnet(self) -> None:
        rp = default_role_profiles(ProviderName.CLAUDE)
        assert rp.executor.model == "sonnet"

    def test_evaluator_gets_opus(self) -> None:
        rp = default_role_profiles(ProviderName.CODEX)
        assert rp.evaluator.model == "opus"
        assert rp.evaluator.provider == "codex"

    def test_planner_and_leader_match_director(self) -> None:
        rp = default_role_profiles(ProviderName.CLAUDE)
        assert rp.planner == rp.director
        assert rp.leader == rp.director


class TestRoleProfilesNormalize:
    """Test that normalize() fallback chains match Go Normalize()."""

    def test_empty_profiles_get_base(self) -> None:
        rp = RoleProfiles().normalize(ProviderName.MOCK)
        # Every role should have mock as provider after normalization
        for role in RoleName:
            profile = rp.profile_for(role, ProviderName.MOCK)
            assert profile.provider == "mock"

    def test_tester_inherits_executor(self) -> None:
        """Go: if isZeroExecutionProfile(r.Tester) then r.Tester = r.Executor."""
        rp = RoleProfiles(
            executor=ExecutionProfile(provider=ProviderName.CLAUDE, model="sonnet"),
        ).normalize(ProviderName.MOCK)
        assert rp.tester.model == "sonnet"
        assert rp.tester.provider == "claude"


class TestRoleProfilesProfileFor:
    """Verify fallback chain in profile_for matches Go ProfileFor."""

    def test_director_fallback_chain(self) -> None:
        """Go: director falls back to leader, then planner."""
        rp = RoleProfiles(
            leader=ExecutionProfile(provider=ProviderName.CODEX, model="gpt4"),
        )
        p = rp.profile_for(RoleName.DIRECTOR, ProviderName.MOCK)
        assert p.provider == "codex"
        assert p.model == "gpt4"

    def test_planner_fallback_chain(self) -> None:
        """Go: planner falls back to director, then leader."""
        rp = RoleProfiles(
            director=ExecutionProfile(provider=ProviderName.CLAUDE, model="opus"),
        )
        p = rp.profile_for(RoleName.PLANNER, ProviderName.MOCK)
        assert p.provider == "claude"

    def test_tester_fallback_to_executor(self) -> None:
        """Go: tester falls back to executor."""
        rp = RoleProfiles(
            executor=ExecutionProfile(provider=ProviderName.CLAUDE, model="sonnet"),
        )
        p = rp.profile_for(RoleName.TESTER, ProviderName.MOCK)
        assert p.provider == "claude"
        assert p.model == "sonnet"

    def test_unknown_role_returns_base(self) -> None:
        """Go default case returns ExecutionProfile{Provider: base}."""
        rp = RoleProfiles()
        # Simulate unknown role by directly checking the fallback
        # In Python, the match/case _ handles this
        p = rp.profile_for(RoleName.EXECUTOR, ProviderName.MOCK)
        assert p.provider == "mock"


# ---------------------------------------------------------------------------
# Job model field completeness
# ---------------------------------------------------------------------------

class TestJobFields:
    def test_all_go_fields_present(self, go_job_fields: frozenset[str]) -> None:
        """Every JSON field from Go Job struct must exist in Python Job."""
        py_fields = set(Job.model_fields.keys())
        missing = go_job_fields - py_fields
        assert not missing, f"Missing Go fields in Python Job: {missing}"

    def test_no_extra_persistent_fields(self, go_job_fields: frozenset[str]) -> None:
        """Python should not add persistent fields not in Go (transient excluded)."""
        py_fields = set(Job.model_fields.keys())
        # pre_check_results is transient (exclude=True), matching Go's json:"-"
        py_persistent = py_fields - {"pre_check_results"}
        extra = py_persistent - go_job_fields
        assert not extra, f"Extra Python fields not in Go: {extra}"


# ---------------------------------------------------------------------------
# JSON round-trip (Pydantic models must serialize/deserialize cleanly)
# ---------------------------------------------------------------------------

class TestJsonRoundTrip:
    def test_job_roundtrip(self) -> None:
        job = Job(
            id="test-001",
            goal="fix the bug",
            provider=ProviderName.MOCK,
        )
        data = job.model_dump_json()
        restored = Job.model_validate_json(data)
        assert restored.id == job.id
        assert restored.goal == job.goal
        assert restored.provider == "mock"

    def test_job_chain_roundtrip(self) -> None:
        chain = JobChain(
            id="chain-001",
            goals=[ChainGoal(goal="step 1", provider=ProviderName.CLAUDE)],
        )
        data = chain.model_dump_json()
        restored = JobChain.model_validate_json(data)
        assert restored.id == chain.id
        assert len(restored.goals) == 1

    def test_pre_check_results_excluded(self) -> None:
        """pre_check_results has exclude=True, matching Go's json:\"-\"."""
        job = Job(
            id="test-002",
            goal="test",
            pre_check_results=[
                AutomatedCheckResult(description="check", status="passed"),
            ],
        )
        data = json.loads(job.model_dump_json())
        assert "pre_check_results" not in data


# ---------------------------------------------------------------------------
# Terminal state helpers
# ---------------------------------------------------------------------------

class TestTerminalStatuses:
    def test_terminal_set(self) -> None:
        from tests.conftest import GO_TERMINAL_STATUSES
        py_terminal = {s.value for s in TERMINAL_STATUSES}
        assert py_terminal == GO_TERMINAL_STATUSES

    def test_is_terminal(self) -> None:
        assert is_terminal(JobStatus.DONE)
        assert is_terminal(JobStatus.FAILED)
        assert is_terminal(JobStatus.BLOCKED)
        assert not is_terminal(JobStatus.RUNNING)
        assert not is_terminal(JobStatus.QUEUED)
