"""Job lease management -- heartbeat and recovery."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)

LEASE_HEARTBEAT_INTERVAL = 15.0  # seconds
LEASE_STALE_AFTER = 45.0  # seconds

_VALID_ID = re.compile(r"^[a-zA-Z0-9_\-.]+$")


def new_service_instance_id() -> str:
    return f"svc-{int(time.time() * 1_000_000_000)}"


def validate_lease_id(job_id: str) -> None:
    if job_id in (".", ".."):
        raise ValueError(f"invalid job ID {job_id!r}: reserved filesystem path component")
    if not _VALID_ID.match(job_id):
        raise ValueError(f"invalid job ID {job_id!r}: must match ^[a-zA-Z0-9_-.]+$")


class JobLease:
    """Manages a heartbeat file for a running job."""

    def __init__(self, lease_dir: str, instance_id: str) -> None:
        self._lease_dir = lease_dir
        self._instance_id = instance_id

    def lease_path(self, job_id: str) -> str:
        return os.path.join(self._lease_dir, f"{job_id.strip()}.json")

    def write_lease(self, job_id: str, workspace_dir: str, heartbeat_at: datetime) -> None:
        validate_lease_id(job_id)
        os.makedirs(self._lease_dir, exist_ok=True)
        payload = {
            "job_id": job_id,
            "run_owner_id": self._instance_id,
            "heartbeat_at": heartbeat_at.isoformat(),
            "workspace_dir": workspace_dir,
        }
        path = self.lease_path(job_id)
        Path(path).write_text(json.dumps(payload, indent=2))

    def remove_lease(self, job_id: str) -> None:
        try:
            os.unlink(self.lease_path(job_id))
        except OSError:
            pass

    def is_stale(self, job_id: str, now: datetime) -> bool:
        path = self.lease_path(job_id)
        try:
            data = json.loads(Path(path).read_text())
            heartbeat = datetime.fromisoformat(data["heartbeat_at"])
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
            age = (now - heartbeat).total_seconds()
            return age > LEASE_STALE_AFTER
        except (OSError, json.JSONDecodeError, KeyError):
            return True


async def run_heartbeat(
    lease: JobLease,
    job_id: str,
    workspace_dir: str,
    stop_event: asyncio.Event,
) -> None:
    """Background heartbeat writer -- runs until stop_event is set."""
    while not stop_event.is_set():
        try:
            lease.write_lease(job_id, workspace_dir, datetime.now(timezone.utc))
        except Exception as exc:
            _log.warning("lease heartbeat failed for %s: %s", job_id, exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=LEASE_HEARTBEAT_INTERVAL)
            break
        except asyncio.TimeoutError:
            pass
