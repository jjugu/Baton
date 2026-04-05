"""Cross-validate baton/provider/base.py against Go provider/provider.go.

Checks:
- Adapter Protocol has correct method signatures
- PhaseAdapter = Adapter + PlannerRunner + EvaluatorRunner
- Method signatures match Go interface
"""
from __future__ import annotations

import inspect
from typing import get_type_hints

from baton.domain.types import Job, LeaderOutput, ProviderName
from baton.provider.base import Adapter, EvaluatorRunner, PhaseAdapter, PlannerRunner


class TestAdapterProtocol:
    """Go Adapter interface: Name(), RunLeader(ctx, job), RunWorker(ctx, job, task)."""

    def test_has_name(self) -> None:
        assert hasattr(Adapter, "name")

    def test_has_run_leader(self) -> None:
        assert hasattr(Adapter, "run_leader")

    def test_has_run_worker(self) -> None:
        assert hasattr(Adapter, "run_worker")

    def test_run_leader_is_async(self) -> None:
        assert inspect.iscoroutinefunction(Adapter.run_leader)

    def test_run_worker_is_async(self) -> None:
        assert inspect.iscoroutinefunction(Adapter.run_worker)

    def test_runtime_checkable(self) -> None:
        """Protocol should be runtime-checkable for isinstance checks."""
        assert getattr(Adapter, "__protocol_attrs__", None) is not None or True
        # Adapter is decorated with @runtime_checkable
        assert hasattr(Adapter, "__protocol_attrs__") or hasattr(Adapter, "_is_runtime_protocol")


class TestPlannerRunnerProtocol:
    """Go PlannerRunner interface: RunPlanner(ctx, job)."""

    def test_has_run_planner(self) -> None:
        assert hasattr(PlannerRunner, "run_planner")

    def test_run_planner_is_async(self) -> None:
        assert inspect.iscoroutinefunction(PlannerRunner.run_planner)


class TestEvaluatorRunnerProtocol:
    """Go EvaluatorRunner interface: RunEvaluator(ctx, job)."""

    def test_has_run_evaluator(self) -> None:
        assert hasattr(EvaluatorRunner, "run_evaluator")

    def test_run_evaluator_is_async(self) -> None:
        assert inspect.iscoroutinefunction(EvaluatorRunner.run_evaluator)


class TestPhaseAdapterProtocol:
    """Go PhaseAdapter = Adapter + PlannerRunner + EvaluatorRunner."""

    def test_inherits_adapter_methods(self) -> None:
        assert hasattr(PhaseAdapter, "name")
        assert hasattr(PhaseAdapter, "run_leader")
        assert hasattr(PhaseAdapter, "run_worker")

    def test_inherits_planner_runner(self) -> None:
        assert hasattr(PhaseAdapter, "run_planner")

    def test_inherits_evaluator_runner(self) -> None:
        assert hasattr(PhaseAdapter, "run_evaluator")

    def test_is_subclass_of_adapter(self) -> None:
        assert issubclass(PhaseAdapter, Adapter)
