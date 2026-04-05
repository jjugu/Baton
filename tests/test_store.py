"""Cross-validate baton/store against Go store.

Tests:
- StateStore: save/load/list for jobs and chains
- ArtifactStore: materialize worker/text/JSON/system-result artifacts
- Atomic write behavior
- ID validation (path traversal prevention)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from baton.domain.errors import ChainNotFoundError, InvalidIDError, JobNotFoundError
from baton.domain.types import (
    ChainGoal,
    Job,
    JobChain,
    ProviderName,
    WorkerOutput,
)
from baton.store.state_store import StateStore
from baton.store.artifact_store import ArtifactStore


# ---------------------------------------------------------------------------
# StateStore
# ---------------------------------------------------------------------------

class TestStateStoreJobCRUD:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> StateStore:
        return StateStore(tmp_path / "state")

    @pytest.mark.asyncio
    async def test_save_and_load_job(self, store: StateStore) -> None:
        job = Job(id="job-001", goal="test goal", provider=ProviderName.MOCK)
        await store.save_job(job)
        loaded = await store.load_job("job-001")
        assert loaded.id == "job-001"
        assert loaded.goal == "test goal"

    @pytest.mark.asyncio
    async def test_load_nonexistent_raises(self, store: StateStore) -> None:
        with pytest.raises(JobNotFoundError):
            await store.load_job("nonexistent")

    @pytest.mark.asyncio
    async def test_list_jobs(self, store: StateStore) -> None:
        for i in range(3):
            job = Job(id=f"job-{i:03d}", goal=f"goal {i}", provider=ProviderName.MOCK)
            await store.save_job(job)
        jobs = await store.list_jobs()
        assert len(jobs) == 3
        ids = {j.id for j in jobs}
        assert ids == {"job-000", "job-001", "job-002"}

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, store: StateStore) -> None:
        jobs = await store.list_jobs()
        assert jobs == []


class TestStateStoreChainCRUD:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> StateStore:
        return StateStore(tmp_path / "state")

    @pytest.mark.asyncio
    async def test_save_and_load_chain(self, store: StateStore) -> None:
        chain = JobChain(
            id="chain-001",
            goals=[ChainGoal(goal="step 1", provider=ProviderName.MOCK)],
        )
        await store.save_chain(chain)
        loaded = await store.load_chain("chain-001")
        assert loaded.id == "chain-001"
        assert len(loaded.goals) == 1

    @pytest.mark.asyncio
    async def test_load_nonexistent_chain_raises(self, store: StateStore) -> None:
        with pytest.raises(ChainNotFoundError):
            await store.load_chain("nonexistent")


class TestStateStoreIDValidation:
    """Go validateID: rejects '.', '..', and non-alphanumeric chars.
    Regex: ^[a-zA-Z0-9_\\-.]+$"""

    @pytest.fixture()
    def store(self, tmp_path: Path) -> StateStore:
        return StateStore(tmp_path / "state")

    @pytest.mark.asyncio
    async def test_dot_rejected(self, store: StateStore) -> None:
        job = Job(id=".", goal="test", provider=ProviderName.MOCK)
        with pytest.raises(InvalidIDError):
            await store.save_job(job)

    @pytest.mark.asyncio
    async def test_dotdot_rejected(self, store: StateStore) -> None:
        job = Job(id="..", goal="test", provider=ProviderName.MOCK)
        with pytest.raises(InvalidIDError):
            await store.save_job(job)

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, store: StateStore) -> None:
        job = Job(id="../etc/passwd", goal="test", provider=ProviderName.MOCK)
        with pytest.raises(InvalidIDError):
            await store.save_job(job)

    @pytest.mark.asyncio
    async def test_valid_ids_accepted(self, store: StateStore) -> None:
        for valid_id in ("job-001", "my_job.v2", "JOB-123"):
            job = Job(id=valid_id, goal="test", provider=ProviderName.MOCK)
            await store.save_job(job)  # should not raise


class TestAtomicWrite:
    """Verify file is created atomically (tempfile + replace)."""

    @pytest.fixture()
    def store(self, tmp_path: Path) -> StateStore:
        return StateStore(tmp_path / "state")

    @pytest.mark.asyncio
    async def test_file_exists_after_save(self, store: StateStore) -> None:
        job = Job(id="atomic-test", goal="test", provider=ProviderName.MOCK)
        await store.save_job(job)
        path = store._job_path("atomic-test")
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["id"] == "atomic-test"


# ---------------------------------------------------------------------------
# ArtifactStore
# ---------------------------------------------------------------------------

class TestArtifactStoreWorkerArtifacts:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> ArtifactStore:
        return ArtifactStore(tmp_path / "artifacts")

    def test_materialize_with_file_contents(self, store: ArtifactStore) -> None:
        output = WorkerOutput(
            status="success",
            summary="done",
            artifacts=["main.py"],
            file_contents={"main.py": "print('hello')"},
        )
        paths = store.materialize_worker_artifacts("job-001", 0, output)
        assert len(paths) == 1
        content = Path(paths[0]).read_text()
        assert content == "print('hello')"

    def test_materialize_without_file_contents(self, store: ArtifactStore) -> None:
        """Go: falls back to {summary, status, next_recommended_action} JSON."""
        output = WorkerOutput(
            status="success",
            summary="completed task",
            artifacts=["result.json"],
        )
        paths = store.materialize_worker_artifacts("job-001", 1, output)
        assert len(paths) == 1
        data = json.loads(Path(paths[0]).read_text())
        assert data["summary"] == "completed task"
        assert data["status"] == "success"

    def test_step_index_in_filename(self, store: ArtifactStore) -> None:
        """Go: fmt.Sprintf(\"step-%02d-%s\", stepIndex, safe)."""
        output = WorkerOutput(
            status="success",
            summary="ok",
            artifacts=["test.txt"],
            file_contents={"test.txt": "content"},
        )
        paths = store.materialize_worker_artifacts("job-001", 5, output)
        assert "step-05" in paths[0]


class TestArtifactStoreTextAndJSON:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> ArtifactStore:
        return ArtifactStore(tmp_path / "artifacts")

    def test_materialize_text(self, store: ArtifactStore) -> None:
        path = store.materialize_text_artifact("job-001", "notes.txt", "hello world")
        assert Path(path).read_text() == "hello world"

    def test_materialize_json(self, store: ArtifactStore) -> None:
        value = {"key": "value", "number": 42}
        path = store.materialize_json_artifact("job-001", "data.json", value)
        data = json.loads(Path(path).read_text())
        assert data == value

    def test_materialize_system_result(self, store: ArtifactStore) -> None:
        """Go: step-{idx:02d}-runtime_result.json."""
        result = {"exit_code": 0, "stdout": "ok"}
        paths = store.materialize_system_result("job-001", 3, result)
        assert len(paths) == 1
        assert "step-03-runtime_result.json" in paths[0]
        data = json.loads(Path(paths[0]).read_text())
        assert data["exit_code"] == 0


class TestArtifactStoreIDValidation:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> ArtifactStore:
        return ArtifactStore(tmp_path / "artifacts")

    def test_path_traversal_rejected(self, store: ArtifactStore) -> None:
        with pytest.raises(InvalidIDError):
            store.materialize_text_artifact("../etc", "test.txt", "evil")
