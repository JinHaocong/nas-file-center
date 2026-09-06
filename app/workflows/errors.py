from __future__ import annotations

from typing import Any


class WorkflowError(Exception):
    """Base class for all workflow-related errors."""

    def __init__(self, message: str, code: str = "WORKFLOW_ERROR", details: Any = None, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        res: dict[str, Any] = {
            "error": self.code,
            "message": self.message,
        }
        if self.details:
            res["details"] = self.details
        return res


class WorkflowValidationError(WorkflowError):
    def __init__(self, message: str, code: str = "WORKFLOW_VALIDATION_ERROR", details: Any = None):
        super().__init__(message=message, code=code, details=details, status_code=400)


class WorkflowRevisionConflictError(WorkflowError):
    def __init__(self, message: str = "Workflow revision conflict", details: Any = None):
        super().__init__(message=message, code="WORKFLOW_REVISION_CONFLICT", details=details, status_code=409)


class WorkflowNotFoundError(WorkflowError):
    def __init__(self, message: str = "Workflow not found", details: Any = None):
        super().__init__(message=message, code="WORKFLOW_NOT_FOUND", details=details, status_code=404)


class WorkflowArchivedError(WorkflowError):
    def __init__(self, message: str = "Workflow is archived and cannot be modified or executed", details: Any = None):
        super().__init__(message=message, code="WORKFLOW_ARCHIVED", details=details, status_code=400)


class VirtualGraphCollisionError(WorkflowError):
    def __init__(self, message: str, details: Any = None):
        super().__init__(message=message, code="PATH_COLLISION", details=details, status_code=400)


class VirtualGraphCycleError(WorkflowError):
    def __init__(self, message: str, details: Any = None):
        super().__init__(message=message, code="PATH_CYCLE", details=details, status_code=400)


class WorkflowBoundaryError(WorkflowError):
    def __init__(self, message: str, details: Any = None):
        super().__init__(message=message, code="PATH_OUTSIDE_ALLOWED_ROOT", details=details, status_code=400)


class WorkflowSafetyLimitExceededError(WorkflowError):
    def __init__(self, message: str, details: Any = None):
        super().__init__(message=message, code="WORKFLOW_LIMIT_EXCEEDED", details=details, status_code=400)


class WorkflowDigestMismatchError(WorkflowError):
    def __init__(self, message: str = "compile_digest mismatch", details: Any = None):
        super().__init__(message=message, code="COMPILE_DIGEST_MISMATCH", details=details, status_code=409)
