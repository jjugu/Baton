"""Artifact store -- materializes step outputs and named artifacts.

Ported from gorchera/internal/store/artifact_store.go.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from baton.domain.errors import InvalidIDError
from baton.domain.types import WorkerOutput

_VALID_ID = re.compile(r"^[a-zA-Z0-9_\-.]+$")
_UNSAFE_CHARS = str.maketrans({
    "\\": "-", "/": "-", " ": "-", ":": "-",
    "*": "-", "?": "-", '"': "-", "<": "-", ">": "-", "|": "-",
})


def _validate_id(id_value: str) -> None:
    if id_value in (".", ".."):
        raise InvalidIDError(id_value, "reserved filesystem path component")
    if not _VALID_ID.match(id_value):
        raise InvalidIDError(id_value)


def _sanitize_artifact_name(name: str) -> str:
    name = os.path.basename(name.strip())
    if not name or name == ".":
        return "artifact.json"
    return name.translate(_UNSAFE_CHARS)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    try:
        os.write(fd, data)
        os.close(fd)
        try:
            os.replace(tmp, str(path))
            return
        except OSError:
            pass
        bak = str(path) + ".bak"
        for attempt in range(20):
            try:
                if path.exists():
                    os.replace(str(path), bak)
            except OSError:
                pass
            try:
                os.replace(tmp, str(path))
                try:
                    os.unlink(bak)
                except OSError:
                    pass
                return
            except OSError:
                pass
            try:
                if not path.exists() and os.path.exists(bak):
                    os.replace(bak, str(path))
            except OSError:
                pass
            time.sleep((attempt + 1) * 0.005)
        raise OSError(f"failed to atomically write {path} after 20 attempts")
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class ArtifactStore:
    """Manages artifact files on disk grouped by job ID."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def materialize_worker_artifacts(
        self, job_id: str, step_index: int, output: WorkerOutput,
    ) -> list[str]:
        """Write worker output artifacts to disk; return list of paths."""
        _validate_id(job_id)
        base_dir = self._root / job_id
        base_dir.mkdir(parents=True, exist_ok=True)
        paths: list[str] = []
        for name in output.artifacts:
            safe = _sanitize_artifact_name(name)
            path = base_dir / f"step-{step_index:02d}-{safe}"
            if name in output.file_contents:
                payload = output.file_contents[name].encode()
            else:
                fallback = {
                    "summary": output.summary,
                    "status": output.status,
                    "next_recommended_action": output.next_recommended_action,
                }
                payload = json.dumps(fallback, indent=2).encode()
            _atomic_write(path, payload)
            paths.append(str(path))
        return paths

    def materialize_text_artifact(
        self, job_id: str, name: str, content: str,
    ) -> str:
        """Write a text artifact; return its path."""
        _validate_id(job_id)
        base_dir = self._root / job_id
        base_dir.mkdir(parents=True, exist_ok=True)
        path = base_dir / _sanitize_artifact_name(name)
        _atomic_write(path, content.encode())
        return str(path)

    def materialize_json_artifact(
        self, job_id: str, name: str, value: Any,
    ) -> str:
        """Write a JSON artifact; return its path."""
        _validate_id(job_id)
        base_dir = self._root / job_id
        base_dir.mkdir(parents=True, exist_ok=True)
        path = base_dir / _sanitize_artifact_name(name)
        payload = json.dumps(value, indent=2).encode()
        _atomic_write(path, payload)
        return str(path)

    def materialize_system_result(
        self, job_id: str, step_index: int, result: dict[str, Any],
    ) -> list[str]:
        """Write a runtime result as JSON; return list of paths."""
        _validate_id(job_id)
        base_dir = self._root / job_id
        base_dir.mkdir(parents=True, exist_ok=True)
        path = base_dir / f"step-{step_index:02d}-runtime_result.json"
        payload = json.dumps(result, indent=2).encode()
        _atomic_write(path, payload)
        return [str(path)]
