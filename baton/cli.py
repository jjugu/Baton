"""Typer CLI for baton.

Ported from gorchera/cmd/gorchera/main.go.
All 22 subcommands are replicated with Python idioms.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from typing import Any, Optional

import typer

app = typer.Typer(
    name="baton",
    help="Baton - Python multi-agent orchestration engine",
    no_args_is_help=True,
)


def _print_json(v: Any) -> None:
    print(json.dumps(v, indent=2, default=str))


def _split_csv(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _build_service(workspace: str) -> Any:
    """Build the orchestrator service for a workspace."""
    root_dir = os.path.join(workspace, ".baton")
    from baton.store.state_store import StateStore
    from baton.store.artifact_store import ArtifactStore
    from baton.provider.registry import new_registry, SessionManager
    from baton.orchestrator.service import Service

    state_store = StateStore(os.path.join(root_dir, "state"))
    artifact_store = ArtifactStore(os.path.join(root_dir, "artifacts"))
    registry = new_registry()
    session_manager = SessionManager(registry)
    return Service(session_manager, state_store, artifact_store, workspace)


def _current_workspace() -> str:
    return os.getcwd()


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@app.command()
def run(
    goal: str = typer.Option(..., help="Job goal"),
    tech_stack: str = typer.Option("go", help="Tech stack label"),
    constraints: str = typer.Option("", help="Comma-separated constraints"),
    done: str = typer.Option("", help="Comma-separated done criteria"),
    provider: str = typer.Option("mock", help="Provider name (mock/codex/claude)"),
    profiles_file: str = typer.Option("", help="Path to role profile JSON file"),
    workspace_mode: str = typer.Option("shared", help="Workspace mode: shared | isolated"),
    max_steps: int = typer.Option(8, help="Maximum worker steps"),
    strictness: str = typer.Option("normal", help="Evaluator strictness: strict/normal/lenient"),
) -> None:
    """Start a new job."""
    if not goal.strip():
        typer.echo("Error: run requires --goal", err=True)
        raise typer.Exit(1)

    from baton.orchestrator.service import CreateJobInput
    from baton.domain.types import (
        ProviderName,
        default_role_profiles,
    )

    service = _build_service(_current_workspace())
    provider_name = ProviderName(provider)

    role_profiles = default_role_profiles(provider_name)
    if profiles_file.strip():
        with open(profiles_file) as f:
            role_profiles = json.load(f)

    input_data = CreateJobInput(
        goal=goal,
        tech_stack=tech_stack,
        workspace_dir=_current_workspace(),
        workspace_mode=workspace_mode,
        constraints=_split_csv(constraints),
        done_criteria=_split_csv(done),
        provider=provider_name,
        role_profiles=role_profiles,
        max_steps=max_steps,
        strictness_level=strictness,
    )

    job = asyncio.run(service.start_async(input_data))
    _print_json(job.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    job: str = typer.Option("", help="Job ID"),
    all: bool = typer.Option(False, "--all", help="List all jobs"),
) -> None:
    """Get job status or list all jobs."""
    service = _build_service(_current_workspace())

    if all:
        jobs = asyncio.run(service.list_jobs())
        _print_json([j.model_dump(mode="json") for j in jobs])
        return

    if not job.strip():
        typer.echo("Error: status requires --job or --all", err=True)
        raise typer.Exit(1)

    result = asyncio.run(service.get(job))
    _print_json(result.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


@app.command()
def events(
    job: str = typer.Option(..., help="Job ID"),
) -> None:
    """Get events for a job."""
    service = _build_service(_current_workspace())
    result = asyncio.run(service.get(job))
    _print_json([e.model_dump(mode="json") for e in result.events])


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------


@app.command()
def artifacts(
    job: str = typer.Option(..., help="Job ID"),
) -> None:
    """Get artifact paths for a job."""
    service = _build_service(_current_workspace())
    result = asyncio.run(service.get(job))
    out: list[str] = []
    for step in result.steps:
        out.extend(step.artifacts)
    _print_json(out)


# ---------------------------------------------------------------------------
# verification / planning / evaluator / profile
# ---------------------------------------------------------------------------


@app.command()
def verification(
    job: str = typer.Option(..., help="Job ID"),
) -> None:
    """Get verification view for a job."""
    from baton.api.views import build_verification_view

    service = _build_service(_current_workspace())
    result = asyncio.run(service.get(job))
    _print_json(build_verification_view(result).model_dump(mode="json"))


@app.command()
def planning(
    job: str = typer.Option(..., help="Job ID"),
) -> None:
    """Get planning view for a job."""
    from baton.api.views import build_planning_view

    service = _build_service(_current_workspace())
    result = asyncio.run(service.get(job))
    _print_json(build_planning_view(result).model_dump(mode="json"))


@app.command()
def evaluator(
    job: str = typer.Option(..., help="Job ID"),
) -> None:
    """Get evaluator view for a job."""
    from baton.api.views import build_evaluator_view

    service = _build_service(_current_workspace())
    result = asyncio.run(service.get(job))
    _print_json(build_evaluator_view(result).model_dump(mode="json"))


@app.command()
def profile(
    job: str = typer.Option(..., help="Job ID"),
) -> None:
    """Get profile view for a job."""
    from baton.api.views import build_profile_view

    service = _build_service(_current_workspace())
    result = asyncio.run(service.get(job))
    _print_json(build_profile_view(result).model_dump(mode="json"))


# ---------------------------------------------------------------------------
# resume / approve / retry / cancel / reject
# ---------------------------------------------------------------------------


@app.command()
def resume(
    job: str = typer.Option(..., help="Job ID"),
) -> None:
    """Resume a blocked job."""
    service = _build_service(_current_workspace())
    result = asyncio.run(service.resume(job))
    _print_json(result.model_dump(mode="json"))


@app.command()
def approve(
    job: str = typer.Option(..., help="Job ID"),
) -> None:
    """Approve a pending approval."""
    service = _build_service(_current_workspace())
    result = asyncio.run(service.approve(job))
    _print_json(result.model_dump(mode="json"))


@app.command()
def retry(
    job: str = typer.Option(..., help="Job ID"),
) -> None:
    """Retry a blocked or failed job."""
    service = _build_service(_current_workspace())
    result = asyncio.run(service.retry(job))
    _print_json(result.model_dump(mode="json"))


@app.command()
def cancel(
    job: str = typer.Option(..., help="Job ID"),
    reason: str = typer.Option("", help="Cancellation reason"),
) -> None:
    """Cancel a job."""
    service = _build_service(_current_workspace())
    result = asyncio.run(service.cancel(job, reason))
    _print_json(result.model_dump(mode="json"))


@app.command()
def reject(
    job: str = typer.Option(..., help="Job ID"),
    reason: str = typer.Option("", help="Rejection reason"),
) -> None:
    """Reject a pending approval."""
    service = _build_service(_current_workspace())
    result = asyncio.run(service.reject(job, reason))
    _print_json(result.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# harness-*
# ---------------------------------------------------------------------------


@app.command("harness-start")
def harness_start(
    job: str = typer.Option("", help="Job ID (scoped if provided)"),
    name: str = typer.Option("", help="Process name"),
    category: str = typer.Option("command", help="Process category"),
    command: str = typer.Option(..., help="Command to run"),
    args: str = typer.Option("", help="Comma-separated args"),
    dir: str = typer.Option("", help="Working directory"),
    env: str = typer.Option("", help="Comma-separated env entries"),
    timeout_seconds: int = typer.Option(0, help="Timeout in seconds"),
    max_output_bytes: int = typer.Option(0, help="Max output bytes"),
    log_dir: str = typer.Option("", help="Log directory"),
    port: int = typer.Option(0, help="Port"),
) -> None:
    """Start a harness process."""
    service = _build_service(_current_workspace())

    from baton.runtime.lifecycle import StartRequest, Request as RuntimeRequest, Category

    request = StartRequest(
        request=RuntimeRequest(
            category=Category(category.strip()),
            command=command,
            args=_split_csv(args),
            dir=dir,
            env=_split_csv(env),
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        ),
        name=name.strip(),
        log_dir=log_dir.strip(),
        port=port,
    )

    if job.strip():
        result = asyncio.run(service.start_job_harness_process(job.strip(), request))
    else:
        result = asyncio.run(service.start_harness_process(request))
    _print_json(result)


@app.command("harness-view")
def harness_view(
    job: str = typer.Option(..., help="Job ID"),
) -> None:
    """View harness state for a job."""
    from baton.api.views import RuntimeHarnessView

    service = _build_service(_current_workspace())
    job_obj = asyncio.run(service.get(job))
    processes = asyncio.run(service.list_job_harness_processes(job))
    _print_json({
        "job_id": job_obj.id,
        "goal": job_obj.goal,
        "status": str(job_obj.status),
        "provider": str(job_obj.provider),
        "workspace_dir": job_obj.workspace_dir,
        "step_count": len(job_obj.steps),
        "event_count": len(job_obj.events),
        "pending_approval": job_obj.pending_approval is not None,
        "process_count": len(processes),
        "processes": processes,
        "available": True,
        "note": "job harness view assembled from persisted job state and tracked runtime processes",
    })


@app.command("harness-list")
def harness_list(
    job: str = typer.Option("", help="Job ID (scoped if provided)"),
) -> None:
    """List harness processes."""
    service = _build_service(_current_workspace())
    if job.strip():
        processes = asyncio.run(service.list_job_harness_processes(job.strip()))
    else:
        processes = asyncio.run(service.list_harness_processes())
    _print_json({
        "processes": processes,
        "note": "runtime processes are managed by the orchestrator service",
    })


@app.command("harness-status")
def harness_status(
    job: str = typer.Option("", help="Job ID (scoped if provided)"),
    pid: int = typer.Option(..., help="Process ID"),
) -> None:
    """Get harness process status."""
    if pid <= 0:
        typer.echo("Error: harness-status requires --pid", err=True)
        raise typer.Exit(1)

    service = _build_service(_current_workspace())
    if job.strip():
        result = asyncio.run(service.get_job_harness_process(job.strip(), pid))
    else:
        result = asyncio.run(service.get_harness_process(pid))
    _print_json(result)


@app.command("harness-stop")
def harness_stop(
    job: str = typer.Option("", help="Job ID (scoped if provided)"),
    pid: int = typer.Option(..., help="Process ID"),
) -> None:
    """Stop a harness process."""
    if pid <= 0:
        typer.echo("Error: harness-stop requires --pid", err=True)
        raise typer.Exit(1)

    service = _build_service(_current_workspace())
    if job.strip():
        result = asyncio.run(service.stop_job_harness_process(job.strip(), pid))
    else:
        result = asyncio.run(service.stop_harness_process(pid))
    _print_json(result)


# ---------------------------------------------------------------------------
# stream (client-side SSE consumer)
# ---------------------------------------------------------------------------


@app.command()
def stream(
    job: str = typer.Option(..., help="Job ID"),
    server: str = typer.Option("http://127.0.0.1:8080", help="API server URL"),
) -> None:
    """Stream SSE events from API server."""
    import urllib.request

    url = f"{server.rstrip('/')}/jobs/{job}/events/stream"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    print(line[5:].strip())
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@app.command()
def serve(
    addr: str = typer.Option("127.0.0.1:8080", help="Listen address"),
    workspace: str = typer.Option("", help="Workspace directory"),
    recover: bool = typer.Option(False, help="Recover interrupted jobs"),
    recover_jobs: str = typer.Option("", help="Comma-separated job IDs to recover"),
) -> None:
    """Start the HTTP API server."""
    import uvicorn
    from baton.api.server import create_app

    ws = workspace or _current_workspace()
    service = _build_service(ws)

    # PID file
    pid_dir = os.path.join(ws, ".baton")
    os.makedirs(pid_dir, exist_ok=True)
    pid_file = os.path.join(pid_dir, "serve.pid")
    _write_pid_file(pid_file, os.getpid(), addr)

    application = create_app(service)

    host, _, port_str = addr.rpartition(":")
    host = host or "127.0.0.1"
    port = int(port_str) if port_str else 8080

    print(f"baton API listening on {addr} (workspace: {ws})")

    try:
        uvicorn.run(application, host=host, port=port, log_level="info")
    finally:
        _remove_pid_file(pid_file)


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


@app.command()
def stop(
    workspace: str = typer.Option("", help="Workspace directory"),
    addr: str = typer.Option("", help="Serve address (overrides PID file)"),
) -> None:
    """Graceful shutdown of running serve."""
    import urllib.request

    if addr:
        _send_shutdown(addr)
        return

    ws = workspace or _current_workspace()
    pid_file = os.path.join(ws, ".baton", "serve.pid")
    try:
        with open(pid_file) as f:
            info = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        typer.echo(f"Error: no running serve found ({pid_file}): {exc}", err=True)
        raise typer.Exit(1)

    _send_shutdown(info["addr"])
    print(f"shutdown requested (pid {info['pid']}, addr {info['addr']})")


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------


@app.command()
def mcp(
    recover: bool = typer.Option(False, help="Recover interrupted jobs"),
    recover_jobs: str = typer.Option("", help="Comma-separated job IDs to recover"),
) -> None:
    """Start MCP stdio server."""
    from baton.mcp.server import Server

    service = _build_service(_current_workspace())
    mcp_server = Server(service)
    mcp_server.run_sync()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_pid_file(path: str, pid: int, addr: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"pid": pid, "addr": addr}, f)
    except OSError:
        pass


def _remove_pid_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _send_shutdown(addr: str) -> None:
    import urllib.request

    url = f"http://{addr}/admin/shutdown"
    req = urllib.request.Request(url, method="POST", data=b"")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as exc:
        typer.echo(f"Error: failed to contact serve at {addr}: {exc}", err=True)
        raise typer.Exit(1)
