from __future__ import annotations


class StateConflictError(ValueError):
    """Raised when an operation cannot be performed due to an invalid state."""
    pass


class PlanStaleError(StateConflictError):
    """Raised when a plan execution fails because files are modified, deleted, or replaced."""

    def __init__(self, plan_id: int, message: str, stale_items: list[dict]):
        super().__init__(message)
        self.plan_id = plan_id
        self.message = message
        self.stale_items = stale_items

