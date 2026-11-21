"""#403 synthetic password-channel tests: never use production media/secrets.

These verify strict per-file permissions and no password in task metadata.
They do NOT prove two real Docker namespaces share a mount; Compose and
a separate two-UID container acceptance must cover that physical boundary.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.archive_recovery import integration as archive
from app.archive_recovery.core import RecoveryError


TOKEN = "d" * 32
PASSWORD = "synthetic-passphrase-not-production"


@pytest.fixture
def private_ram_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "secret-channel"
    root.mkdir()
    root.chmod(0o2770)
    monkeypatch.setattr(archive, "SECRET_DIR", root)
    monkeypatch.setenv("NFC_SECRET_OWNER_UID", str(os.geteuid()))
    monkeypatch.setenv("NFC_SECRET_GROUP_GID", str(os.getegid()))
    # Filesystem fixture models the *contents* of a verified Docker tmpfs.
    monkeypatch.setattr(archive, "tmpfs_available", lambda: True)
    return root


def test_one_time_password_is_group_readable_and_removed_after_read(
    private_ram_scratch: Path,
) -> None:
    archive.store_one_time_password(TOKEN, PASSWORD)
    path = private_ram_scratch / TOKEN
    assert (path.stat().st_mode & 0o777) == 0o640
    assert path.stat().st_gid == os.getegid()
    assert path.stat().st_uid == os.geteuid()
    assert path.read_text(encoding="utf-8") == PASSWORD
    assert archive.read_one_time_password(TOKEN) == PASSWORD
    assert not path.exists()
    with pytest.raises((FileNotFoundError, RecoveryError)):
        archive.read_one_time_password(TOKEN)


@pytest.mark.parametrize("mode", [0o600, 0o660, 0o644, 0o777])
def test_invalid_secret_mode_fails_closed_without_eating_foreign_token(
    private_ram_scratch: Path, mode: int,
) -> None:
    path = private_ram_scratch / TOKEN
    path.write_text(PASSWORD, encoding="utf-8")
    path.chmod(mode)
    with pytest.raises(RecoveryError, match="PASSWORD_CHANNEL_INVALID"):
        archive.read_one_time_password(TOKEN)
    assert path.read_text(encoding="utf-8") == PASSWORD


def test_symlink_secret_is_never_read_or_removed(
    private_ram_scratch: Path, tmp_path: Path,
) -> None:
    original = tmp_path / "unrelated.txt"
    original.write_text("foreign", encoding="utf-8")
    (private_ram_scratch / TOKEN).symlink_to(original)
    with pytest.raises((OSError, RecoveryError)):
        archive.read_one_time_password(TOKEN)
    assert original.read_text(encoding="utf-8") == "foreign"
    assert (private_ram_scratch / TOKEN).is_symlink()


def test_bad_secret_group_fails_closed_without_chown(
    private_ram_scratch: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive.store_one_time_password(TOKEN, PASSWORD)
    path = private_ram_scratch / TOKEN
    original_group = path.stat().st_gid
    monkeypatch.setenv("NFC_SECRET_GROUP_GID", str(original_group + 1))
    with pytest.raises(RecoveryError, match="PASSWORD_CHANNEL_"):
        archive.read_one_time_password(TOKEN)
    assert path.stat().st_gid == original_group
    assert path.read_text(encoding="utf-8") == PASSWORD


def test_secret_channel_fails_closed_if_mount_is_ordinary_disk_directory(
    private_ram_scratch: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.undo()
    monkeypatch.setattr(archive, "SECRET_DIR", private_ram_scratch)
    monkeypatch.setenv("NFC_SECRET_OWNER_UID", str(os.geteuid()))
    monkeypatch.setenv("NFC_SECRET_GROUP_GID", str(os.getegid()))
    # Even valid-looking ownership/mode is NOT proof that disk is RAM-backed.
    assert archive.tmpfs_available() is False


def test_secret_creation_rejects_existing_token_without_overwrite(
    private_ram_scratch: Path,
) -> None:
    path = private_ram_scratch / TOKEN
    path.write_text("foreign", encoding="utf-8")
    with pytest.raises((FileExistsError, RecoveryError)):
        archive.store_one_time_password(TOKEN, PASSWORD)
    assert path.read_text(encoding="utf-8") == "foreign"


def test_secret_creation_rejects_invalid_token_without_writing(
    private_ram_scratch: Path,
) -> None:
    with pytest.raises(RecoveryError, match="PASSWORD_CHANNEL_INVALID"):
        archive.store_one_time_password("../secret", PASSWORD)
    assert list(private_ram_scratch.iterdir()) == []
