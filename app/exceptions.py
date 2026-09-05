from __future__ import annotations


class StateConflictError(ValueError):
    """Raised when an operation cannot be performed due to an invalid state."""
    pass
