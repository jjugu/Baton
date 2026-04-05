"""Provider error taxonomy.

12 error kinds with recommended actions (retry / block / fail).
"""

from __future__ import annotations

from enum import Enum

from baton.domain.types import ProviderName


class ErrorKind(str, Enum):
    MISSING_EXECUTABLE = "missing_executable"
    PROBE_FAILED = "probe_failed"
    COMMAND_FAILED = "command_failed"
    INVALID_RESPONSE = "invalid_response"
    UNSUPPORTED_PHASE = "unsupported_phase"
    AUTH_FAILURE = "auth_failure"
    QUOTA_EXCEEDED = "quota_exceeded"
    RATE_LIMITED = "rate_limited"
    BILLING_REQUIRED = "billing_required"
    SESSION_EXPIRED = "session_expired"
    NETWORK_ERROR = "network_error"
    TRANSPORT_ERROR = "transport_error"


class ErrorAction(str, Enum):
    RETRY = "retry"
    BLOCK = "block"
    FAIL = "fail"


def recommended_action(kind: ErrorKind) -> ErrorAction:
    """Map an error kind to its default recommended action."""
    match kind:
        case ErrorKind.RATE_LIMITED | ErrorKind.NETWORK_ERROR:
            return ErrorAction.RETRY
        case ErrorKind.AUTH_FAILURE | ErrorKind.BILLING_REQUIRED | ErrorKind.SESSION_EXPIRED:
            return ErrorAction.BLOCK
        case _:
            return ErrorAction.FAIL


# Pre-structured failure kinds eligible for fallback-model retry
_FALLBACK_ELIGIBLE: frozenset[ErrorKind] = frozenset({
    ErrorKind.COMMAND_FAILED,
    ErrorKind.AUTH_FAILURE,
    ErrorKind.QUOTA_EXCEEDED,
    ErrorKind.RATE_LIMITED,
    ErrorKind.BILLING_REQUIRED,
    ErrorKind.SESSION_EXPIRED,
    ErrorKind.NETWORK_ERROR,
    ErrorKind.TRANSPORT_ERROR,
})


def is_fallback_eligible(kind: ErrorKind) -> bool:
    return kind in _FALLBACK_ELIGIBLE


class ProviderError(Exception):
    """Structured provider-layer error with classification metadata."""

    def __init__(
        self,
        provider: ProviderName,
        kind: ErrorKind,
        *,
        executable: str = "",
        detail: str = "",
        cause: Exception | None = None,
    ) -> None:
        self.provider = provider
        self.kind = kind
        self.recommended_action = recommended_action(kind)
        self.executable = executable
        self.detail = detail
        self.cause = cause

        parts: list[str] = [f"{provider} provider {kind.value}"]
        if executable:
            parts[0] += f" ({executable})"
        if detail:
            parts.append(detail)
        super().__init__(": ".join(parts))

    def __repr__(self) -> str:
        return (
            f"ProviderError(provider={self.provider!r}, kind={self.kind!r}, "
            f"detail={self.detail!r})"
        )


# ---------------------------------------------------------------------------
# Factory helpers -- keep call sites concise
# ---------------------------------------------------------------------------

def _new(
    provider: ProviderName,
    kind: ErrorKind,
    executable: str,
    detail: str,
    cause: Exception | None = None,
) -> ProviderError:
    return ProviderError(
        provider, kind, executable=executable, detail=detail, cause=cause,
    )


def missing_executable_error(
    provider: ProviderName, executable: str, cause: Exception | None = None,
) -> ProviderError:
    return _new(provider, ErrorKind.MISSING_EXECUTABLE, executable,
                "CLI executable is not available on PATH", cause)


def probe_failed_error(
    provider: ProviderName, executable: str, cause: Exception | None = None,
) -> ProviderError:
    return _new(provider, ErrorKind.PROBE_FAILED, executable,
                "CLI probe failed", cause)


def command_failed_error(
    provider: ProviderName, executable: str, cause: Exception | None = None,
) -> ProviderError:
    return _new(provider, ErrorKind.COMMAND_FAILED, executable,
                "provider command failed", cause)


def invalid_response_error(
    provider: ProviderName, executable: str, detail: str,
    cause: Exception | None = None,
) -> ProviderError:
    return _new(provider, ErrorKind.INVALID_RESPONSE, executable, detail, cause)


def unsupported_phase_error(
    provider: ProviderName, executable: str, phase: str,
) -> ProviderError:
    return _new(provider, ErrorKind.UNSUPPORTED_PHASE, executable,
                f"provider does not support {phase} phase")


def auth_failure_error(
    provider: ProviderName, executable: str, cause: Exception | None = None,
) -> ProviderError:
    return _new(provider, ErrorKind.AUTH_FAILURE, executable,
                "provider authentication failed", cause)


def quota_exceeded_error(
    provider: ProviderName, executable: str, cause: Exception | None = None,
) -> ProviderError:
    return _new(provider, ErrorKind.QUOTA_EXCEEDED, executable,
                "provider quota exceeded", cause)


def rate_limited_error(
    provider: ProviderName, executable: str, cause: Exception | None = None,
) -> ProviderError:
    return _new(provider, ErrorKind.RATE_LIMITED, executable,
                "provider rate limited", cause)


def billing_required_error(
    provider: ProviderName, executable: str, cause: Exception | None = None,
) -> ProviderError:
    return _new(provider, ErrorKind.BILLING_REQUIRED, executable,
                "provider billing is required", cause)


def session_expired_error(
    provider: ProviderName, executable: str, cause: Exception | None = None,
) -> ProviderError:
    return _new(provider, ErrorKind.SESSION_EXPIRED, executable,
                "provider session expired", cause)


def network_error(
    provider: ProviderName, executable: str, cause: Exception | None = None,
) -> ProviderError:
    return _new(provider, ErrorKind.NETWORK_ERROR, executable,
                "provider network error", cause)


def transport_error(
    provider: ProviderName, executable: str, cause: Exception | None = None,
) -> ProviderError:
    return _new(provider, ErrorKind.TRANSPORT_ERROR, executable,
                "provider transport error", cause)


# ---------------------------------------------------------------------------
# Error classification from command output
# ---------------------------------------------------------------------------

_CLASSIFICATION_RULES: list[tuple[list[str], type[...] | None]] = [
    # (patterns, factory)  -- order matters; first match wins
]


def _contains_any(text: str, *patterns: str) -> bool:
    lowered = text.lower()
    return any(p in lowered for p in patterns)


def classify_command_error(
    provider: ProviderName,
    executable: str,
    stdout: str,
    stderr: str,
    cause: Exception | None = None,
) -> ProviderError:
    """Classify a failed CLI command into the appropriate ProviderError.

    Inspects stdout, stderr, and the exception message to detect known
    error patterns (rate limits, auth failures, etc.).
    """
    combined = "\n".join([
        stderr or "",
        stdout or "",
        str(cause) if cause else "",
    ]).lower().strip()

    if _contains_any(combined, "rate limit", "rate-limit", "too many requests", "429"):
        return rate_limited_error(provider, executable, cause)
    if _contains_any(combined, "authentication", "unauthorized",
                     "invalid api key", "api key", "401"):
        return auth_failure_error(provider, executable, cause)
    if _contains_any(combined, "billing", "payment required", "402",
                     "payment method", "credit balance"):
        return billing_required_error(provider, executable, cause)
    if _contains_any(combined, "insufficient_quota", "quota exceeded",
                     "quota", "usage limit", "credits exhausted"):
        return quota_exceeded_error(provider, executable, cause)
    if _contains_any(combined, "session expired", "session has expired",
                     "login expired", "reauthenticate", "re-authenticate"):
        return session_expired_error(provider, executable, cause)
    if _contains_any(combined, "timeout", "timed out", "connection reset",
                     "connection refused", "network is unreachable",
                     "temporary failure in name resolution", "no such host",
                     "econnreset", "econnrefused", "tls handshake timeout"):
        return network_error(provider, executable, cause)
    if _contains_any(combined, "transport", "broken pipe", "unexpected eof",
                     "stream closed", "protocol error",
                     "connection closed unexpectedly"):
        return transport_error(provider, executable, cause)
    return command_failed_error(provider, executable, cause)
