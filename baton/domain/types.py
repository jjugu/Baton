"""Domain types for the baton orchestration engine.

All Pydantic models, enums, and helper functions ported from
gorchera/internal/domain/types.go using Python idioms.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    QUEUED = "queued"
    STARTING = "starting"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_LEADER = "waiting_leader"
    WAITING_WORKER = "waiting_worker"
    BLOCKED = "blocked"
    FAILED = "failed"
    DONE = "done"


class WorkspaceMode(str, Enum):
    SHARED = "shared"
    ISOLATED = "isolated"


class PipelineMode(str, Enum):
    LIGHT = "light"
    BALANCED = "balanced"
    FULL = "full"


class StepStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"


class ProviderName(str, Enum):
    MOCK = "mock"
    CODEX = "codex"
    CLAUDE = "claude"


class RoleName(str, Enum):
    DIRECTOR = "director"
    PLANNER = "planner"
    LEADER = "leader"
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    TESTER = "tester"
    EVALUATOR = "evaluator"


class AmbitionLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"
    CUSTOM = "custom"


class SystemActionType(str, Enum):
    SEARCH = "search"
    BUILD = "build"
    TEST = "test"
    LINT = "lint"
    COMMAND = "command"


class ChainGoalStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class ChainStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Value objects / sub-models
# ---------------------------------------------------------------------------

class ExecutionProfile(BaseModel):
    """Per-role provider + model configuration."""

    model_config = ConfigDict(use_enum_values=True)

    provider: ProviderName | None = None
    model: str = ""
    effort: str = ""
    tool_policy: str = ""
    fallback_provider: ProviderName | None = None
    fallback_model: str = ""
    max_budget_usd: float = 0.0

    def with_fallback(self, base: ProviderName) -> ExecutionProfile:
        """Return a copy with *provider* defaulting to *base* if unset."""
        if self.provider is not None:
            return self
        return self.model_copy(update={"provider": base})

    def is_zero(self) -> bool:
        return self == ExecutionProfile()


class RoleOverride(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    provider: ProviderName | None = None
    model: str = ""


class RoleProfiles(BaseModel):
    """Provider/model configuration for every role in the pipeline."""

    model_config = ConfigDict(use_enum_values=True)

    director: ExecutionProfile = Field(default_factory=ExecutionProfile)
    planner: ExecutionProfile = Field(default_factory=ExecutionProfile)
    leader: ExecutionProfile = Field(default_factory=ExecutionProfile)
    executor: ExecutionProfile = Field(default_factory=ExecutionProfile)
    reviewer: ExecutionProfile = Field(default_factory=ExecutionProfile)
    tester: ExecutionProfile = Field(default_factory=ExecutionProfile)
    evaluator: ExecutionProfile = Field(default_factory=ExecutionProfile)

    def normalize(self, base: ProviderName) -> RoleProfiles:
        director = _first_non_zero(self.director, self.planner, self.leader).with_fallback(base)
        planner = _first_non_zero(self.planner, self.director).with_fallback(base)
        leader = _first_non_zero(self.leader, self.director).with_fallback(base)
        executor = self.executor.with_fallback(base)
        reviewer = self.reviewer.with_fallback(base)
        tester = self.tester if not self.tester.is_zero() else self.executor
        tester = tester.with_fallback(base)
        evaluator = self.evaluator.with_fallback(base)
        return RoleProfiles(
            director=director,
            planner=planner,
            leader=leader,
            executor=executor,
            reviewer=reviewer,
            tester=tester,
            evaluator=evaluator,
        )

    def profile_for(self, role: RoleName, base: ProviderName) -> ExecutionProfile:
        director = _first_non_zero(self.director, self.leader, self.planner).with_fallback(base)
        match role:
            case RoleName.DIRECTOR:
                return director
            case RoleName.PLANNER:
                return _first_non_zero(self.planner, self.director, self.leader).with_fallback(base)
            case RoleName.LEADER:
                return _first_non_zero(self.leader, self.director, self.planner).with_fallback(base)
            case RoleName.EXECUTOR:
                return self.executor.with_fallback(base)
            case RoleName.REVIEWER:
                return self.reviewer.with_fallback(base)
            case RoleName.TESTER:
                return _first_non_zero(self.tester, self.executor).with_fallback(base)
            case RoleName.EVALUATOR:
                return self.evaluator.with_fallback(base)
            case _:
                return ExecutionProfile(provider=base)


def default_role_profiles(base: ProviderName) -> RoleProfiles:
    """Heavy reasoning roles get opus; execution roles get sonnet."""
    director = ExecutionProfile(provider=base, model="opus")
    executor = ExecutionProfile(provider=base, model="sonnet")
    return RoleProfiles(
        director=director,
        planner=director,
        leader=director,
        executor=executor,
        reviewer=ExecutionProfile(provider=base, model="sonnet"),
        tester=executor,
        evaluator=ExecutionProfile(provider=base, model="opus"),
    )


def _first_non_zero(*profiles: ExecutionProfile) -> ExecutionProfile:
    for p in profiles:
        if not p.is_zero():
            return p
    return ExecutionProfile()


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_pipeline_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized == PipelineMode.LIGHT:
        return PipelineMode.LIGHT
    if normalized == PipelineMode.FULL:
        return PipelineMode.FULL
    return PipelineMode.BALANCED


def normalize_ambition_level(level: str) -> str:
    normalized = level.strip().lower()
    try:
        return AmbitionLevel(normalized).value
    except ValueError:
        return AmbitionLevel.MEDIUM.value


def role_for_task_type(task_type: str) -> RoleName:
    """All task types currently route to executor."""
    return RoleName.EXECUTOR


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class SystemAction(BaseModel):
    type: SystemActionType
    command: str
    args: list[str] = Field(default_factory=list)
    workdir: str = ""
    description: str = ""


class PendingApproval(BaseModel):
    step_index: int
    reason: str
    requested_at: datetime
    target: str
    task_type: str
    task_text: str
    system_action: SystemAction | None = None


class WorkerTask(BaseModel):
    target: str
    task_type: str
    task_text: str
    artifacts: list[str] = Field(default_factory=list)
    reason: str = ""
    next_hint: str = ""


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class StructuredReason(BaseModel):
    category: str
    detail: str
    suggested_action: str


class ChangedFile(BaseModel):
    path: str
    action: str  # created, modified, deleted


class RubricAxis(BaseModel):
    name: str
    weight: float
    min_threshold: float


class AutomatedCheck(BaseModel):
    type: str  # grep, file_exists, file_unchanged, no_new_deps
    pattern: str = ""
    file: str = ""
    path: str = ""
    ref: str = ""
    description: str = ""


class AutomatedCheckResult(BaseModel):
    description: str
    status: str  # passed, failed, skipped
    detail: str = ""


class RubricScore(BaseModel):
    axis: str
    score: float
    passed: bool


class VerificationContract(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    version: int = 1
    goal: str = ""
    scope: list[str] = Field(default_factory=list)
    required_commands: list[str] = Field(default_factory=list)
    required_artifacts: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)
    disallowed_actions: list[str] = Field(default_factory=list)
    max_seconds: int = 0
    notes: str = ""
    owner_role: RoleName | None = None
    rubric_axes: list[RubricAxis] = Field(default_factory=list)
    automated_checks: list[AutomatedCheck] = Field(default_factory=list)


class VerificationReport(BaseModel):
    status: str
    passed: bool
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    missing_checks: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    contract_ref: str = ""


class EvaluatorReport(BaseModel):
    status: str
    passed: bool
    score: int = 0
    reason: str = ""
    missing_step_types: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    contract_ref: str = ""
    rubric_scores: list[RubricScore] = Field(default_factory=list)


class LeaderOutput(BaseModel):
    action: str
    target: str = ""
    task_type: str = ""
    task_text: str = ""
    artifacts: list[str] = Field(default_factory=list)
    reason: str = ""
    next_hint: str = ""
    system_action: SystemAction | None = None
    tasks: list[WorkerTask] = Field(default_factory=list)


class WorkerOutput(BaseModel):
    status: str
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)
    file_contents: dict[str, str] = Field(default_factory=dict)
    blocked_reason: str = ""
    error_reason: str = ""
    next_recommended_action: str = ""


class Event(BaseModel):
    time: datetime
    kind: str
    message: str


class ChainContext(BaseModel):
    summary: str = ""
    evaluator_report_ref: str = ""


class SprintContract(BaseModel):
    version: int = 1
    goal: str = ""
    required_step_types: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    blocking_criteria: list[str] = Field(default_factory=list)
    threshold_success_count: int = 0
    threshold_min_steps: int = 0
    threshold_require_eval: bool = False
    strictness_level: str = ""


class PlanningArtifact(BaseModel):
    goal: str = ""
    tech_stack: str = ""
    workspace_dir: str = ""
    summary: str = ""
    product_scope: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    proposed_steps: list[str] = Field(default_factory=list)
    invariants_to_preserve: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    success_signals: list[str] = Field(default_factory=list)
    verification_contract: VerificationContract | None = None
    recommended_strictness: str = ""
    recommended_max_steps: int = 0


class Step(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    index: int
    target: str
    task_type: str
    task_text: str
    status: StepStatus = StepStatus.PENDING
    summary: str = ""
    diff_summary: str = ""
    artifacts: list[str] = Field(default_factory=list)
    changed_files: list[ChangedFile] = Field(default_factory=list)
    blocked_reason: str = ""
    error_reason: str = ""
    structured_reason: StructuredReason | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    started_at: datetime = Field(default_factory=lambda: datetime.min)
    finished_at: datetime = Field(default_factory=lambda: datetime.min)


class ChainGoal(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    goal: str
    provider: ProviderName
    pipeline_mode: str = ""
    strictness_level: str = ""
    ambition_level: str = ""
    ambition_text: str = ""
    context_mode: str = ""
    max_steps: int = 10
    role_overrides: dict[str, RoleOverride] = Field(default_factory=dict)
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    pre_build_commands: list[str] = Field(default_factory=list)
    engine_build_cmd: str = ""
    engine_test_cmd: str = ""
    job_id: str = ""
    status: str = ChainGoalStatus.PENDING


class JobChain(BaseModel):
    id: str
    goals: list[ChainGoal] = Field(default_factory=list)
    current_index: int = 0
    status: str = ChainStatus.RUNNING
    created_at: datetime = Field(default_factory=lambda: datetime.min)
    updated_at: datetime = Field(default_factory=lambda: datetime.min)


class Job(BaseModel):
    """Central job model -- the orchestration unit of work."""

    model_config = ConfigDict(use_enum_values=True)

    id: str
    goal: str
    tech_stack: str = ""
    workspace_dir: str = ""
    requested_workspace_dir: str = ""
    workspace_mode: str = ""
    constraints: list[str] = Field(default_factory=list)
    done_criteria: list[str] = Field(default_factory=list)
    pipeline_mode: str = ""
    strictness_level: str = ""
    ambition_level: str = ""
    ambition_text: str = ""
    context_mode: str = ""
    role_profiles: RoleProfiles = Field(default_factory=RoleProfiles)
    role_overrides: dict[str, RoleOverride] = Field(default_factory=dict)
    verification_contract: VerificationContract | None = None
    verification_contract_ref: str = ""
    planning_artifacts: list[str] = Field(default_factory=list)
    sprint_contract_ref: str = ""
    evaluator_report_ref: str = ""
    chain_id: str = ""
    chain_goal_index: int = 0
    chain_context: ChainContext | None = None
    status: JobStatus = JobStatus.QUEUED
    provider: ProviderName = ProviderName.MOCK
    max_steps: int = 10
    current_step: int = 0
    retry_count: int = 0
    resume_extra_steps_used: int = 0
    blocked_reason: str = ""
    failure_reason: str = ""
    pending_approval: PendingApproval | None = None
    summary: str = ""
    leader_context_summary: str = ""
    supervisor_directive: str = ""
    pre_build_commands: list[str] = Field(default_factory=list)
    engine_build_cmd: str = ""
    engine_test_cmd: str = ""
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    schema_retry_hint: str = ""
    # pre_check_results is transient -- excluded from serialization
    pre_check_results: list[AutomatedCheckResult] = Field(
        default_factory=list, exclude=True
    )
    run_owner_id: str = ""
    run_heartbeat_at: datetime = Field(default_factory=lambda: datetime.min)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    steps: list[Step] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.min)
    updated_at: datetime = Field(default_factory=lambda: datetime.min)


# ---------------------------------------------------------------------------
# Terminal / recoverable state helpers
# ---------------------------------------------------------------------------

TERMINAL_STATUSES: frozenset[JobStatus] = frozenset({
    JobStatus.DONE,
    JobStatus.FAILED,
    JobStatus.BLOCKED,
})


def is_terminal(status: JobStatus) -> bool:
    return status in TERMINAL_STATUSES
