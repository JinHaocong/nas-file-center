from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from app.models import utcnow


def test_utcnow_returns_timezone_aware_utc():
    now = utcnow()
    assert now.tzinfo is not None
    assert now.tzinfo == timezone.utc
    iso_str = now.isoformat()
    # Check that ISO serialization includes timezone (+00:00 or Z)
    assert "+00:00" in iso_str or iso_str.endswith("Z")


def test_frontend_directory_picker_modal_uses_format_datetime_helper():
    modal_file = (
        Path(__file__).resolve().parent.parent
        / "frontend"
        / "src"
        / "components"
        / "DirectoryPicker"
        / "DirectoryPickerModal.tsx"
    )
    assert modal_file.exists()
    content = modal_file.read_text(encoding="utf-8")
    assert "formatDateTime(rec.last_used_at)" in content
    assert "toLocaleString" not in content
