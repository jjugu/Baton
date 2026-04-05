"""Response DTOs (Pydantic models) for the HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from baton.domain.types import (
    EvaluatorReport,
    Job,
    JobStatus,
    ProviderName,
    RoleProfiles,
    SprintContract,
    VerificationContract,
)


class ArtifactView(BaseModel):
    name: str
    path: str
    kind: str = ""
    content: Any = None
    error: str = ""


class ParallelPolicyView(BaseModel):
    max_parallel_workers: int = 2
    approval_authority: str = "leader/orchestrator"
    scope_requirement: str = "disjoint write scope required"
    context_policy: list[str] = Field(default_factory=lambda: [
        "planner may propose parallel candidates",
        "leader authorizes worker fan-out",
        "executor cannot spawn workers on its own",
        "context must stay artifact-scoped and minimal",
    ])
    note: str = "runtime fan-out is implemented and enforced by the orchestrator"


class PlanningView(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    job_id: str
    goal: str
    tech_stack: str = ""
    workspace_dir: str = ""
    requested_workspace_dir: str = ""
    workspace_mode: str = ""
    provider: ProviderName
    sprint_contract_ref: str = ""
    planning_artifact_refs: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactView] = Field(default_factory=list)
    parallel_policy: ParallelPolicyView = Field(default_factory=ParallelPolicyView)


class EvaluatorView(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    job_id: str
    provider: ProviderName
    report_ref: str = ""
    report: EvaluatorReport | None = None
    error: str = ""


class VerificationView(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    job_id: str
    goal: str
    provider: ProviderName
    sprint_contract_ref: str = ""
    sprint_contract: SprintContract | None = None
    verification_contract_ref: str = ""
    verification_contract: VerificationContract | None = None
    evaluator_report_ref: str = ""
    evaluator_report: EvaluatorReport | None = None
    role_profiles: RoleProfiles | None = None
    derived_checks: list[str] = Field(default_factory=list)
    parallel_policy: ParallelPolicyView = Field(default_factory=ParallelPolicyView)
    note: str = ""


class ProfileView(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    job_id: str
    provider: ProviderName
    workspace_dir: str = ""
    requested_workspace_dir: str = ""
    workspace_mode: str = ""
    role_profiles_available: bool = True
    role_profiles: RoleProfiles | None = None
    parallel_policy: ParallelPolicyView = Field(default_factory=ParallelPolicyView)
    note: str = ""


class RuntimeProcessHandleView(BaseModel):
    pid: int
    name: str = ""
    command: str = ""
    status: str = ""


class RuntimeProcessListView(BaseModel):
    processes: list[RuntimeProcessHandleView] = Field(default_factory=list)
    note: str = ""


class RuntimeHarnessView(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    job_id: str
    goal: str
    status: JobStatus
    provider: ProviderName
    workspace_dir: str = ""
    step_count: int = 0
    event_count: int = 0
    pending_approval: bool = False
    process_count: int = 0
    processes: list[RuntimeProcessHandleView] = Field(default_factory=list)
    available: bool = True
    note: str = ""


# ---------------------------------------------------------------------------
# View builders (match Go Build*View functions)
# ---------------------------------------------------------------------------

def build_planning_view(job: Job) -> PlanningView:
    return PlanningView(
        job_id=job.id,
        goal=job.goal,
        tech_stack=job.tech_stack,
        workspace_dir=job.workspace_dir,
        requested_workspace_dir=job.requested_workspace_dir,
        workspace_mode=job.workspace_mode,
        provider=job.provider,
        sprint_contract_ref=job.sprint_contract_ref,
        planning_artifact_refs=list(job.planning_artifacts),
    )


def build_evaluator_view(job: Job) -> EvaluatorView:
    view = EvaluatorView(
        job_id=job.id,
        provider=job.provider,
        report_ref=job.evaluator_report_ref,
    )
    if not job.evaluator_report_ref.strip():
        view.error = "evaluator report is not available"
    return view


def build_verification_view(job: Job) -> VerificationView:
    return VerificationView(
        job_id=job.id,
        goal=job.goal,
        provider=job.provider,
        sprint_contract_ref=job.sprint_contract_ref,
        verification_contract_ref=job.verification_contract_ref,
        evaluator_report_ref=job.evaluator_report_ref,
        role_profiles=job.role_profiles,
        verification_contract=job.verification_contract,
        note="verification is a read-only contract derived from sprint contract, evaluator report, and role profiles",
    )


def build_profile_view(job: Job) -> ProfileView:
    return ProfileView(
        job_id=job.id,
        provider=job.provider,
        workspace_dir=job.workspace_dir,
        requested_workspace_dir=job.requested_workspace_dir,
        workspace_mode=job.workspace_mode,
        role_profiles_available=True,
        role_profiles=job.role_profiles,
        note="leader and worker routing use these persisted profiles",
    )
