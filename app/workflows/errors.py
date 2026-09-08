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
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details or {},
            }
        }


class WorkflowValidationError(WorkflowError):
    def __init__(self, message: str, code: str = "INVALID_WORKFLOW", details: Any = None, status_code: int = 422):
        super().__init__(message=message, code=code, details=details, status_code=status_code)


class WorkflowRevisionConflictError(WorkflowError):
    def __init__(self, message: str = "Workflow revision conflict", details: Any = None):
        super().__init__(message=message, code="WORKFLOW_REVISION_CONFLICT", details=details, status_code=409)


class WorkflowNotFoundError(WorkflowError):
    def __init__(self, message: str = "Workflow not found", details: Any = None):
        super().__init__(message=message, code="WORKFLOW_NOT_FOUND", details=details, status_code=404)


class RecipeRevisionNotFoundError(WorkflowError):
    def __init__(self, message: str = "Workflow recipe revision not found", details: Any = None):
        super().__init__(message=message, code="RECIPE_REVISION_NOT_FOUND", details=details, status_code=404)


class WorkflowArchivedError(WorkflowError):
    def __init__(self, message: str = "Workflow is archived and cannot be modified or executed", details: Any = None):
        super().__init__(message=message, code="WORKFLOW_ARCHIVED", details=details, status_code=409)


class BuiltinWorkflowImmutableError(WorkflowError):
    def __init__(self, message: str = "Builtin workflow cannot be modified or archived", details: Any = None):
        super().__init__(message=message, code="BUILTIN_WORKFLOW_IMMUTABLE", details=details, status_code=409)


class VirtualGraphCollisionError(WorkflowError):
    def __init__(self, message: str, details: Any = None):
        super().__init__(message=message, code="PATH_COLLISION", details=details, status_code=409)


class VirtualGraphCycleError(WorkflowError):
    def __init__(self, message: str, details: Any = None):
        super().__init__(message=message, code="PATH_CYCLE", details=details, status_code=409)


class WorkflowBoundaryError(WorkflowError):
    def __init__(self, message: str, details: Any = None):
        super().__init__(message=message, code="PATH_OUTSIDE_ALLOWED_ROOT", details=details, status_code=400)


class WorkflowSafetyLimitExceededError(WorkflowError):
    def __init__(self, message: str, details: Any = None):
        super().__init__(message=message, code="WORKFLOW_LIMIT_EXCEEDED", details=details, status_code=422)


class WorkflowDigestMismatchError(WorkflowError):
    def __init__(self, message: str = "Workflow compile digest has changed", details: Any = None):
        super().__init__(message=message, code="PREVIEW_CHANGED", details=details, status_code=409)


class DedupeRescanRequiredError(WorkflowError):
    def __init__(self, message: str = "Stale dedupe plan requires a new scan before rebuild", details: Any = None):
        super().__init__(message=message, code="DEDUPE_RESCAN_REQUIRED", details=details, status_code=409)

