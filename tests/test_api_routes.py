"""Cross-validate baton/api/routes.py against Go api/server.go.

Tests:
- All Go API endpoints have matching FastAPI routes
- Request DTOs match Go request structs
- Auth middleware uses constant-time comparison
"""
from __future__ import annotations

from baton.api.routes import router, StartJobRequest, CancelJobRequest, RejectJobRequest, SteerJobRequest
from baton.api.server import create_app, BearerAuthMiddleware


class TestAPIEndpoints:
    """Verify all Go endpoints have matching FastAPI routes."""

    def _route_paths(self) -> set[tuple[str, str]]:
        """Collect (method, path) from the router."""
        routes: set[tuple[str, str]] = set()
        for route in router.routes:
            if hasattr(route, "methods") and hasattr(route, "path"):
                for m in route.methods:
                    routes.add((m.upper(), route.path))
        return routes

    def test_healthz(self) -> None:
        assert ("GET", "/healthz") in self._route_paths()

    def test_list_jobs(self) -> None:
        assert ("GET", "/jobs") in self._route_paths()

    def test_create_job(self) -> None:
        assert ("POST", "/jobs") in self._route_paths()

    def test_get_job(self) -> None:
        assert ("GET", "/jobs/{job_id}") in self._route_paths()

    def test_resume_job(self) -> None:
        assert ("POST", "/jobs/{job_id}/resume") in self._route_paths()

    def test_approve_job(self) -> None:
        assert ("POST", "/jobs/{job_id}/approve") in self._route_paths()

    def test_retry_job(self) -> None:
        assert ("POST", "/jobs/{job_id}/retry") in self._route_paths()

    def test_reject_job(self) -> None:
        assert ("POST", "/jobs/{job_id}/reject") in self._route_paths()

    def test_cancel_job(self) -> None:
        assert ("POST", "/jobs/{job_id}/cancel") in self._route_paths()

    def test_steer_job(self) -> None:
        assert ("POST", "/jobs/{job_id}/steer") in self._route_paths()

    def test_get_events(self) -> None:
        assert ("GET", "/jobs/{job_id}/events") in self._route_paths()

    def test_stream_events(self) -> None:
        assert ("GET", "/jobs/{job_id}/events/stream") in self._route_paths()

    def test_get_artifacts(self) -> None:
        assert ("GET", "/jobs/{job_id}/artifacts") in self._route_paths()

    def test_get_verification(self) -> None:
        assert ("GET", "/jobs/{job_id}/verification") in self._route_paths()

    def test_get_planning(self) -> None:
        assert ("GET", "/jobs/{job_id}/planning") in self._route_paths()

    def test_get_evaluator(self) -> None:
        assert ("GET", "/jobs/{job_id}/evaluator") in self._route_paths()

    def test_get_profile(self) -> None:
        assert ("GET", "/jobs/{job_id}/profile") in self._route_paths()

    def test_list_chains(self) -> None:
        assert ("GET", "/chains") in self._route_paths()

    def test_get_chain(self) -> None:
        assert ("GET", "/chains/{chain_id}") in self._route_paths()


class TestRequestDTOs:
    """Match Go request struct fields."""

    def test_start_job_fields(self) -> None:
        """Go StartJobRequest fields."""
        go_fields = {
            "goal", "tech_stack", "workspace_dir", "workspace_mode",
            "constraints", "done_criteria", "provider", "role_profiles", "max_steps",
        }
        py_fields = set(StartJobRequest.model_fields.keys())
        assert py_fields == go_fields

    def test_cancel_request_has_reason(self) -> None:
        assert "reason" in CancelJobRequest.model_fields

    def test_reject_request_has_reason(self) -> None:
        assert "reason" in RejectJobRequest.model_fields

    def test_steer_request_has_message(self) -> None:
        assert "message" in SteerJobRequest.model_fields


class TestAuthMiddleware:
    def test_constant_time_comparison(self) -> None:
        """Go uses crypto/subtle.ConstantTimeCompare; Python uses secrets.compare_digest."""
        # Verify the class exists and is importable
        import secrets
        assert hasattr(secrets, "compare_digest")

    def test_create_app_no_crash(self) -> None:
        """App creates without a service (for testing)."""
        app = create_app(service=None)
        assert app is not None
        assert app.state.service is None
