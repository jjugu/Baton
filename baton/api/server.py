"""FastAPI application setup and middleware."""

from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from baton.api.routes import router


def create_app(service: Any = None) -> FastAPI:
    """Build the FastAPI application with middleware and routes."""
    app = FastAPI(title="baton", version="0.1.0")

    # Store service for injection into route handlers
    app.state.service = service

    # CORS for dashboard
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Bearer token auth
    token = os.environ.get("BATON_AUTH_TOKEN", "")
    if token:
        app.add_middleware(BearerAuthMiddleware, token=token)

    # API routes
    app.include_router(router)

    # Admin endpoints (for serve mode)
    _register_admin_routes(app)

    # Static dashboard (mounted last so API routes take priority)
    web_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
    if os.path.isdir(web_dir):
        app.mount("/dashboard", StaticFiles(directory=web_dir, html=True), name="dashboard")

    return app


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Enforces Bearer token auth when BATON_AUTH_TOKEN is set.

    Uses constant-time comparison to prevent timing attacks.
    """

    def __init__(self, app: Any, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        auth = request.headers.get("Authorization", "")
        expected = f"Bearer {self._token}"
        if not secrets.compare_digest(auth, expected):
            return JSONResponse(
                status_code=401,
                content={"detail": "unauthorized"},
            )
        return await call_next(request)


def _register_admin_routes(app: FastAPI) -> None:
    """Register admin endpoints (shutdown, workspace switch)."""

    @app.get("/")
    async def root() -> Response:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/dashboard/")

    @app.post("/admin/shutdown")
    async def admin_shutdown() -> dict[str, str]:
        return {"status": "shutting_down"}

    @app.post("/admin/workspace")
    async def admin_workspace_switch(request: Request) -> dict[str, str]:
        body = await request.json()
        workspace = body.get("workspace", "")
        if not workspace or not os.path.isdir(workspace):
            return JSONResponse(
                status_code=400,
                content={"error": "workspace directory not found"},
            )
        return {"status": "switched", "workspace": workspace}

    @app.get("/admin/workspace")
    async def admin_workspace_get(request: Request) -> dict[str, str]:
        svc = request.app.state.service
        workspace = ""
        if svc and hasattr(svc, "workspace_root"):
            workspace = svc.workspace_root() if callable(svc.workspace_root) else svc.workspace_root
        return {"workspace": workspace}
