"""Provider adapter protocols.

Defines the async interface that every provider (codex, claude, mock) must
implement. Ported from gorchera/internal/provider/provider.go using
Python Protocol classes instead of Go interfaces.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from baton.domain.types import Job, LeaderOutput, ProviderName


@runtime_checkable
class Adapter(Protocol):
    """Base adapter -- every provider must support leader + worker phases."""

    def name(self) -> ProviderName: ...
    async def run_leader(self, job: Job) -> str: ...
    async def run_worker(self, job: Job, task: LeaderOutput) -> str: ...


@runtime_checkable
class PlannerRunner(Protocol):
    async def run_planner(self, job: Job) -> str: ...


@runtime_checkable
class EvaluatorRunner(Protocol):
    async def run_evaluator(self, job: Job) -> str: ...


@runtime_checkable
class PhaseAdapter(Adapter, PlannerRunner, EvaluatorRunner, Protocol):
    """Full adapter supporting all four phases (leader, worker, planner, evaluator)."""
    ...
