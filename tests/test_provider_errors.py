"""Cross-validate baton/provider/errors.py against Go provider/errors.go.

Tests verify:
- All 12 ErrorKind values match Go
- All 3 ErrorAction values match Go
- ErrorKind -> recommended action mapping matches Go
- Fallback eligibility set matches Go isPreStructuredProviderFailure
- classify_command_error pattern matching matches Go classifyCommandError
- Factory function signatures and messages match Go
"""
from __future__ import annotations

from baton.domain.types import ProviderName
from baton.provider.errors import (
    ErrorAction,
    ErrorKind,
    ProviderError,
    classify_command_error,
    is_fallback_eligible,
    recommended_action,
    # Factory helpers
    missing_executable_error,
    probe_failed_error,
    command_failed_error,
    invalid_response_error,
    unsupported_phase_error,
    auth_failure_error,
    quota_exceeded_error,
    rate_limited_error,
    billing_required_error,
    session_expired_error,
    network_error,
    transport_error,
)


class TestErrorKindCompleteness:
    def test_all_12_kinds(self, go_error_kinds: frozenset[str]) -> None:
        py_values = {k.value for k in ErrorKind}
        assert py_values == go_error_kinds

    def test_count(self) -> None:
        assert len(ErrorKind) == 12


class TestErrorActionCompleteness:
    def test_all_3_actions(self) -> None:
        from tests.conftest import GO_ERROR_ACTIONS
        py_values = {a.value for a in ErrorAction}
        assert py_values == GO_ERROR_ACTIONS


class TestRecommendedActionMapping:
    """Go recommendedActionForKind() must match Python recommended_action()."""

    def test_full_mapping(self, go_error_action_map: dict[str, str]) -> None:
        for kind_str, expected_action in go_error_action_map.items():
            kind = ErrorKind(kind_str)
            actual = recommended_action(kind)
            assert actual.value == expected_action, (
                f"ErrorKind.{kind.name}: expected {expected_action}, got {actual.value}"
            )


class TestFallbackEligibility:
    """Go isPreStructuredProviderFailure must match Python is_fallback_eligible."""

    def test_eligible_kinds(self) -> None:
        # Go: CommandFailed, AuthFailure, QuotaExceeded, RateLimited,
        #     BillingRequired, SessionExpired, NetworkError, TransportError
        expected_eligible = {
            ErrorKind.COMMAND_FAILED,
            ErrorKind.AUTH_FAILURE,
            ErrorKind.QUOTA_EXCEEDED,
            ErrorKind.RATE_LIMITED,
            ErrorKind.BILLING_REQUIRED,
            ErrorKind.SESSION_EXPIRED,
            ErrorKind.NETWORK_ERROR,
            ErrorKind.TRANSPORT_ERROR,
        }
        for kind in ErrorKind:
            expected = kind in expected_eligible
            actual = is_fallback_eligible(kind)
            assert actual == expected, (
                f"ErrorKind.{kind.name}: fallback eligible expected={expected}, got={actual}"
            )


class TestProviderErrorConstruction:
    def test_fields(self) -> None:
        err = ProviderError(
            ProviderName.CLAUDE,
            ErrorKind.RATE_LIMITED,
            executable="claude",
            detail="too fast",
        )
        assert err.provider == ProviderName.CLAUDE
        assert err.kind == ErrorKind.RATE_LIMITED
        assert err.recommended_action == ErrorAction.RETRY
        assert err.executable == "claude"
        assert err.detail == "too fast"

    def test_str_format_with_executable_and_detail(self) -> None:
        """Go: fmt.Sprintf(\"%s provider %s (%s): %s\", ...)"""
        err = ProviderError(
            ProviderName.CODEX,
            ErrorKind.AUTH_FAILURE,
            executable="codex-cli",
            detail="invalid token",
        )
        msg = str(err)
        assert "codex" in msg
        assert "auth_failure" in msg
        assert "codex-cli" in msg
        assert "invalid token" in msg


class TestFactoryHelpers:
    """Verify each factory produces the correct ErrorKind and detail."""

    def test_missing_executable(self) -> None:
        err = missing_executable_error(ProviderName.CODEX, "codex-cli")
        assert err.kind == ErrorKind.MISSING_EXECUTABLE
        assert "PATH" in err.detail

    def test_probe_failed(self) -> None:
        err = probe_failed_error(ProviderName.CLAUDE, "claude")
        assert err.kind == ErrorKind.PROBE_FAILED
        assert "probe" in err.detail.lower()

    def test_command_failed(self) -> None:
        err = command_failed_error(ProviderName.MOCK, "mock-cli")
        assert err.kind == ErrorKind.COMMAND_FAILED

    def test_invalid_response(self) -> None:
        err = invalid_response_error(ProviderName.CLAUDE, "claude", "bad json")
        assert err.kind == ErrorKind.INVALID_RESPONSE
        assert err.detail == "bad json"

    def test_unsupported_phase(self) -> None:
        err = unsupported_phase_error(ProviderName.CODEX, "codex-cli", "evaluator")
        assert err.kind == ErrorKind.UNSUPPORTED_PHASE
        assert "evaluator" in err.detail

    def test_auth_failure(self) -> None:
        err = auth_failure_error(ProviderName.CLAUDE, "claude")
        assert err.kind == ErrorKind.AUTH_FAILURE
        assert err.recommended_action == ErrorAction.BLOCK

    def test_quota_exceeded(self) -> None:
        err = quota_exceeded_error(ProviderName.CLAUDE, "claude")
        assert err.kind == ErrorKind.QUOTA_EXCEEDED
        assert err.recommended_action == ErrorAction.FAIL

    def test_rate_limited(self) -> None:
        err = rate_limited_error(ProviderName.CLAUDE, "claude")
        assert err.kind == ErrorKind.RATE_LIMITED
        assert err.recommended_action == ErrorAction.RETRY

    def test_billing_required(self) -> None:
        err = billing_required_error(ProviderName.CODEX, "codex-cli")
        assert err.kind == ErrorKind.BILLING_REQUIRED
        assert err.recommended_action == ErrorAction.BLOCK

    def test_session_expired(self) -> None:
        err = session_expired_error(ProviderName.CLAUDE, "claude")
        assert err.kind == ErrorKind.SESSION_EXPIRED
        assert err.recommended_action == ErrorAction.BLOCK

    def test_network(self) -> None:
        err = network_error(ProviderName.CLAUDE, "claude")
        assert err.kind == ErrorKind.NETWORK_ERROR
        assert err.recommended_action == ErrorAction.RETRY

    def test_transport(self) -> None:
        err = transport_error(ProviderName.CLAUDE, "claude")
        assert err.kind == ErrorKind.TRANSPORT_ERROR
        assert err.recommended_action == ErrorAction.FAIL


class TestClassifyCommandError:
    """Must match Go classifyCommandError pattern-matching order."""

    def test_rate_limit(self) -> None:
        err = classify_command_error(
            ProviderName.CLAUDE, "claude",
            stdout="", stderr="Error: rate limit exceeded", cause=None,
        )
        assert err.kind == ErrorKind.RATE_LIMITED

    def test_429(self) -> None:
        err = classify_command_error(
            ProviderName.CLAUDE, "claude",
            stdout="429 Too Many Requests", stderr="", cause=None,
        )
        assert err.kind == ErrorKind.RATE_LIMITED

    def test_auth_failure(self) -> None:
        err = classify_command_error(
            ProviderName.CODEX, "codex-cli",
            stdout="", stderr="401 unauthorized", cause=None,
        )
        assert err.kind == ErrorKind.AUTH_FAILURE

    def test_billing(self) -> None:
        err = classify_command_error(
            ProviderName.CLAUDE, "claude",
            stdout="", stderr="payment required 402", cause=None,
        )
        assert err.kind == ErrorKind.BILLING_REQUIRED

    def test_quota(self) -> None:
        err = classify_command_error(
            ProviderName.CLAUDE, "claude",
            stdout="", stderr="insufficient_quota", cause=None,
        )
        assert err.kind == ErrorKind.QUOTA_EXCEEDED

    def test_session_expired(self) -> None:
        err = classify_command_error(
            ProviderName.CLAUDE, "claude",
            stdout="", stderr="session expired, please reauthenticate", cause=None,
        )
        assert err.kind == ErrorKind.SESSION_EXPIRED

    def test_network_timeout(self) -> None:
        err = classify_command_error(
            ProviderName.CLAUDE, "claude",
            stdout="", stderr="connection refused", cause=None,
        )
        assert err.kind == ErrorKind.NETWORK_ERROR

    def test_transport_broken_pipe(self) -> None:
        err = classify_command_error(
            ProviderName.CLAUDE, "claude",
            stdout="", stderr="broken pipe in transport layer", cause=None,
        )
        assert err.kind == ErrorKind.TRANSPORT_ERROR

    def test_unknown_defaults_to_command_failed(self) -> None:
        err = classify_command_error(
            ProviderName.CLAUDE, "claude",
            stdout="", stderr="something went wrong", cause=None,
        )
        assert err.kind == ErrorKind.COMMAND_FAILED
