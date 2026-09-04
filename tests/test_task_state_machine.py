from __future__ import annotations

import pytest

from app.tasks.state_machine import (
    JobState,
    JobTransitionError,
    JobPauseRequested,
    JobCancelRequested,
    validate_transition,
    can_transition,
    TERMINAL_STATES,
)


def test_job_states_constants():
    assert JobState.QUEUED == "queued"
    assert JobState.RUNNING == "running"
    assert JobState.PAUSED == "paused"
    assert JobState.CANCEL_REQUESTED == "cancel_requested"
    assert JobState.CANCELLED == "cancelled"
    assert JobState.FAILED == "failed"
    assert JobState.COMPLETED == "completed"

    assert TERMINAL_STATES == {"cancelled", "failed", "completed"}


def test_valid_transitions():
    # queued transitions
    assert can_transition(JobState.QUEUED, JobState.RUNNING) is True
    assert can_transition(JobState.QUEUED, JobState.PAUSED) is True
    assert can_transition(JobState.QUEUED, JobState.CANCELLED) is True

    # running transitions
    assert can_transition(JobState.RUNNING, JobState.PAUSED) is True
    assert can_transition(JobState.RUNNING, JobState.CANCEL_REQUESTED) is True
    assert can_transition(JobState.RUNNING, JobState.COMPLETED) is True
    assert can_transition(JobState.RUNNING, JobState.FAILED) is True

    # cancel_requested transitions
    assert can_transition(JobState.CANCEL_REQUESTED, JobState.CANCELLED) is True
    assert can_transition(JobState.CANCEL_REQUESTED, JobState.FAILED) is True

    # paused transitions
    assert can_transition(JobState.PAUSED, JobState.QUEUED) is True
    assert can_transition(JobState.PAUSED, JobState.CANCELLED) is True

    # validate_transition does not raise for valid moves
    validate_transition(JobState.QUEUED, JobState.RUNNING)
    validate_transition(JobState.RUNNING, JobState.COMPLETED)
    validate_transition(JobState.PAUSED, JobState.QUEUED)


def test_invalid_transitions():
    # terminal states cannot transition to anything
    for term in TERMINAL_STATES:
        for target in [JobState.QUEUED, JobState.RUNNING, JobState.PAUSED, JobState.COMPLETED, JobState.FAILED]:
            assert can_transition(term, target) is False
            with pytest.raises(JobTransitionError):
                validate_transition(term, target)

    # queued cannot jump directly to completed or failed
    assert can_transition(JobState.QUEUED, JobState.COMPLETED) is False
    assert can_transition(JobState.QUEUED, JobState.FAILED) is False

    # paused cannot jump directly to running or completed
    assert can_transition(JobState.PAUSED, JobState.RUNNING) is False
    assert can_transition(JobState.PAUSED, JobState.COMPLETED) is False

    # running cannot go back to queued directly
    assert can_transition(JobState.RUNNING, JobState.QUEUED) is False


def test_controlled_exceptions():
    pause_exc = JobPauseRequested("Pause requested at checkpoint")
    cancel_exc = JobCancelRequested("Cancel requested at checkpoint")

    assert isinstance(pause_exc, BaseException)
    assert isinstance(cancel_exc, BaseException)
    # Ensure they are distinct custom exception types
    assert issubclass(JobPauseRequested, Exception)
    assert issubclass(JobCancelRequested, Exception)
