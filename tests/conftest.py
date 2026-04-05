"""Common pytest fixtures for baton test suite.

Provides reference data so every test module can
cross-validate Python implementations against the canonical baton types.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Go-canonical enum values (single source of truth for cross-validation)
# ---------------------------------------------------------------------------

GO_JOB_STATUSES = frozenset({
    "queued",
    "starting",
    "planning",
    "running",
    "waiting_leader",
    "waiting_worker",
    "blocked",
    "failed",
    "done",
})

GO_STEP_STATUSES = frozenset({
    "pending",
    "active",
    "succeeded",
    "blocked",
    "failed",
    "skipped",
})

GO_PROVIDER_NAMES = frozenset({
    "mock",
    "codex",
    "claude",
})

GO_ROLE_NAMES = frozenset({
    "director",
    "planner",
    "leader",
    "executor",
    "reviewer",
    "tester",
    "evaluator",
})

GO_AMBITION_LEVELS = frozenset({
    "low",
    "medium",
    "high",
    "extreme",
    "custom",
})

GO_PIPELINE_MODES = frozenset({
    "light",
    "balanced",
    "full",
})

GO_WORKSPACE_MODES = frozenset({
    "shared",
    "isolated",
})

GO_SYSTEM_ACTION_TYPES = frozenset({
    "search",
    "build",
    "test",
    "lint",
    "command",
})

GO_CHAIN_GOAL_STATUSES = frozenset({
    "pending",
    "running",
    "done",
    "failed",
    "skipped",
})

GO_CHAIN_STATUSES = frozenset({
    "running",
    "paused",
    "done",
    "failed",
    "cancelled",
})

GO_ERROR_KINDS = frozenset({
    "missing_executable",
    "probe_failed",
    "command_failed",
    "invalid_response",
    "unsupported_phase",
    "auth_failure",
    "quota_exceeded",
    "rate_limited",
    "billing_required",
    "session_expired",
    "network_error",
    "transport_error",
})

GO_ERROR_ACTIONS = frozenset({
    "retry",
    "block",
    "fail",
})

# ErrorKind -> recommended action mapping from Go errors.go
GO_ERROR_ACTION_MAP: dict[str, str] = {
    "rate_limited": "retry",
    "network_error": "retry",
    "auth_failure": "block",
    "billing_required": "block",
    "session_expired": "block",
    "quota_exceeded": "fail",
    "transport_error": "fail",
    "missing_executable": "fail",
    "probe_failed": "fail",
    "command_failed": "fail",
    "invalid_response": "fail",
    "unsupported_phase": "fail",
}

# Leader action enum from protocol.go leaderSchema
GO_LEADER_ACTIONS = frozenset({
    "run_worker",
    "run_workers",
    "run_system",
    "summarize",
    "complete",
    "fail",
    "blocked",
})

# Worker output status enum from protocol.go workerSchema
GO_WORKER_STATUSES = frozenset({
    "success",
    "failed",
    "blocked",
})

# Evaluator status enum from protocol.go evaluatorSchema
GO_EVALUATOR_STATUSES = frozenset({
    "passed",
    "failed",
    "blocked",
})

# MCP tool names (18 tools)
MCP_TOOL_NAMES = [
    "baton_start_job",
    "baton_start_chain",
    "baton_list_jobs",
    "baton_status",
    "baton_chain_status",
    "baton_pause_chain",
    "baton_resume_chain",
    "baton_cancel_chain",
    "baton_skip_chain_goal",
    "baton_events",
    "baton_artifacts",
    "baton_approve",
    "baton_reject",
    "baton_retry",
    "baton_cancel",
    "baton_resume",
    "baton_steer",
    "baton_diff",
]

# Backward-compat aliases
GO_MCP_TOOL_NAMES = MCP_TOOL_NAMES
BATON_MCP_TOOL_NAMES = MCP_TOOL_NAMES

# API endpoints from api/server.go
GO_API_ENDPOINTS = [
    ("GET", "/healthz"),
    ("GET", "/jobs"),
    ("POST", "/jobs"),
    ("GET", "/jobs/{job_id}"),
    ("POST", "/jobs/{job_id}/resume"),
    ("POST", "/jobs/{job_id}/approve"),
    ("POST", "/jobs/{job_id}/retry"),
    ("POST", "/jobs/{job_id}/reject"),
    ("POST", "/jobs/{job_id}/cancel"),
    ("POST", "/jobs/{job_id}/steer"),
    ("GET", "/jobs/{job_id}/events"),
    ("GET", "/jobs/{job_id}/events/stream"),
    ("GET", "/jobs/{job_id}/artifacts"),
    ("GET", "/jobs/{job_id}/verification"),
    ("GET", "/jobs/{job_id}/planning"),
    ("GET", "/jobs/{job_id}/evaluator"),
    ("GET", "/jobs/{job_id}/profile"),
    ("GET", "/chains"),
    ("POST", "/chains"),
    ("GET", "/chains/{chain_id}"),
    ("POST", "/harness"),
    ("GET", "/harness"),
]

# Provider Adapter interface methods from provider.go
GO_ADAPTER_METHODS = frozenset({
    "name",
    "run_leader",
    "run_worker",
})

GO_PHASE_ADAPTER_METHODS = GO_ADAPTER_METHODS | frozenset({
    "run_planner",
    "run_evaluator",
})

# Job fields from types.go Job struct (json tag names)
GO_JOB_FIELDS = frozenset({
    "id",
    "goal",
    "tech_stack",
    "workspace_dir",
    "requested_workspace_dir",
    "workspace_mode",
    "constraints",
    "done_criteria",
    "pipeline_mode",
    "strictness_level",
    "ambition_level",
    "ambition_text",
    "context_mode",
    "role_profiles",
    "role_overrides",
    "verification_contract",
    "verification_contract_ref",
    "planning_artifacts",
    "sprint_contract_ref",
    "evaluator_report_ref",
    "chain_id",
    "chain_goal_index",
    "chain_context",
    "status",
    "provider",
    "max_steps",
    "current_step",
    "retry_count",
    "resume_extra_steps_used",
    "blocked_reason",
    "failure_reason",
    "pending_approval",
    "summary",
    "leader_context_summary",
    "supervisor_directive",
    "pre_build_commands",
    "engine_build_cmd",
    "engine_test_cmd",
    "prompt_overrides",
    "schema_retry_hint",
    "run_owner_id",
    "run_heartbeat_at",
    "token_usage",
    "steps",
    "events",
    "created_at",
    "updated_at",
})

# Valid state transitions (from -> to) derived from service.go
# These are the transitions the orchestrator is known to make.
GO_STATE_TRANSITIONS: set[tuple[str, str]] = {
    # prepareJob sets starting
    ("starting", "planning"),
    ("starting", "running"),
    ("starting", "blocked"),
    ("starting", "failed"),
    # planning phase
    ("planning", "running"),
    ("planning", "blocked"),
    ("planning", "failed"),
    # running -> leader dispatch
    ("running", "waiting_leader"),
    ("running", "blocked"),
    ("running", "failed"),
    ("running", "done"),
    # leader returned
    ("waiting_leader", "running"),
    ("waiting_leader", "waiting_worker"),
    ("waiting_leader", "blocked"),
    ("waiting_leader", "failed"),
    ("waiting_leader", "done"),
    # worker returned
    ("waiting_worker", "running"),
    ("waiting_worker", "waiting_leader"),
    ("waiting_worker", "blocked"),
    ("waiting_worker", "failed"),
    # blocked/failed recovery
    ("blocked", "running"),
    ("blocked", "waiting_leader"),
    ("blocked", "starting"),
    ("blocked", "failed"),
    # failed -> retry
    ("failed", "starting"),
    ("failed", "running"),
    ("failed", "waiting_leader"),
}

# Terminal job statuses
GO_TERMINAL_STATUSES = frozenset({"done", "failed", "blocked"})

# Recoverable (non-terminal running) statuses
GO_RECOVERABLE_STATUSES = frozenset({
    "starting",
    "planning",
    "running",
    "waiting_leader",
    "waiting_worker",
})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def go_job_statuses() -> frozenset[str]:
    return GO_JOB_STATUSES


@pytest.fixture()
def go_step_statuses() -> frozenset[str]:
    return GO_STEP_STATUSES


@pytest.fixture()
def go_error_kinds() -> frozenset[str]:
    return GO_ERROR_KINDS


@pytest.fixture()
def go_error_action_map() -> dict[str, str]:
    return dict(GO_ERROR_ACTION_MAP)


@pytest.fixture()
def go_mcp_tool_names() -> list[str]:
    return list(GO_MCP_TOOL_NAMES)


@pytest.fixture()
def baton_mcp_tool_names() -> list[str]:
    return list(BATON_MCP_TOOL_NAMES)


@pytest.fixture()
def go_api_endpoints() -> list[tuple[str, str]]:
    return list(GO_API_ENDPOINTS)


@pytest.fixture()
def go_leader_actions() -> frozenset[str]:
    return GO_LEADER_ACTIONS


@pytest.fixture()
def go_job_fields() -> frozenset[str]:
    return GO_JOB_FIELDS


@pytest.fixture()
def go_state_transitions() -> set[tuple[str, str]]:
    return set(GO_STATE_TRANSITIONS)


@pytest.fixture(scope="session")
def tmp_workspace(tmp_path_factory: pytest.TempPathFactory):
    """Session-scoped temporary workspace directory."""
    return tmp_path_factory.mktemp("baton_workspace")
