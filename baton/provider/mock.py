"""Mock provider adapter for testing.

Ported from gorchera/internal/provider/mock/mock.go.
Deterministic responses that exercise the state machine without real LLM calls.
"""

from __future__ import annotations

import json

from baton.domain.types import (
    EvaluatorReport,
    Job,
    LeaderOutput,
    PlanningArtifact,
    ProviderName,
    RoleName,
    StepStatus,
    VerificationContract,
    WorkerOutput,
    WorkerTask,
)
from baton.provider.base import PhaseAdapter


class MockAdapter:
    """Deterministic test adapter that walks through implement->search->test->complete."""

    def name(self) -> ProviderName:
        return ProviderName.MOCK

    async def run_leader(self, job: Job) -> str:
        last_status = ""
        last_type = ""
        if job.steps:
            last = job.steps[-1]
            last_status = last.status
            last_type = last.task_type

        if last_status == StepStatus.BLOCKED:
            out = LeaderOutput(
                action="blocked",
                target="none",
                task_type="none",
                reason=f"worker blocked during {last_type}",
            )
        elif last_status == StepStatus.FAILED:
            out = LeaderOutput(
                action="fail",
                target="none",
                task_type="none",
                reason=f"worker failed during {last_type}",
            )
        elif not job.steps and "parallel" in job.goal.lower():
            out = LeaderOutput(
                action="run_workers",
                tasks=[
                    WorkerTask(
                        target="B",
                        task_type="implement",
                        task_text="Create the parallel execution scaffolding.",
                        artifacts=["parallel_execution_plan.md"],
                        next_hint="Return a compact implementation summary.",
                    ),
                    WorkerTask(
                        target="C",
                        task_type="search",
                        task_text="Search for policy and schema regression risks.",
                        artifacts=["search_notes.md"],
                        next_hint="Return search findings.",
                    ),
                ],
                reason="parallel fan-out is appropriate for the initial goal",
            )
        elif not _has_succeeded(job, "implement"):
            out = LeaderOutput(
                action="run_worker",
                target="B",
                task_type="implement",
                task_text="Create the initial implementation skeleton.",
                artifacts=["project_summary.md"],
                next_hint="Return implementation artifacts and a concise summary.",
            )
        elif not _has_succeeded(job, "search"):
            out = LeaderOutput(
                action="run_worker",
                target="C",
                task_type="search",
                task_text="Search codebase for integration points.",
                artifacts=["patch.diff", "implementation_notes.md"],
                next_hint="Return search findings.",
            )
        elif not _has_succeeded(job, "test"):
            out = LeaderOutput(
                action="run_worker",
                target="D",
                task_type="test",
                task_text="Run the designated validation checks.",
                artifacts=["review_report.json"],
                next_hint="Return test status and artifact references.",
            )
        else:
            out = LeaderOutput(
                action="complete",
                target="none",
                task_type="none",
                reason="mock provider completed implement, search, and test phases",
            )
        return out.model_dump_json()

    async def run_planner(self, job: Job) -> str:
        plan = PlanningArtifact(
            goal=job.goal,
            tech_stack=job.tech_stack,
            workspace_dir=job.workspace_dir,
            summary=f"planner prepared a plan for {job.goal!r}",
            product_scope=[
                "stateful multi-agent orchestration core",
                "planner, evaluator, and worker phase separation",
                "role-based execution profiles for provider selection",
            ],
            non_goals=[
                "interactive assistant UX",
                "unguarded autonomous writes",
            ],
            proposed_steps=[
                "draft product spec",
                "define sprint contract",
                "execute implementation loop",
                "gate completion on evaluator",
            ],
            acceptance=list(job.done_criteria),
            success_signals=[
                "planner artifact is persisted",
                "leader and worker phases can consume the result",
            ],
            verification_contract=VerificationContract(
                version=1,
                goal=job.goal,
                scope=["implementation", "review", "test"],
                required_commands=["go test ./..."],
                required_artifacts=["planner artifact", "sprint contract", "evaluator report"],
                required_checks=[
                    "job reached done only after evaluator pass",
                    "tester followed verification contract",
                ],
                disallowed_actions=["uncontracted completion", "unreviewed skip"],
                max_seconds=300,
                notes="tester must report evidence, not self-approve",
                owner_role=RoleName.TESTER,
            ),
        )
        return plan.model_dump_json()

    async def run_evaluator(self, job: Job) -> str:
        missing = _missing_required(job)
        ver_reason = "verification contract not provided"
        if job.verification_contract is not None:
            ver_reason = f"verification contract checks: {len(job.verification_contract.required_checks)}"

        report = EvaluatorReport(
            status="blocked",
            passed=False,
            score=_score_from_missing(job, missing),
            reason=f"missing required step coverage: {', '.join(missing)}; {ver_reason}",
            missing_step_types=missing,
            evidence=_success_evidence(job),
            contract_ref=job.sprint_contract_ref,
        )
        if not missing:
            report.status = "passed"
            report.passed = True
            report.reason = "mock evaluator confirmed required step coverage and verification contract"

        return report.model_dump_json()

    async def run_worker(self, job: Job, task: LeaderOutput) -> str:
        out = WorkerOutput(
            status="success",
            summary=f"{task.task_type} completed for goal {job.goal!r}",
            next_recommended_action=_next_action(task.task_type),
        )
        match task.task_type:
            case "implement":
                out.artifacts = ["patch.diff", "implementation_notes.md"]
            case "search":
                out.artifacts = ["search_report.json"]
            case "test":
                out.artifacts = ["test_report.json", "verification_evidence.json"]
                if job.verification_contract is not None:
                    out.summary = f"{task.task_type} followed {len(job.verification_contract.required_checks)} verification checks"
            case _:
                out.artifacts = ["worker_output.json"]
        return out.model_dump_json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_succeeded(job: Job, task_type: str) -> bool:
    return any(
        s.task_type == task_type and s.status == StepStatus.SUCCEEDED
        for s in job.steps
    )


def _next_action(task_type: str) -> str:
    if task_type == "implement":
        return "search"
    if task_type == "search":
        return "test"
    return "complete"


def _missing_required(job: Job) -> list[str]:
    required = ["implement", "search", "test"]
    seen = {s.task_type for s in job.steps if s.status == StepStatus.SUCCEEDED}
    return [r for r in required if r not in seen]


def _score_from_missing(job: Job, missing: list[str]) -> int:
    total = 3
    if total == 0:
        return 0
    return (total - len(missing)) * 100 // total


def _success_evidence(job: Job) -> list[str]:
    return [
        f"{s.target}:{s.task_type}"
        for s in job.steps
        if s.status == StepStatus.SUCCEEDED
    ]
