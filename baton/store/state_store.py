"""Atomic JSON state store for Jobs and Chains."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

from baton.domain.errors import InvalidIDError, JobNotFoundError, ChainNotFoundError
from baton.domain.types import Job, JobChain

_VALID_ID = re.compile(r"^[a-zA-Z0-9_\-.]+$")


def _validate_id(id_value: str) -> None:
    if id_value in (".", ".."):
        raise InvalidIDError(id_value, "reserved filesystem path component")
    if not _VALID_ID.match(id_value):
        raise InvalidIDError(id_value)


def _atomic_write(path: Path, data: bytes) -> None:
    """Write *data* to *path* atomically (best-effort on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    try:
        os.write(fd, data)
        os.close(fd)
        # os.replace is atomic on POSIX; best-effort on Windows
        try:
            os.replace(tmp, str(path))
            return
        except OSError:
            pass
        # Windows retry with rename-to-bak strategy
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
            # Restore backup so target is never absent
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


class StateStore:
    """JSON file-based persistence for Job and JobChain objects."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    # -- Jobs ---------------------------------------------------------------

    async def save_job(self, job: Job) -> None:
        _validate_id(job.id)
        data = job.model_dump_json(indent=2).encode()
        _atomic_write(self._job_path(job.id), data)

    async def load_job(self, job_id: str) -> Job:
        _validate_id(job_id)
        path = self._job_path(job_id)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raise JobNotFoundError(job_id) from None
        return Job.model_validate_json(raw)

    async def list_jobs(self) -> list[Job]:
        jobs_dir = self._jobs_dir()
        jobs_dir.mkdir(parents=True, exist_ok=True)
        jobs: list[Job] = []
        for entry in sorted(jobs_dir.iterdir()):
            if entry.is_dir() or not entry.name.endswith(".json"):
                continue
            raw = entry.read_bytes()
            jobs.append(Job.model_validate_json(raw))
        # newest first
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    # -- Chains -------------------------------------------------------------

    async def save_chain(self, chain: JobChain) -> None:
        _validate_id(chain.id)
        data = chain.model_dump_json(indent=2).encode()
        _atomic_write(self._chain_path(chain.id), data)

    async def load_chain(self, chain_id: str) -> JobChain:
        _validate_id(chain_id)
        path = self._chain_path(chain_id)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raise ChainNotFoundError(chain_id) from None
        return JobChain.model_validate_json(raw)

    async def list_chains(self) -> list[JobChain]:
        chains_dir = self._chains_dir()
        chains_dir.mkdir(parents=True, exist_ok=True)
        chains: list[JobChain] = []
        for entry in sorted(chains_dir.iterdir()):
            if entry.is_dir() or not entry.name.endswith(".json"):
                continue
            raw = entry.read_bytes()
            chains.append(JobChain.model_validate_json(raw))
        chains.sort(key=lambda c: c.created_at, reverse=True)
        return chains

    # -- Paths --------------------------------------------------------------

    def _jobs_dir(self) -> Path:
        return self._root / "jobs"

    def _chains_dir(self) -> Path:
        return self._root / "chains"

    def _job_path(self, job_id: str) -> Path:
        return self._jobs_dir() / f"{job_id}.json"

    def _chain_path(self, chain_id: str) -> Path:
        return self._chains_dir() / f"{chain_id}.json"
