"""Domain-level errors for baton."""


class DomainError(Exception):
    """Base exception for domain-layer errors."""


class ValidationError(DomainError):
    """Raised when a domain object fails validation."""


class JobNotFoundError(DomainError):
    """Raised when a requested job does not exist."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"job not found: {job_id}")


class ChainNotFoundError(DomainError):
    """Raised when a requested chain does not exist."""

    def __init__(self, chain_id: str) -> None:
        self.chain_id = chain_id
        super().__init__(f"chain not found: {chain_id}")


class InvalidIDError(DomainError):
    """Raised when an ID contains unsafe characters."""

    def __init__(self, id_value: str, reason: str = "") -> None:
        self.id_value = id_value
        detail = reason or "must match ^[a-zA-Z0-9_\\-.]+$"
        super().__init__(f"invalid ID {id_value!r}: {detail}")
