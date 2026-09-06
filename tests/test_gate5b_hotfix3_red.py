import pytest
from pydantic import ValidationError
from app.workflows.schema import OrganizerProfileSnapshot


def test_sequential_snapshot_accepted():
    """sequential is a real OrganizerProfile numbering mode and must be accepted."""
    s = OrganizerProfileSnapshot(name="test", numbering_mode="sequential")
    assert s.numbering_mode == "sequential"


def test_ordered_snapshot_accepted():
    """ordered is a real OrganizerProfile mtime mode and must be accepted."""
    s = OrganizerProfileSnapshot(name="test", mtime_mode="ordered")
    assert s.mtime_mode == "ordered"


def test_continuous_snapshot_rejected():
    """continuous is NOT a valid OrganizerProfile numbering mode and must be rejected."""
    with pytest.raises(ValidationError):
        OrganizerProfileSnapshot(name="test", numbering_mode="continuous")


def test_delay_snapshot_rejected():
    """delay is NOT a valid OrganizerProfile mtime mode and must be rejected."""
    with pytest.raises(ValidationError):
        OrganizerProfileSnapshot(name="test", mtime_mode="delay")


def test_numbering_padding_1000_rejected():
    """numbering_padding must be bounded to 1..10 and reject 1000."""
    with pytest.raises(ValidationError):
        OrganizerProfileSnapshot(name="test", numbering_padding=1000)


def test_numbering_start_negative_rejected():
    """numbering_start must be >= 0 and reject -5."""
    with pytest.raises(ValidationError):
        OrganizerProfileSnapshot(name="test", numbering_start=-5)


def test_mtime_delay_seconds_bool_rejected():
    """mtime_delay_seconds must reject boolean values like True."""
    with pytest.raises(ValidationError):
        OrganizerProfileSnapshot(name="test", mtime_delay_seconds=True)
