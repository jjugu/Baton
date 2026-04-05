"""Planning phase -- planner execution, artifact building, sprint contracts."""

from __future__ import annotations

import json

from baton.domain.types import (
    Job,
    PlanningArtifact,
    SprintContract,
    VerificationContract,
)


def build_planning_artifact(job: Job, seed: PlanningArtifact | None = None) -> PlanningArtifact:
    """Construct a PlanningArtifact from job defaults and optional planner output."""
    invariants = list(job.constraints)
    if seed and seed.invariants_to_preserve:
        invariants.extend(seed.invariants_to_preserve)

    return PlanningArtifact(
        goal=(seed.goal if seed and seed.goal else job.goal),
        tech_stack=(seed.tech_stack if seed and seed.tech_stack else job.tech_stack),
        workspace_dir=(seed.workspace_dir if seed and seed.workspace_dir else job.workspace_dir),
        summary=_planning_summary(job, seed),
        product_scope=list(seed.product_scope) if seed and seed.product_scope else [],
        non_goals=list(seed.non_goals) if seed and seed.non_goals else [],
        proposed_steps=list(seed.proposed_steps) if seed and seed.proposed_steps else [],
        invariants_to_preserve=_unique(invariants),
        acceptance=list(job.done_criteria),
        success_signals=list(seed.success_signals) if seed and seed.success_signals else [],
        verification_contract=seed.verification_contract.model_copy(deep=True) if seed and seed.verification_contract else None,
    )


def build_sprint_contract(job: Job, planning: PlanningArtifact) -> SprintContract:
    """Build a sprint contract from a planning artifact."""
    required = ["implement"]
    # Use proposed steps as hints for required types
    for step in planning.proposed_steps:
        step_lower = step.lower()
        if "review" in step_lower and "review" not in required:
            required.append("review")
        if "test" in step_lower and "test" not in required:
            required.append("test")

    strictness = job.strictness_level.strip().lower() or "normal"
    threshold_success = max(len(required), 1)
    threshold_min_steps = max(len(required), 1)
    threshold_require_eval = strictness != "lenient"

    return SprintContract(
        version=1,
        goal=planning.goal or job.goal,
        required_step_types=required,
        acceptance_criteria=list(planning.acceptance),
        blocking_criteria=[],
        threshold_success_count=threshold_success,
        threshold_min_steps=threshold_min_steps,
        threshold_require_eval=threshold_require_eval,
        strictness_level=strictness,
    )


def validate_planning_artifact(artifact: PlanningArtifact, job: Job) -> None:
    """Raise ValueError if the artifact is invalid."""
    if not artifact.goal.strip():
        raise ValueError("planning artifact goal is empty")
    if not artifact.summary.strip():
        raise ValueError("planning artifact summary is empty")


def planning_markdown(plan: PlanningArtifact) -> str:
    """Render a planning artifact as markdown."""
    lines = [
        "# Product Spec",
        "",
        f"Goal: {plan.goal}",
        "",
        "## Scope",
    ]
    for item in plan.product_scope:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Non-Goals")
    for item in plan.non_goals:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Steps")
    for i, step in enumerate(plan.proposed_steps, 1):
        lines.append(f"{i}. {step}")
    lines.append("")
    lines.append("## Acceptance Criteria")
    for item in plan.acceptance:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Invariants")
    for item in plan.invariants_to_preserve:
        lines.append(f"- {item}")
    lines.append("")
    if plan.verification_contract:
        lines.append("## Verification Contract")
        lines.append(f"Goal: {plan.verification_contract.goal}")
        for check in plan.verification_contract.required_checks:
            lines.append(f"- {check}")
    return "\n".join(lines)


def _planning_summary(job: Job, seed: PlanningArtifact | None) -> str:
    if seed and seed.summary:
        return seed.summary
    return f"Plan for {job.goal}"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
