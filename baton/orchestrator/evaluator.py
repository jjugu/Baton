"""Evaluator -- completion gate logic.

The evaluateCompletion flow is the CORE INVARIANT of the engine:
done is NEVER reached without passing through this gate.
"""

from __future__ import annotations

import json

from baton.domain.types import (
    EvaluatorReport,
    Job,
    SprintContract,
    StepStatus,
)
from baton.orchestrator.verification import InternalVerificationContract


def merge_evaluator_report(
    job: Job,
    verification: InternalVerificationContract,
    sprint: SprintContract,
    provider_report: EvaluatorReport,
) -> EvaluatorReport:
    """Merge provider report with mechanical checks (sprint contract coverage)."""
    report = provider_report.model_copy()

    # Override status based on sprint contract coverage
    missing = missing_required_steps(job, sprint.required_step_types)
    if missing and report.passed:
        report.passed = False
        report.status = "failed"
        report.missing_step_types = missing
        if not report.reason:
            report.reason = f"missing required step types: {', '.join(missing)}"

    # Ensure threshold is met
    if sprint.threshold_min_steps > 0:
        succeeded = sum(1 for s in job.steps if s.status == StepStatus.SUCCEEDED)
        if succeeded < sprint.threshold_min_steps and report.passed:
            report.passed = False
            report.status = "failed"
            report.reason = f"only {succeeded} succeeded steps, need {sprint.threshold_min_steps}"

    # Enforce contract_ref
    if not report.contract_ref:
        report.contract_ref = job.sprint_contract_ref

    return report


def deterministic_evaluator_report(
    job: Job,
    verification: InternalVerificationContract,
    sprint: SprintContract,
) -> EvaluatorReport:
    """Build a mechanical evaluator report when no LLM evaluator is available."""
    missing = missing_required_steps(job, sprint.required_step_types)
    succeeded = sum(1 for s in job.steps if s.status == StepStatus.SUCCEEDED)
    total = max(len(sprint.required_step_types), 1)
    score = (total - len(missing)) * 100 // total

    if missing:
        return EvaluatorReport(
            status="failed",
            passed=False,
            score=score,
            reason=f"missing required step types: {', '.join(missing)}",
            missing_step_types=missing,
            evidence=_success_evidence(job),
            contract_ref=job.sprint_contract_ref,
        )

    return EvaluatorReport(
        status="passed",
        passed=True,
        score=score,
        reason="deterministic evaluator: all required step types succeeded",
        evidence=_success_evidence(job),
        contract_ref=job.sprint_contract_ref,
    )


def validate_evaluator_report(report: EvaluatorReport, job: Job) -> None:
    """Raise ValueError if the report violates schema constraints."""
    if report.status not in ("passed", "failed", "blocked"):
        raise ValueError(f"invalid evaluator status: {report.status!r}")


def apply_evaluator_job_state(job: Job, report: EvaluatorReport) -> None:
    """Update job fields based on evaluator report."""
    if report.passed:
        job.summary = report.reason
    else:
        job.blocked_reason = report.reason


def missing_required_steps(job: Job, required: list[str]) -> list[str]:
    seen = {s.task_type for s in job.steps if s.status == StepStatus.SUCCEEDED}
    return [r for r in required if r not in seen]


def successful_step_types(job: Job) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for s in job.steps:
        if s.status == StepStatus.SUCCEEDED and s.task_type not in seen:
            seen.add(s.task_type)
            result.append(s.task_type)
    return result


def _success_evidence(job: Job) -> list[str]:
    return [
        f"{s.target}:{s.task_type}"
        for s in job.steps
        if s.status == StepStatus.SUCCEEDED
    ]
