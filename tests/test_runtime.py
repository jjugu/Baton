"""Cross-validate baton/runtime against Go runtime.

Tests:
- Category enum completeness
- ProcessState enum completeness
- Policy default allowlists match Go
- normalizeExecutable logic matches Go
- Result/ProcessHandle field completeness
"""
from __future__ import annotations

import sys

from baton.runtime.types import (
    Category,
    ProcessHandle,
    ProcessState,
    Request,
    Result,
    StartRequest,
)
from baton.runtime.policy import Policy, default_policy, _normalize_executable


# ---------------------------------------------------------------------------
# Category enum
# ---------------------------------------------------------------------------

class TestCategory:
    def test_values_match_go(self) -> None:
        go_values = {"build", "test", "lint", "search", "command"}
        py_values = {c.value for c in Category}
        assert py_values == go_values

    def test_count(self) -> None:
        assert len(Category) == 5


# ---------------------------------------------------------------------------
# ProcessState enum
# ---------------------------------------------------------------------------

class TestProcessState:
    def test_values_match_go(self) -> None:
        go_values = {"starting", "running", "stopped", "exited", "failed", "unknown"}
        py_values = {s.value for s in ProcessState}
        assert py_values == go_values

    def test_count(self) -> None:
        assert len(ProcessState) == 6


# ---------------------------------------------------------------------------
# Policy default allowlists
# ---------------------------------------------------------------------------

class TestDefaultPolicy:
    def test_build_allowlist(self) -> None:
        """Go: go, cargo, dotnet, make, cmake, mvn, gradle, npm, pnpm, yarn."""
        go_build = {"go", "cargo", "dotnet", "make", "cmake", "mvn", "gradle", "npm", "pnpm", "yarn"}
        p = default_policy()
        # Policy allows checks by not raising
        for cmd in go_build:
            p.allows(Category.BUILD, cmd)  # should not raise

    def test_test_allowlist(self) -> None:
        """Go: go, cargo, dotnet, pytest, npm, pnpm, yarn, python."""
        go_test = {"go", "cargo", "dotnet", "pytest", "npm", "pnpm", "yarn", "python"}
        p = default_policy()
        for cmd in go_test:
            p.allows(Category.TEST, cmd)

    def test_lint_allowlist(self) -> None:
        """Go: go, golangci-lint, eslint, prettier, ruff, black, mypy, flake8, cargo, dotnet."""
        go_lint = {"go", "golangci-lint", "eslint", "prettier", "ruff", "black", "mypy", "flake8", "cargo", "dotnet"}
        p = default_policy()
        for cmd in go_lint:
            p.allows(Category.LINT, cmd)

    def test_search_allowlist(self) -> None:
        """Go: rg, grep, git, findstr, select-string."""
        go_search = {"rg", "grep", "git", "findstr", "select-string"}
        p = default_policy()
        for cmd in go_search:
            p.allows(Category.SEARCH, cmd)

    def test_command_allowlist(self) -> None:
        """Go: go only (rg intentionally absent)."""
        p = default_policy()
        p.allows(Category.COMMAND, "go")  # should not raise

    def test_disallowed_command_raises(self) -> None:
        """rg is not in COMMAND category (only SEARCH)."""
        from baton.runtime.policy import PolicyError
        p = default_policy()
        import pytest
        with pytest.raises(PolicyError):
            p.allows(Category.COMMAND, "rg")


# ---------------------------------------------------------------------------
# normalizeExecutable
# ---------------------------------------------------------------------------

class TestNormalizeExecutable:
    def test_strips_path(self) -> None:
        assert _normalize_executable("/usr/local/bin/go") == "go"

    def test_lowercases(self) -> None:
        assert _normalize_executable("Go") == "go"

    def test_strips_exe(self) -> None:
        assert _normalize_executable("go.exe") == "go"

    def test_strips_cmd(self) -> None:
        assert _normalize_executable("npm.cmd") == "npm"

    def test_strips_bat(self) -> None:
        assert _normalize_executable("build.bat") == "build"

    def test_windows_path(self) -> None:
        result = _normalize_executable("C:\\Program Files\\Go\\bin\\go.exe")
        assert result == "go"


# ---------------------------------------------------------------------------
# Result field completeness
# ---------------------------------------------------------------------------

class TestResultFields:
    def test_matches_go(self) -> None:
        """Go Result: category, command, args, exit_code, stdout, stderr,
        started_at, finished_at, duration, timed_out, truncated_stdout, truncated_stderr."""
        go_fields = {
            "category", "command", "args", "exit_code", "stdout", "stderr",
            "started_at", "finished_at", "duration_seconds", "timed_out",
            "truncated_stdout", "truncated_stderr",
        }
        py_fields = set(Result.model_fields.keys())
        # Go uses "duration" (time.Duration); Python uses "duration_seconds" (float)
        # This is an intentional difference for Python idiomacy
        assert py_fields == go_fields


class TestProcessHandleFields:
    def test_matches_go(self) -> None:
        """Go ProcessHandle: pid, name, category, command, args, port,
        log_path, state, started_at, finished_at, exit_code, running, error."""
        go_fields = {
            "pid", "name", "category", "command", "args", "port",
            "log_path", "state", "started_at", "finished_at",
            "exit_code", "running", "error",
        }
        py_fields = set(ProcessHandle.model_fields.keys())
        assert py_fields == go_fields


class TestRequestFields:
    def test_has_expected_fields(self) -> None:
        """Go Request: Category, Command, Args, Dir, Env, Timeout, MaxOutputBytes."""
        # Python uses timeout_seconds (float) instead of Go's Timeout (time.Duration)
        go_fields = {"category", "command", "args", "dir", "env",
                     "timeout_seconds", "max_output_bytes"}
        py_fields = set(Request.model_fields.keys())
        assert py_fields == go_fields


class TestStartRequestFields:
    def test_extends_request(self) -> None:
        """Go StartRequest embeds Request + adds Name, LogDir, Port."""
        extra_fields = {"name", "log_dir", "port"}
        py_fields = set(StartRequest.model_fields.keys())
        assert extra_fields.issubset(py_fields)
        # Should also include all Request fields
        request_fields = set(Request.model_fields.keys())
        assert request_fields.issubset(py_fields)
