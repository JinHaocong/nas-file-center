from typing import Any


class BatchUtilityError(Exception):
    """Base error for all Gate5-E batch utility exceptions with structured error envelope."""

    def __init__(
        self,
        message: str,
        code: str,
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class BatchUtilityInvalidConfigError(BatchUtilityError):
    def __init__(
        self,
        message: str = "Invalid batch utility configuration",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code="BATCH_UTILITY_INVALID_CONFIG",
            status_code=422,
            details=details,
        )


class BatchUtilityLimitExceededError(BatchUtilityError):
    def __init__(
        self,
        message: str = "Batch utility limit exceeded",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code="BATCH_UTILITY_LIMIT_EXCEEDED",
            status_code=422,
            details=details,
        )


class BatchUtilityEmptyPlanError(BatchUtilityError):
    def __init__(
        self,
        message: str = "Batch utility plan would be empty",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code="BATCH_UTILITY_EMPTY_PLAN",
            status_code=422,
            details=details,
        )


class BatchUtilityPreviewChangedError(BatchUtilityError):
    def __init__(
        self,
        message: str = "Batch utility preview has changed",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code="PREVIEW_CHANGED",
            status_code=409,
            details=details,
        )


class BatchUtilityScopeNotFoundError(BatchUtilityError):
    def __init__(
        self,
        message: str = "Batch utility scope root not found",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code="BATCH_UTILITY_SCOPE_NOT_FOUND",
            status_code=404,
            details=details,
        )


class BatchUtilityConflictError(BatchUtilityError):
    def __init__(
        self,
        message: str = "Blocking conflicts detected in batch utility plan",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code="BATCH_UTILITY_CONFLICT",
            status_code=409,
            details=details,
        )


class BatchUtilitySymlinkBlockedError(BatchUtilityConflictError):
    def __init__(
        self,
        message: str = "Target path is a symlink",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            details=details,
        )
        self.code = "BATCH_UTILITY_SYMLINK_BLOCKED"


class BatchUtilityCrossRootError(BatchUtilityConflictError):
    def __init__(
        self,
        message: str = "Target path is outside allowed roots",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            details=details,
        )
        self.code = "BATCH_UTILITY_CROSS_ROOT"


class BatchUtilityNameTooLongError(BatchUtilityConflictError):
    def __init__(
        self,
        message: str = "Target filename exceeds maximum length",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            details=details,
        )
        self.code = "BATCH_UTILITY_NAME_TOO_LONG"


class BatchUtilityCaseCollisionError(BatchUtilityConflictError):
    def __init__(
        self,
        message: str = "Case-only collision detected for target path",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            details=details,
        )
        self.code = "BATCH_UTILITY_CASE_COLLISION"


class BatchUtilityCollisionError(BatchUtilityConflictError):
    def __init__(
        self,
        message: str = "Target collision or cycle detected in batch utility plan",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            details=details,
        )
        self.code = "BATCH_UTILITY_COLLISION"

