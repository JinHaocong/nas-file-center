from __future__ import annotations

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models import IndexRoot, OrganizerProfile
from app.service import FileCenterService
from app.workflows.schema import OrganizerProfileSnapshot


def test_red_minimal_defaults_mismatch(tmp_path: Path):
    """RED: Current OrganizerProfileSnapshot defaults mismatch real created OrganizerProfile defaults."""
    settings = Settings(
        config_dir=tmp_path / "cfg",
        data_mount=tmp_path / "data",
        quarantine_root=tmp_path / "quar",
        allowed_roots_raw=str(tmp_path / "data"),
    )
    service = FileCenterService(settings)
    created = service._validate_profile_payload({"name": "Minimal"})

    snapshot = OrganizerProfileSnapshot(name="Minimal")

    # Real OrganizerProfile defaults:
    real_image_exts = json.loads(created["image_extensions"])
    real_video_exts = json.loads(created["video_extensions"])
    assert real_image_exts == ["jpg", "jpeg", "png", "webp"]
    assert real_video_exts == ["mp4", "mov", "mkv"]
    assert created["rename_template"] == "{name}"
    assert created["statistics_template"] == "[{images}P {videos}V {size}]"

    # Current snapshot fails these assertions:
    assert snapshot.image_extensions == real_image_exts
    assert snapshot.video_extensions == real_video_exts
    assert snapshot.rename_template == created["rename_template"]
    assert snapshot.statistics_template == created["statistics_template"]


def test_red_whitespace_name_rejected():
    """RED: Whitespace-only name must be rejected."""
    with pytest.raises(ValidationError):
        OrganizerProfileSnapshot(name="   ")


def test_red_extensions_normalized():
    """RED: Extension list with uppercase and leading dots must be normalized."""
    s = OrganizerProfileSnapshot(name="test", image_extensions=[".JPG", "jpg", "PNG"])
    assert s.image_extensions == ["jpg", "png"]


def test_red_invalid_extension_rejected():
    """RED: Invalid extensions with slashes, backslashes, or spaces must be rejected."""
    with pytest.raises(ValidationError):
        OrganizerProfileSnapshot(name="test", image_extensions=["jpg/bad"])

    with pytest.raises(ValidationError):
        OrganizerProfileSnapshot(name="test", image_extensions=["mkv\\bad"])

    with pytest.raises(ValidationError):
        OrganizerProfileSnapshot(name="test", image_extensions=["a b"])


def test_red_preserve_tags_normalized():
    """RED: preserve_tags must trim whitespace and drop empty strings."""
    s = OrganizerProfileSnapshot(name="test", preserve_tags=["  HDR  ", "", " RAW "])
    assert s.preserve_tags == ["HDR", "RAW"]
