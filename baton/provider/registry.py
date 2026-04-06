"""Provider registry and session manager."""

from __future__ import annotations

from baton.domain.types import (
    ExecutionProfile,
    Job,
    LeaderOutput,
    ProviderName,
    RoleName,
    RoleProfiles,
    TokenUsage,
    role_for_task_type,
)
from baton.provider.base import Adapter, EvaluatorRunner, PlannerRunner
from baton.provider.errors import (
    ProviderError,
    is_fallback_eligible,
    unsupported_phase_error,
)


class Registry:
    """Maps provider names to adapter instances."""

    def __init__(self) -> None:
        self._adapters: dict[ProviderName, Adapter] = {}

    def register(self, adapter: Adapter) -> None:
        self._adapters[adapter.name()] = adapter

    def get(self, name: ProviderName) -> Adapter:
        adapter = self._adapters.get(name)
        if adapter is None:
            raise KeyError(f"provider {name!r} is not registered")
        return adapter


def new_registry() -> Registry:
    """Create a registry pre-loaded with codex and claude adapters."""
    from baton.provider.codex import CodexAdapter
    from baton.provider.claude import ClaudeAdapter

    reg = Registry()
    reg.register(CodexAdapter())
    reg.register(ClaudeAdapter())
    return reg


class SessionManager:
    """Resolves role -> adapter and handles fallback retry logic."""

    def __init__(self, registry: Registry) -> None:
        self._registry = registry
        self.last_token_usage: TokenUsage = TokenUsage()

    async def run_leader(self, job: Job) -> str:
        return await self._run_role(job, RoleName.LEADER, lambda a, j: a.run_leader(j))

    async def run_worker(self, job: Job, task: LeaderOutput) -> str:
        role = role_for_task_type(task.task_type)
        return await self._run_role(job, role, lambda a, j: a.run_worker(j, task))

    async def run_planner(self, job: Job) -> str:
        return await self._run_phase(job, RoleName.PLANNER, lambda a, j: _run_planner_phase(a, j))

    async def run_evaluator(self, job: Job) -> str:
        return await self._run_phase(job, RoleName.EVALUATOR, lambda a, j: _run_evaluator_phase(a, j))

    async def _run_role(self, job: Job, role: RoleName, invoke) -> str:
        return await self._run_with_resolved_profile(job, role, invoke)

    async def _run_phase(self, job: Job, role: RoleName, invoke) -> str:
        return await self._run_with_resolved_profile(job, role, invoke)

    async def _run_with_resolved_profile(self, job: Job, role: RoleName, invoke) -> str:
        effective_job, profile = self._resolve_job_for_role(job, role)
        adapter, used_fallback = self._adapter_for_profile_with_source(profile)
        try:
            result = await invoke(adapter, effective_job)
        except ProviderError as exc:
            if used_fallback or not _should_retry_with_fallback_model(profile, exc):
                raise
            retry_profile = profile.model_copy(update={"model": profile.fallback_model.strip()})
            effective_job = effective_job.model_copy(
                update={"role_profiles": _set_role_profile(effective_job.role_profiles, role, retry_profile)}
            )
            result = await invoke(adapter, effective_job)
        self.last_token_usage = getattr(adapter, "last_token_usage", TokenUsage())
        return result

    def _resolve_profile(self, job: Job, role: RoleName) -> ExecutionProfile:
        profile = job.role_profiles.profile_for(role, ProviderName.MOCK)
        override = job.role_overrides.get(role.value if isinstance(role, RoleName) else role)
        if override is not None:
            if override.provider is not None:
                profile = profile.model_copy(update={"provider": override.provider})
            if override.model.strip():
                profile = profile.model_copy(update={"model": override.model})
        if profile.provider is None:
            profile = profile.model_copy(update={"provider": job.provider})
        if profile.provider is None:
            profile = profile.model_copy(update={"provider": ProviderName.MOCK})
        return profile

    def _resolve_job_for_role(self, job: Job, role: RoleName) -> tuple[Job, ExecutionProfile]:
        profile = self._resolve_profile(job, role)
        updated_profiles = _set_role_profile(job.role_profiles, role, profile)
        return job.model_copy(update={"role_profiles": updated_profiles}), profile

    def _adapter_for_profile_with_source(self, profile: ExecutionProfile) -> tuple[Adapter, bool]:
        try:
            return self._registry.get(profile.provider), False
        except KeyError:
            pass
        if profile.fallback_provider and profile.fallback_provider != profile.provider:
            try:
                return self._registry.get(profile.fallback_provider), True
            except KeyError:
                pass
        raise KeyError(f"provider {profile.provider!r} is not registered")


async def _run_planner_phase(adapter: Adapter, job: Job) -> str:
    if isinstance(adapter, PlannerRunner):
        return await adapter.run_planner(job)
    raise unsupported_phase_error(adapter.name(), "", "planner")


async def _run_evaluator_phase(adapter: Adapter, job: Job) -> str:
    if isinstance(adapter, EvaluatorRunner):
        return await adapter.run_evaluator(job)
    raise unsupported_phase_error(adapter.name(), "", "evaluator")


def _should_retry_with_fallback_model(profile: ExecutionProfile, exc: ProviderError) -> bool:
    fallback = profile.fallback_model.strip()
    if not fallback or fallback == profile.model.strip():
        return False
    return is_fallback_eligible(exc.kind)


def _set_role_profile(profiles: RoleProfiles, role: RoleName, profile: ExecutionProfile) -> RoleProfiles:
    update_key = {
        RoleName.PLANNER: "planner",
        RoleName.LEADER: "leader",
        RoleName.EXECUTOR: "executor",
        RoleName.REVIEWER: "reviewer",
        RoleName.TESTER: "tester",
        RoleName.EVALUATOR: "evaluator",
    }.get(role)
    if update_key:
        return profiles.model_copy(update={update_key: profile})
    return profiles
