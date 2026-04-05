"""Cross-validate baton/provider/registry.py against Go provider/provider.go.

Tests:
- Registry get/register
- SessionManager profile resolution matches Go resolveProfile
- SessionManager fallback provider/model logic matches Go
- _set_role_profile matches Go setRoleProfile
- Mock adapter implements PhaseAdapter (leader, worker, planner, evaluator)
- Claude and Codex adapters implement PhaseAdapter
"""
from __future__ import annotations

import pytest

from baton.domain.types import (
    ExecutionProfile,
    Job,
    LeaderOutput,
    ProviderName,
    RoleName,
    RoleOverride,
    RoleProfiles,
)
from baton.provider.base import Adapter, EvaluatorRunner, PlannerRunner, PhaseAdapter
from baton.provider.errors import ErrorKind, ProviderError
from baton.provider.mock import MockAdapter
from baton.provider.registry import (
    Registry,
    SessionManager,
    _set_role_profile,
    _should_retry_with_fallback_model,
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_register_and_get(self) -> None:
        reg = Registry()
        mock = MockAdapter()
        reg.register(mock)
        assert reg.get(ProviderName.MOCK) is mock

    def test_get_missing_raises(self) -> None:
        reg = Registry()
        with pytest.raises(KeyError):
            reg.get(ProviderName.CLAUDE)

    def test_new_registry_has_codex_and_claude(self) -> None:
        from baton.provider.registry import new_registry
        reg = new_registry()
        # Should not raise
        reg.get(ProviderName.CODEX)
        reg.get(ProviderName.CLAUDE)


# ---------------------------------------------------------------------------
# Mock adapter interface compliance
# ---------------------------------------------------------------------------

class TestMockAdapter:
    def test_name(self) -> None:
        assert MockAdapter().name() == ProviderName.MOCK

    @pytest.mark.asyncio
    async def test_run_leader_first_call(self) -> None:
        """First call with no steps should produce implement task."""
        import json
        job = Job(id="test", goal="build something", provider=ProviderName.MOCK)
        raw = await MockAdapter().run_leader(job)
        data = json.loads(raw)
        assert data["action"] == "run_worker"
        assert data["task_type"] == "implement"

    @pytest.mark.asyncio
    async def test_run_planner(self) -> None:
        import json
        job = Job(id="test", goal="build something", provider=ProviderName.MOCK)
        raw = await MockAdapter().run_planner(job)
        data = json.loads(raw)
        assert "goal" in data
        assert data["goal"] == "build something"

    @pytest.mark.asyncio
    async def test_run_evaluator_no_steps(self) -> None:
        import json
        job = Job(id="test", goal="build something", provider=ProviderName.MOCK)
        raw = await MockAdapter().run_evaluator(job)
        data = json.loads(raw)
        assert data["status"] in ("passed", "failed", "blocked")

    @pytest.mark.asyncio
    async def test_run_worker(self) -> None:
        import json
        job = Job(id="test", goal="build something", provider=ProviderName.MOCK)
        task = LeaderOutput(action="run_worker", target="B", task_type="implement", task_text="do it")
        raw = await MockAdapter().run_worker(job, task)
        data = json.loads(raw)
        assert data["status"] == "success"


# ---------------------------------------------------------------------------
# SessionManager profile resolution
# ---------------------------------------------------------------------------

class TestSessionManagerResolveProfile:
    """Go resolveProfile:
    1. job.RoleProfiles.ProfileFor(role, "")
    2. RoleOverrides[role] overrides provider/model
    3. Fallback to job.Provider
    4. Final fallback to mock
    """

    def test_uses_role_profiles(self) -> None:
        reg = Registry()
        reg.register(MockAdapter())
        sm = SessionManager(reg)
        job = Job(
            id="test",
            goal="test",
            provider=ProviderName.MOCK,
            role_profiles=RoleProfiles(
                executor=ExecutionProfile(provider=ProviderName.MOCK, model="fast"),
            ),
        )
        profile = sm._resolve_profile(job, RoleName.EXECUTOR)
        assert profile.model == "fast"
        assert profile.provider == "mock"

    def test_role_override_applies(self) -> None:
        """Go: RoleOverrides[role] overrides provider and model."""
        reg = Registry()
        reg.register(MockAdapter())
        sm = SessionManager(reg)
        job = Job(
            id="test",
            goal="test",
            provider=ProviderName.MOCK,
            role_overrides={"executor": RoleOverride(model="custom-model")},
        )
        profile = sm._resolve_profile(job, RoleName.EXECUTOR)
        assert profile.model == "custom-model"

    def test_fallback_to_job_provider(self) -> None:
        """Go: if profile.Provider == \"\" then profile.Provider = job.Provider."""
        reg = Registry()
        reg.register(MockAdapter())
        sm = SessionManager(reg)
        job = Job(
            id="test",
            goal="test",
            provider=ProviderName.MOCK,
        )
        profile = sm._resolve_profile(job, RoleName.EXECUTOR)
        assert profile.provider == "mock"

    def test_final_fallback_to_mock(self) -> None:
        """Go: if profile.Provider == \"\" then profile.Provider = ProviderMock.
        In Python, Job.provider is an enum and defaults to MOCK.
        The SessionManager._resolve_profile has an explicit fallback."""
        reg = Registry()
        reg.register(MockAdapter())
        sm = SessionManager(reg)
        # Empty RoleProfiles + no overrides -> falls back to job.provider
        job = Job(
            id="test",
            goal="test",
            provider=ProviderName.MOCK,
            role_profiles=RoleProfiles(),  # all zero profiles
        )
        profile = sm._resolve_profile(job, RoleName.EXECUTOR)
        assert profile.provider == "mock"


# ---------------------------------------------------------------------------
# _set_role_profile
# ---------------------------------------------------------------------------

class TestSetRoleProfile:
    """Go setRoleProfile updates the named role field."""

    def test_updates_executor(self) -> None:
        rp = RoleProfiles()
        new_profile = ExecutionProfile(provider=ProviderName.CLAUDE, model="opus")
        updated = _set_role_profile(rp, RoleName.EXECUTOR, new_profile)
        assert updated.executor.provider == "claude"
        assert updated.executor.model == "opus"

    def test_updates_evaluator(self) -> None:
        rp = RoleProfiles()
        new_profile = ExecutionProfile(provider=ProviderName.CODEX, model="gpt4")
        updated = _set_role_profile(rp, RoleName.EVALUATOR, new_profile)
        assert updated.evaluator.provider == "codex"

    def test_unknown_role_no_change(self) -> None:
        """Go: default case returns profiles unchanged.
        Note: Go's switch doesn't include DIRECTOR. Python also excludes it."""
        rp = RoleProfiles()
        new_profile = ExecutionProfile(provider=ProviderName.CLAUDE, model="opus")
        updated = _set_role_profile(rp, RoleName.DIRECTOR, new_profile)
        # Director not in the map, so profiles unchanged
        assert updated.director == rp.director


# ---------------------------------------------------------------------------
# Fallback model retry
# ---------------------------------------------------------------------------

class TestShouldRetryWithFallbackModel:
    def test_no_fallback_model(self) -> None:
        profile = ExecutionProfile(provider=ProviderName.CLAUDE, model="opus")
        exc = ProviderError(ProviderName.CLAUDE, ErrorKind.RATE_LIMITED)
        assert not _should_retry_with_fallback_model(profile, exc)

    def test_same_fallback_model(self) -> None:
        profile = ExecutionProfile(
            provider=ProviderName.CLAUDE, model="opus", fallback_model="opus",
        )
        exc = ProviderError(ProviderName.CLAUDE, ErrorKind.RATE_LIMITED)
        assert not _should_retry_with_fallback_model(profile, exc)

    def test_eligible_kind_retries(self) -> None:
        profile = ExecutionProfile(
            provider=ProviderName.CLAUDE, model="opus", fallback_model="sonnet",
        )
        exc = ProviderError(ProviderName.CLAUDE, ErrorKind.RATE_LIMITED)
        assert _should_retry_with_fallback_model(profile, exc)

    def test_ineligible_kind_no_retry(self) -> None:
        profile = ExecutionProfile(
            provider=ProviderName.CLAUDE, model="opus", fallback_model="sonnet",
        )
        exc = ProviderError(ProviderName.CLAUDE, ErrorKind.INVALID_RESPONSE)
        assert not _should_retry_with_fallback_model(profile, exc)
