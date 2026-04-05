"""Workspace validation and preparation."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from baton.domain.types import WorkspaceMode


class WorkspaceError(Exception):
    pass


def validate_workspace_dir(path: str) -> None:
    """Validate that *path* is an existing absolute directory."""
    if not path.strip():
        return
    if not os.path.isabs(path):
        raise WorkspaceError(f"workspace directory must be an absolute path: {path}")
    try:
        resolved = os.path.realpath(path)
    except OSError as exc:
        raise WorkspaceError(f"resolve workspace directory {path!r}: {exc}") from exc
    if not os.path.isdir(resolved):
        raise WorkspaceError(f"workspace directory does not exist: {path}")


def normalize_workspace_mode(mode: str) -> str:
    if mode.strip().lower() == WorkspaceMode.ISOLATED:
        return WorkspaceMode.ISOLATED
    return WorkspaceMode.SHARED


def prepare_workspace_dir(
    workspace_root: str,
    requested_dir: str,
    job_id: str,
    workspace_mode: str,
) -> tuple[str, str, str]:
    """Return (workspace_dir, requested_workspace_dir, mode)."""
    source = requested_dir.strip() or workspace_root
    validate_workspace_dir(source)
    mode = normalize_workspace_mode(workspace_mode)
    if mode != WorkspaceMode.ISOLATED:
        return source, source, mode
    isolated = _create_git_worktree(workspace_root, source, job_id)
    validate_workspace_dir(isolated)
    return isolated, source, mode


def _create_git_worktree(workspace_root: str, source_dir: str, job_id: str) -> str:
    """Create an isolated git worktree for a job."""
    try:
        repo_root = _git_output(source_dir, "rev-parse", "--show-toplevel").strip()
    except Exception as exc:
        raise WorkspaceError(f"isolated workspace mode requires a git repository: {exc}") from exc

    repo_root = os.path.normpath(repo_root)
    parent = os.path.join(os.path.dirname(repo_root), ".baton-worktrees", os.path.basename(repo_root))
    worktree_dir = os.path.join(parent, job_id)
    os.makedirs(parent, exist_ok=True)

    if os.path.exists(worktree_dir):
        _git_output(repo_root, "worktree", "remove", "--force", worktree_dir)

    branch = _git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    _git_output(repo_root, "worktree", "add", worktree_dir, branch)
    return worktree_dir


def _git_output(cwd: str, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise WorkspaceError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def collect_workspace_diff_summary(workspace_dir: str) -> str:
    """Return git diff --stat output for workspace changes."""
    try:
        return _git_output(workspace_dir, "diff", "--stat").strip()
    except Exception:
        return ""
