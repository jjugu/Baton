"""Runtime command allowlist policy.

Ported from gorchera/internal/runtime/policy.go.
"""

from __future__ import annotations

import os
import sys
from pathlib import PurePath

from baton.runtime.types import Category


class PolicyError(Exception):
    """Raised when a command is not allowed by the current policy."""


class Policy:
    """Allowlist-based command policy per category."""

    def __init__(self, rules: dict[Category, set[str]] | None = None) -> None:
        self._rules: dict[Category, set[str]] = rules or {}

    def allows(self, category: Category, command: str) -> None:
        """Raise PolicyError if *command* is not allowlisted for *category*."""
        command = command.strip()
        if not command:
            raise PolicyError("command is required")
        if category not in self._rules:
            raise PolicyError(f"unsupported category: {category}")
        exe = _normalize_executable(command)
        if exe not in self._rules[category]:
            raise PolicyError(
                f"command {exe!r} is not allowlisted for category {category}"
            )

    def allow(self, category: Category, command: str) -> None:
        """Add *command* to the allowlist for *category*."""
        rules = self._rules.setdefault(category, set())
        rules.add(_normalize_executable(command))


def default_policy() -> Policy:
    return Policy({
        Category.BUILD: {
            "go", "cargo", "dotnet", "make", "cmake",
            "mvn", "gradle", "npm", "pnpm", "yarn",
        },
        Category.TEST: {
            "go", "cargo", "dotnet", "pytest", "npm",
            "pnpm", "yarn", "python",
        },
        Category.LINT: {
            "go", "golangci-lint", "eslint", "prettier", "ruff",
            "black", "mypy", "flake8", "cargo", "dotnet",
        },
        Category.SEARCH: {
            "rg", "grep", "git", "findstr", "select-string",
        },
        Category.COMMAND: {"go"},
    })


def _normalize_executable(command: str) -> str:
    """Normalize a command name for policy matching.

    Strips path, lowercases, removes Windows extensions.
    """
    name = PurePath(command).name.lower()
    for ext in (".exe", ".cmd", ".bat"):
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    if sys.platform == "win32":
        name = name.replace(" ", "")
    return name
