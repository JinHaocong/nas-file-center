from pathlib import Path

import pytest


def test_settings_parse_allowed_roots_from_csv(monkeypatch, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir(); b.mkdir()
    monkeypatch.setenv("ALLOWED_ROOTS", f"{a},{b}")
    from app.config import Settings

    settings = Settings(_env_file=None)
    assert settings.allowed_roots == [a.resolve(), b.resolve()]


def test_require_allowed_path_accepts_child(tmp_path):
    root = tmp_path / "data"
    child = root / "folder" / "file.txt"
    child.parent.mkdir(parents=True)
    child.write_text("x")
    from app.path_safety import require_allowed_path

    assert require_allowed_path(child, [root]) == child.resolve()


def test_require_allowed_path_rejects_escape(tmp_path):
    root = tmp_path / "data"
    outside = tmp_path / "outside.txt"
    root.mkdir(); outside.write_text("x")
    from app.path_safety import require_allowed_path, UnsafePathError

    with pytest.raises(UnsafePathError):
        require_allowed_path(outside, [root])


def test_require_allowed_path_rejects_symlink_escape(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "link"
    link.symlink_to(outside, target_is_directory=True)
    from app.path_safety import require_allowed_path, UnsafePathError

    with pytest.raises(UnsafePathError):
        require_allowed_path(link / "x.txt", [root])
