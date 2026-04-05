"""Automated mechanical checks run before the evaluator LLM."""

from __future__ import annotations

import os
import re
from glob import glob
from pathlib import Path

from baton.domain.types import AutomatedCheck, AutomatedCheckResult, Step


def run_automated_checks(
    workspace_dir: str,
    checks: list[AutomatedCheck],
    steps: list[Step],
) -> list[AutomatedCheckResult]:
    return [_execute_check(workspace_dir, check, steps) for check in checks]


def _execute_check(
    workspace_dir: str,
    check: AutomatedCheck,
    steps: list[Step],
) -> AutomatedCheckResult:
    match check.type:
        case "grep":
            return _run_grep_check(workspace_dir, check)
        case "file_exists":
            return _run_file_exists_check(workspace_dir, check)
        case "file_unchanged":
            return _run_file_unchanged_check(check, steps)
        case "no_new_deps":
            return _run_no_new_deps_check(check, steps)
        case _:
            return AutomatedCheckResult(
                description=check.description,
                status="skipped",
                detail=f"unknown check type: {check.type}",
            )


def _run_grep_check(workspace_dir: str, check: AutomatedCheck) -> AutomatedCheckResult:
    if not check.pattern:
        return AutomatedCheckResult(
            description=check.description,
            status="skipped",
            detail="grep check missing pattern",
        )
    try:
        pattern = re.compile(check.pattern)
    except re.error as exc:
        return AutomatedCheckResult(
            description=check.description,
            status="skipped",
            detail=f"invalid pattern: {exc}",
        )

    glob_pattern = check.file or "*"
    matches = glob(os.path.join(workspace_dir, glob_pattern))
    if not matches:
        return AutomatedCheckResult(
            description=check.description,
            status="failed",
            detail=f"no files matched glob {glob_pattern!r}",
        )

    for path in matches:
        try:
            data = Path(path).read_text(errors="replace")
        except OSError:
            continue
        for line in data.split("\n"):
            if pattern.search(line):
                rel = os.path.relpath(path, workspace_dir).replace("\\", "/")
                return AutomatedCheckResult(
                    description=check.description,
                    status="passed",
                    detail=f"pattern matched in {rel}",
                )

    return AutomatedCheckResult(
        description=check.description,
        status="failed",
        detail=f"pattern {check.pattern!r} not found in {len(matches)} file(s)",
    )


def _run_file_exists_check(workspace_dir: str, check: AutomatedCheck) -> AutomatedCheckResult:
    if not check.path:
        return AutomatedCheckResult(
            description=check.description,
            status="skipped",
            detail="file_exists check missing path",
        )
    full = os.path.join(workspace_dir, check.path)
    if os.path.exists(full):
        return AutomatedCheckResult(
            description=check.description,
            status="passed",
            detail=f"{check.path} exists",
        )
    return AutomatedCheckResult(
        description=check.description,
        status="failed",
        detail=f"{check.path} not found",
    )


def _run_file_unchanged_check(check: AutomatedCheck, steps: list[Step]) -> AutomatedCheckResult:
    if not check.path:
        return AutomatedCheckResult(
            description=check.description,
            status="skipped",
            detail="file_unchanged check missing path",
        )
    for step in steps:
        for cf in step.changed_files:
            if cf.path == check.path:
                return AutomatedCheckResult(
                    description=check.description,
                    status="failed",
                    detail=f"{check.path} was modified in step {step.index}",
                )
    return AutomatedCheckResult(
        description=check.description,
        status="passed",
        detail=f"{check.path} was not modified",
    )


def _run_no_new_deps_check(check: AutomatedCheck, steps: list[Step]) -> AutomatedCheckResult:
    dep_files = {"go.mod", "go.sum", "package.json", "requirements.txt", "pyproject.toml"}
    for step in steps:
        for cf in step.changed_files:
            if os.path.basename(cf.path) in dep_files:
                return AutomatedCheckResult(
                    description=check.description,
                    status="failed",
                    detail=f"dependency file {cf.path} was modified in step {step.index}",
                )
    return AutomatedCheckResult(
        description=check.description,
        status="passed",
        detail="no dependency files were modified",
    )
