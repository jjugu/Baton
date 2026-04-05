"""HTTP endpoint handlers for the baton API.

All routes are registered on the FastAPI app in server.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from baton.api.views import (
    build_evaluator_view,
    build_planning_view,
    build_profile_view,
    build_verification_view,
)
from baton.domain.types import (
    Job,
    JobStatus,
    ProviderName,
    RoleProfiles,
)

logger = logging.getLogger("baton.api")

router = APIRouter()

# ---------------------------------------------------------------------------
# Request DTOs
# ---------------------------------------------------------------------------


class StartJobRequest(BaseModel):
    goal: str
    tech_stack: str = ""
    workspace_dir: str = ""
    workspace_mode: str = ""
    constraints: list[str] = Field(default_factory=list)
    done_criteria: list[str] = Field(default_factory=list)
    provider: str = ""
    role_profiles: dict[str, Any] | None = None
    max_steps: int = 0


class CancelJobRequest(BaseModel):
    reason: str = ""


class RejectJobRequest(BaseModel):
    reason: str = ""


class SteerJobRequest(BaseModel):
    message: str


class StartChainRequest(BaseModel):
    workspace_dir: str
    goals: list[dict[str, Any]]


class StartHarnessProcessRequest(BaseModel):
    name: str = ""
    category: str = "command"
    command: str
    args: list[str] = Field(default_factory=list)
    dir: str = ""
    env: list[str] = Field(default_factory=list)
    timeout_seconds: int = 0
    max_output_bytes: int = 0
    log_dir: str = ""
    port: int = 0


# ---------------------------------------------------------------------------
# The service is injected via app.state at startup
# ---------------------------------------------------------------------------


def _svc(request: Request) -> Any:
    return request.app.state.service


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Jobs collection
# ---------------------------------------------------------------------------


@router.get("/jobs")
async def list_jobs(request: Request) -> Any:
    svc = _svc(request)
    jobs = await svc.list_jobs()
    return [j.model_dump(mode="json") for j in jobs]


@router.post("/jobs", status_code=201)
async def start_job(request: Request, body: StartJobRequest) -> Any:
    svc = _svc(request)
    from baton.orchestrator.service import CreateJobInput

    provider = ProviderName(body.provider) if body.provider else ProviderName.MOCK
    input_data = CreateJobInput(
        goal=body.goal,
        tech_stack=body.tech_stack,
        workspace_dir=body.workspace_dir,
        workspace_mode=body.workspace_mode,
        constraints=body.constraints,
        done_criteria=body.done_criteria,
        provider=provider,
        max_steps=body.max_steps or 8,
    )
    job = await svc.start_async(input_data)
    return job.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Single job
# ---------------------------------------------------------------------------


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str) -> Any:
    svc = _svc(request)
    try:
        job = await svc.get(job_id)
    except Exception:
        raise HTTPException(status_code=404, detail="not found")
    return job.model_dump(mode="json")


@router.post("/jobs/{job_id}/resume")
async def resume_job(request: Request, job_id: str) -> Any:
    svc = _svc(request)
    try:
        job = await svc.resume(job_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return job.model_dump(mode="json")


@router.post("/jobs/{job_id}/approve")
async def approve_job(request: Request, job_id: str) -> Any:
    svc = _svc(request)
    try:
        job = await svc.approve(job_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return job.model_dump(mode="json")


@router.post("/jobs/{job_id}/retry")
async def retry_job(request: Request, job_id: str) -> Any:
    svc = _svc(request)
    try:
        job = await svc.retry(job_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return job.model_dump(mode="json")


@router.post("/jobs/{job_id}/reject")
async def reject_job(request: Request, job_id: str, body: RejectJobRequest | None = None) -> Any:
    svc = _svc(request)
    reason = body.reason if body else ""
    try:
        job = await svc.reject(job_id, reason)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return job.model_dump(mode="json")


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str, body: CancelJobRequest | None = None) -> Any:
    svc = _svc(request)
    reason = body.reason if body else ""
    try:
        job = await svc.cancel(job_id, reason)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return job.model_dump(mode="json")


@router.post("/jobs/{job_id}/steer")
async def steer_job(request: Request, job_id: str, body: SteerJobRequest) -> Any:
    svc = _svc(request)
    try:
        job = await svc.steer(job_id, body.message)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return job.model_dump(mode="json")


@router.get("/jobs/{job_id}/events")
async def get_events(request: Request, job_id: str) -> Any:
    svc = _svc(request)
    try:
        job = await svc.get(job_id)
    except Exception:
        raise HTTPException(status_code=404, detail="not found")
    return [e.model_dump(mode="json") for e in job.events]


@router.get("/jobs/{job_id}/events/stream")
async def stream_events(request: Request, job_id: str) -> StreamingResponse:
    svc = _svc(request)

    async def event_generator():
        last_count = 0
        terminal = frozenset({"done", "failed", "blocked"})
        while True:
            try:
                job = await svc.get(job_id)
            except Exception:
                return

            while last_count < len(job.events):
                event = job.events[last_count]
                data = json.dumps(event.model_dump(mode="json"), default=str)
                yield f"id: {last_count}\nevent: job_event\ndata: {data}\n\n"
                last_count += 1

            if str(job.status) in terminal:
                return

            if await request.is_disconnected():
                return

            await asyncio.sleep(0.25)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/jobs/{job_id}/artifacts")
async def get_artifacts(request: Request, job_id: str) -> Any:
    svc = _svc(request)
    try:
        job = await svc.get(job_id)
    except Exception:
        raise HTTPException(status_code=404, detail="not found")
    out: list[str] = []
    for step in job.steps:
        out.extend(step.artifacts)
    return out


@router.get("/jobs/{job_id}/verification")
async def get_verification(request: Request, job_id: str) -> Any:
    svc = _svc(request)
    try:
        job = await svc.get(job_id)
    except Exception:
        raise HTTPException(status_code=404, detail="not found")
    return build_verification_view(job).model_dump(mode="json")


@router.get("/jobs/{job_id}/planning")
async def get_planning(request: Request, job_id: str) -> Any:
    svc = _svc(request)
    try:
        job = await svc.get(job_id)
    except Exception:
        raise HTTPException(status_code=404, detail="not found")
    return build_planning_view(job).model_dump(mode="json")


@router.get("/jobs/{job_id}/evaluator")
async def get_evaluator(request: Request, job_id: str) -> Any:
    svc = _svc(request)
    try:
        job = await svc.get(job_id)
    except Exception:
        raise HTTPException(status_code=404, detail="not found")
    return build_evaluator_view(job).model_dump(mode="json")


@router.get("/jobs/{job_id}/profile")
async def get_profile(request: Request, job_id: str) -> Any:
    svc = _svc(request)
    try:
        job = await svc.get(job_id)
    except Exception:
        raise HTTPException(status_code=404, detail="not found")
    return build_profile_view(job).model_dump(mode="json")


# ---------------------------------------------------------------------------
# Chains
# ---------------------------------------------------------------------------


@router.get("/chains")
async def list_chains(request: Request) -> Any:
    svc = _svc(request)
    chains = await svc.list_chains()
    return [c.model_dump(mode="json") for c in chains]


@router.post("/chains", status_code=201)
async def start_chain(request: Request, body: StartChainRequest) -> Any:
    """Start a sequential chain of jobs (Go: handleChains POST)."""
    svc = _svc(request)
    from baton.domain.types import ChainGoal, ProviderName as PN

    goals = []
    for i, raw in enumerate(body.goals):
        goal_text = raw.get("goal", "").strip()
        if not goal_text:
            raise HTTPException(status_code=400, detail=f"goals[{i}].goal is required")
        provider_str = raw.get("provider", "")
        provider = PN(provider_str) if provider_str else PN.CLAUDE
        goals.append(ChainGoal(
            goal=goal_text,
            provider=provider,
            max_steps=raw.get("max_steps", 8),
            strictness_level=raw.get("strictness_level", "normal"),
        ))

    try:
        chain = await svc.start_chain(goals, body.workspace_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return chain.model_dump(mode="json")


@router.get("/chains/{chain_id}")
async def get_chain(request: Request, chain_id: str) -> Any:
    svc = _svc(request)
    try:
        chain = await svc.get_chain(chain_id)
    except Exception:
        raise HTTPException(status_code=404, detail="not found")
    return chain.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Global harness (Go: handleHarness in harness.go)
# ---------------------------------------------------------------------------


@router.get("/harness/processes")
async def list_harness_processes(request: Request) -> Any:
    """List all managed harness processes."""
    svc = _svc(request)
    try:
        processes = await svc.list_harness_processes()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"processes": processes, "note": "runtime processes are managed by the orchestrator service"}


@router.post("/harness/processes", status_code=201)
async def start_harness_process(request: Request, body: StartHarnessProcessRequest) -> Any:
    """Start a global harness process."""
    svc = _svc(request)
    try:
        handle = await svc.start_harness_process(body.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return handle


@router.get("/harness/processes/{pid}")
async def get_harness_process(request: Request, pid: int) -> Any:
    """Get a harness process by PID."""
    if pid <= 0:
        raise HTTPException(status_code=400, detail="invalid pid")
    svc = _svc(request)
    try:
        handle = await svc.get_harness_process(pid)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return handle


@router.post("/harness/processes/{pid}/stop")
async def stop_harness_process(request: Request, pid: int) -> Any:
    """Stop a harness process by PID."""
    if pid <= 0:
        raise HTTPException(status_code=400, detail="invalid pid")
    svc = _svc(request)
    try:
        handle = await svc.stop_harness_process(pid)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return handle


# ---------------------------------------------------------------------------
# Job-scoped harness (Go: handleJobHarness in harness.go)
# ---------------------------------------------------------------------------


@router.get("/jobs/{job_id}/harness")
async def get_job_harness(request: Request, job_id: str) -> Any:
    """Get harness view for a job (Go: handleJobHarness root)."""
    svc = _svc(request)
    try:
        job = await svc.get(job_id)
    except Exception:
        raise HTTPException(status_code=404, detail="not found")
    try:
        processes = await svc.list_job_harness_processes(job_id)
    except Exception:
        processes = []
    return {
        "job_id": job.id,
        "goal": job.goal,
        "status": str(job.status),
        "provider": str(job.provider),
        "workspace_dir": job.workspace_dir,
        "step_count": len(job.steps),
        "event_count": len(job.events),
        "pending_approval": job.pending_approval is not None,
        "process_count": len(processes),
        "processes": processes,
        "available": True,
        "note": "job harness view assembled from persisted job state and tracked runtime processes",
    }


@router.get("/jobs/{job_id}/harness/processes")
async def list_job_harness_processes(request: Request, job_id: str) -> Any:
    """List harness processes scoped to a job."""
    svc = _svc(request)
    try:
        processes = await svc.list_job_harness_processes(job_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"processes": processes, "note": "job-scoped runtime processes are owned by the requested job"}


@router.post("/jobs/{job_id}/harness/processes", status_code=201)
async def start_job_harness_process(request: Request, job_id: str, body: StartHarnessProcessRequest) -> Any:
    """Start a harness process scoped to a job."""
    svc = _svc(request)
    try:
        handle = await svc.start_job_harness_process(job_id, body.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return handle


@router.get("/jobs/{job_id}/harness/processes/{pid}")
async def get_job_harness_process(request: Request, job_id: str, pid: int) -> Any:
    """Get a job-scoped harness process by PID."""
    if pid <= 0:
        raise HTTPException(status_code=400, detail="invalid pid")
    svc = _svc(request)
    try:
        handle = await svc.get_job_harness_process(job_id, pid)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return handle


@router.post("/jobs/{job_id}/harness/processes/{pid}/stop")
async def stop_job_harness_process(request: Request, job_id: str, pid: int) -> Any:
    """Stop a job-scoped harness process by PID."""
    if pid <= 0:
        raise HTTPException(status_code=400, detail="invalid pid")
    svc = _svc(request)
    try:
        handle = await svc.stop_job_harness_process(job_id, pid)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return handle
