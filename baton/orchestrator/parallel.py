"""Parallel worker fan-out (max 2 workers)."""

from __future__ import annotations

from dataclasses import dataclass, field

from baton.domain.types import LeaderOutput, WorkerTask

MAX_PARALLEL_WORKERS = 2


@dataclass
class WorkerPlan:
    step_index: int = 0
    scope_key: str = ""
    task: LeaderOutput = field(default_factory=LeaderOutput)


def build_worker_plans(leader: LeaderOutput) -> list[WorkerPlan]:
    """Split a leader action into one or more worker plans.

    Raises ValueError on invalid parallel fan-out configurations.
    """
    if leader.action == "run_workers":
        return _build_from_tasks(leader.tasks)

    primary = WorkerPlan(
        scope_key=f"primary:{leader.target}:{leader.task_type}",
        task=LeaderOutput(
            action="run_worker",
            target=leader.target,
            task_type=leader.task_type,
            task_text=leader.task_text,
            artifacts=list(leader.artifacts),
        ),
    )
    return [primary]


def _build_from_tasks(tasks: list[WorkerTask]) -> list[WorkerPlan]:
    if not tasks:
        raise ValueError("parallel fan-out requires worker tasks")
    if len(tasks) > MAX_PARALLEL_WORKERS:
        raise ValueError(f"parallel fan-out exceeds max_parallel_workers={MAX_PARALLEL_WORKERS}")

    used_targets: set[str] = set()
    plans: list[WorkerPlan] = []
    for task in tasks:
        target = task.target.strip()
        if not target:
            raise ValueError("parallel fan-out requires target")
        normalized = target.lower()
        if normalized in used_targets:
            raise ValueError(f"parallel fan-out requires disjoint targets; duplicate target {target!r}")
        used_targets.add(normalized)
        plans.append(WorkerPlan(
            scope_key=f"parallel:{target}:{task.task_type}",
            task=LeaderOutput(
                action="run_worker",
                target=task.target,
                task_type=task.task_type,
                task_text=task.task_text,
                artifacts=list(task.artifacts),
                reason=task.reason,
                next_hint=task.next_hint,
            ),
        ))
    return plans
