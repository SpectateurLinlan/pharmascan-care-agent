"""Domain error hierarchy with stable error codes (API error envelope)."""

from __future__ import annotations

from ..contracts.enums import ErrorCode, PolicyRuleId


class DomainError(Exception):
    code = ErrorCode.INTERNAL_ERROR

    def __init__(self, message: str, *, rule_id: PolicyRuleId | None = None) -> None:
        super().__init__(message)
        self.rule_id = rule_id


class ValidationError(DomainError):
    code = ErrorCode.INVALID_INPUT


class AuthenticationRequiredError(DomainError):
    """Raised at the transport boundary when no verified identity is present.

    The message must never contain the presented token, header or any claim
    value other than the identity that was successfully verified.
    """

    code = ErrorCode.AUTH_REQUIRED

    def __init__(self, message: str = "Authentication is required") -> None:
        super().__init__(message)


class NotFoundError(DomainError):
    code = ErrorCode.NOT_FOUND


class SourceUnreviewedError(DomainError):
    code = ErrorCode.SOURCE_UNREVIEWED

    def __init__(self, message: str) -> None:
        super().__init__(message, rule_id=PolicyRuleId.SOURCE_REVIEW_REQUIRED)


class IncompleteRegimenError(DomainError):
    code = ErrorCode.INCOMPLETE_REGIMEN

    def __init__(self, message: str) -> None:
        super().__init__(message, rule_id=PolicyRuleId.COMPLETE_REGIMEN_REQUIRED)


class StaleVersionError(DomainError):
    code = ErrorCode.STALE_VERSION

    def __init__(self, message: str) -> None:
        super().__init__(message, rule_id=PolicyRuleId.CURRENT_VERSION_REQUIRED)


class ConfirmationRequiredError(DomainError):
    code = ErrorCode.CONFIRMATION_REQUIRED

    def __init__(self, message: str) -> None:
        super().__init__(message, rule_id=PolicyRuleId.EXPLICIT_CONFIRMATION_REQUIRED)


class ConfirmationExpiredError(DomainError):
    code = ErrorCode.CONFIRMATION_EXPIRED

    def __init__(self, message: str) -> None:
        super().__init__(message, rule_id=PolicyRuleId.EXPLICIT_CONFIRMATION_REQUIRED)


class DuplicateEventError(DomainError):
    code = ErrorCode.DUPLICATE_EVENT

    def __init__(self, message: str) -> None:
        super().__init__(message, rule_id=PolicyRuleId.NO_DUPLICATE_EVENT)


class PolicyBlockedError(DomainError):
    code = ErrorCode.POLICY_BLOCKED

    def __init__(self, message: str, rule_id: PolicyRuleId = PolicyRuleId.DEMO_ONLY) -> None:
        super().__init__(message, rule_id=rule_id)


class ProviderUnavailableError(DomainError):
    code = ErrorCode.PROVIDER_UNAVAILABLE
