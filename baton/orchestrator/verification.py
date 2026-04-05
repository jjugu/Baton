"""Verification contract management.

Ported from gorchera/internal/orchestrator/verification.go.
"""

from __future__ import annotations

import json
from pathlib import Path

from baton.domain.types import (
    Job,
    PlanningArtifact,
    RubricAxis,
    SprintContract,
    VerificationContract,
)


class InternalVerificationContract:
    """Internal verification contract with extended metadata."""

    def __init__(
        self,
        *,
        version: int = 1,
        goal: str = "",
        summary: str = "",
        sprint_contract_ref: str = "",
        planning_artifact_refs: list[str] | None = None,
        required_step_types: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        engine_instructions: list[str] | None = None,
        evaluator_criteria: list[str] | None = None,
        rubric_axes: list[RubricAxis] | None = None,
    ):
        self.version = version
        self.goal = goal
        self.summary = summary
        self.sprint_contract_ref = sprint_contract_ref
        self.planning_artifact_refs = planning_artifact_refs or []
        self.required_step_types = required_step_types or []
        self.acceptance_criteria = acceptance_criteria or []
        self.engine_instructions = engine_instructions or []
        self.evaluator_criteria = evaluator_criteria or []
        self.rubric_axes = rubric_axes or []

    def to_dict(self) -> dict:
        d: dict = {
            "version": self.version,
            "goal": self.goal,
            "summary": self.summary,
            "sprint_contract_ref": self.sprint_contract_ref,
            "planning_artifact_refs": self.planning_artifact_refs,
            "required_step_types": self.required_step_types,
            "acceptance_criteria": self.acceptance_criteria,
            "engine_instructions": self.engine_instructions,
            "evaluator_criteria": self.evaluator_criteria,
        }
        if self.rubric_axes:
            d["rubric_axes"] = [a.model_dump() for a in self.rubric_axes]
        return d


def build_verification_contract(
    job: Job,
    planning: PlanningArtifact,
    sprint: SprintContract,
    artifact_refs: list[str],
) -> InternalVerificationContract:
    engine_instructions = [
        "Engine runs build and test commands after each successful implement step.",
        "Treat skipped engine checks as informational.",
        "Treat failed engine checks as unresolved regression evidence.",
    ]
    evaluator_criteria = [
        "latest successful implement step contains engine build/test evidence",
        "required step coverage matches the sprint contract",
        "review coverage matches the selected pipeline mode",
    ]
    goal = planning.goal or job.goal
    summary = _verification_summary(job, planning, sprint)
    return InternalVerificationContract(
        version=1,
        goal=goal,
        summary=summary,
        sprint_contract_ref=job.sprint_contract_ref,
        planning_artifact_refs=list(artifact_refs),
        required_step_types=list(sprint.required_step_types),
        acceptance_criteria=list(sprint.acceptance_criteria),
        engine_instructions=engine_instructions,
        evaluator_criteria=evaluator_criteria,
    )


def build_persisted_verification_contract(
    job: Job,
    planning: PlanningArtifact,
    sprint: SprintContract,
    contract: InternalVerificationContract,
    contract_path: str,
) -> VerificationContract:
    """Build the domain VerificationContract persisted on the job."""
    if planning.verification_contract is not None:
        cloned = planning.verification_contract.model_copy(deep=True)
        if not cloned.required_artifacts:
            cloned.required_artifacts = list(contract.planning_artifact_refs)
        if contract_path.strip():
            cloned.required_artifacts.append(contract_path)
        cloned.required_artifacts = _unique(cloned.required_artifacts)
        return cloned

    required_checks = list(contract.required_step_types) + list(contract.evaluator_criteria)
    required_artifacts = list(contract.planning_artifact_refs)
    if contract_path.strip():
        required_artifacts.append(contract_path)

    return VerificationContract(
        version=1,
        goal=contract.goal,
        scope=[],
        required_commands=[],
        required_artifacts=_unique(required_artifacts),
        required_checks=required_checks,
        disallowed_actions=[],
        max_seconds=0,
        notes=contract.summary,
    )


def verification_contract_prompt(contract: InternalVerificationContract, ref_path: str) -> str:
    return f"Verification contract ({ref_path}):\n{contract.summary}"


def verification_contract_path(job: Job) -> str:
    return job.verification_contract_ref or ""


def resolve_verification_contract(job: Job) -> tuple[InternalVerificationContract, str]:
    """Load the verification contract from disk if available."""
    ref = job.verification_contract_ref.strip()
    if not ref:
        raise FileNotFoundError("no verification contract ref")
    try:
        data = json.loads(Path(ref).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise FileNotFoundError(str(exc)) from exc
    return InternalVerificationContract(
        version=data.get("version", 1),
        goal=data.get("goal", ""),
        summary=data.get("summary", ""),
        sprint_contract_ref=data.get("sprint_contract_ref", ""),
        planning_artifact_refs=data.get("planning_artifact_refs", []),
        required_step_types=data.get("required_step_types", []),
        acceptance_criteria=data.get("acceptance_criteria", []),
        engine_instructions=data.get("engine_instructions", []),
        evaluator_criteria=data.get("evaluator_criteria", []),
    ), ref


def _verification_summary(job: Job, planning: PlanningArtifact, sprint: SprintContract) -> str:
    required = ", ".join(sprint.required_step_types) or "implement"
    summary = planning.summary or job.goal
    return f"Verify {summary} with required worker steps: {required} and engine-managed build/test evidence"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
