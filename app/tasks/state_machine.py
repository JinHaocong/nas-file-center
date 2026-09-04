from __future__ import annotations

from enum import Enum


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"

    def __str__(self) -> str:
        return self.value


def _to_str(s: str | JobState) -> str:
    return s.value if hasattr(s, "value") else str(s)


TERMINAL_STATES: set[str] = {
    JobState.CANCELLED.value,
    JobState.FAILED.value,
    JobState.COMPLETED.value,
}

# Explicit state transition map
VALID_TRANSITIONS: dict[str, set[str]] = {
    JobState.QUEUED.value: {
        JobState.RUNNING.value,
        JobState.PAUSED.value,
        JobState.CANCELLED.value,
    },
    JobState.RUNNING.value: {
        JobState.PAUSED.value,
        JobState.CANCEL_REQUESTED.value,
        JobState.COMPLETED.value,
        JobState.FAILED.value,
    },
    JobState.CANCEL_REQUESTED.value: {
        JobState.CANCELLED.value,
        JobState.FAILED.value,
    },
    JobState.PAUSED.value: {
        JobState.QUEUED.value,
        JobState.CANCELLED.value,
    },
    JobState.CANCELLED.value: set(),
    JobState.FAILED.value: set(),
    JobState.COMPLETED.value: set(),
}


class JobTransitionError(ValueError):
    """Raised when an illegal job state transition is attempted."""
    pass


class JobPauseRequested(Exception):
    """Raised at checkpoint boundary when pause was requested."""
    pass


class JobCancelRequested(Exception):
    """Raised at checkpoint boundary or child process poll when cancel was requested."""
    pass


class JobLeaseLost(Exception):
    """Raised when a worker discovers it has lost its exclusive lease ownership during task execution."""
    pass


def can_transition(from_state: str | JobState, to_state: str | JobState) -> bool:
    """Return True if transition from from_state to to_state is valid."""
    allowed = VALID_TRANSITIONS.get(_to_str(from_state), set())
    return _to_str(to_state) in allowed


def validate_transition(from_state: str | JobState, to_state: str | JobState) -> None:
    """Validate transition or raise JobTransitionError with clear context."""
    from_s = _to_str(from_state)
    to_s = _to_str(to_state)
    if from_s in TERMINAL_STATES:
        raise JobTransitionError(f"Terminal job in state '{from_s}' cannot transition to '{to_s}'")
    if not can_transition(from_s, to_s):
        raise JobTransitionError(f"Illegal state transition from '{from_s}' to '{to_s}'")
