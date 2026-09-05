from __future__ import annotations

import os
from pathlib import Path
import pytest

from app.path_safety import UnsafePathError
from app.quarantine.paths import (
    build_quarantine_target_path,
    build_restore_rename_path,
    get_containing_root_slot,
    is_reserved_quarantine_path,
    require_unreserved_path,
    safe_quarantine_hash,
)


def test_containing_root_longest_prefix_match(tmp_path: Path):
    """Most specific root selection (longest prefix match)."""
    root1 = tmp_path / "data"
    root2 = tmp_path / "data" / "media"
    root1.mkdir(parents=True)
    root2.mkdir(parents=True)

    allowed = [root1, root2]

    # File in /data/media/Movies/test.mp4 -> root2
    file_in_media = root2 / "Movies" / "test.mp4"
    slot, root = get_containing_root_slot(file_in_media, allowed)
    assert slot == 1
    assert root == root2.resolve(strict=False)

    # File in /data/docs/test.txt -> root1
    file_in_data = root1 / "docs" / "test.txt"
    slot, root = get_containing_root_slot(file_in_data, allowed)
    assert slot == 0
    assert root == root1.resolve(strict=False)


def test_containing_root_outside_allowed_roots(tmp_path: Path):
    """File outside allowed roots raises UnsafePathError."""
    root = tmp_path / "data"
    root.mkdir()
    outside_file = tmp_path / "etc" / "secret.txt"
    with pytest.raises(UnsafePathError):
        get_containing_root_slot(outside_file, [root])


def test_quarantine_target_path_layout_and_uniqueness(tmp_path: Path):
    """Target layout must follow <QUARANTINE_ROOT>/plan-<id>/root-<slot>/<parent>/<stem>.q-<entry_id><ext>."""
    data_root = tmp_path / "data"
    quarantine_root = data_root / ".nas-file-center-trash"
    source = data_root / "Movies" / "SciFi" / "matrix.mkv"

    target_1 = build_quarantine_target_path(
        source,
        allowed_roots=[data_root],
        quarantine_root=quarantine_root,
        plan_id="7",
        entry_id=42,
    )
    expected_rel = Path("plan-7") / "root-0" / "Movies" / "SciFi" / "matrix.q-42.mkv"
    assert target_1 == (quarantine_root / expected_rel).resolve(strict=False)

    # Different entry_id must yield distinct target
    target_2 = build_quarantine_target_path(
        source,
        allowed_roots=[data_root],
        quarantine_root=quarantine_root,
        plan_id="7",
        entry_id=43,
    )
    assert target_1 != target_2
    assert target_2.name == "matrix.q-43.mkv"


def test_quarantine_target_path_with_no_extension(tmp_path: Path):
    """Target layout handles extension-less files cleanly."""
    data_root = tmp_path / "data"
    quarantine_root = data_root / ".nas-file-center-trash"
    source = data_root / "Makefile"

    target = build_quarantine_target_path(
        source,
        allowed_roots=[data_root],
        quarantine_root=quarantine_root,
        plan_id="1",
        entry_id=99,
    )
    assert target.name == "Makefile.q-99"


def test_reserved_quarantine_path_detection(tmp_path: Path):
    """Accurately detects paths within QUARANTINE_ROOT without relying on fragile string containment."""
    data_root = tmp_path / "data"
    quarantine_root = data_root / ".nas-file-center-trash"
    
    in_trash = quarantine_root / "plan-1" / "file.txt"
    normal_file = data_root / "some.nas-file-center-trash-fake" / "file.txt"

    assert is_reserved_quarantine_path(in_trash, quarantine_root) is True
    assert is_reserved_quarantine_path(quarantine_root, quarantine_root) is True
    # Normal file with similar string in name must NOT be treated as reserved
    assert is_reserved_quarantine_path(normal_file, quarantine_root) is False

    with pytest.raises(UnsafePathError):
        require_unreserved_path(in_trash, quarantine_root)
    
    assert require_unreserved_path(normal_file, quarantine_root) == normal_file.resolve(strict=False)


def test_symlink_rejection_in_quarantine(tmp_path: Path):
    """Symlinks as source, quarantine_root, or target parent are strictly rejected."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    quarantine_root = data_root / ".trash"
    real_file = data_root / "real.txt"
    real_file.write_text("hello")

    link_file = data_root / "link.txt"
    try:
        os.symlink(real_file, link_file)
    except OSError:
        pytest.skip("Symlink not supported in environment")

    # Source symlink rejected
    with pytest.raises(ValueError, match="symlink"):
        build_quarantine_target_path(
            link_file,
            allowed_roots=[data_root],
            quarantine_root=quarantine_root,
            plan_id="1",
            entry_id=1,
            check_symlink=True,
        )


def test_restore_rename_path_generation(tmp_path: Path):
    """Restore rename generates <stem>.restored-<entry_id><suffix> and increments on collision."""
    original = tmp_path / "data" / "doc.pdf"
    
    # 1. No collision on destination
    r1 = build_restore_rename_path(original, entry_id=10, existing_check=lambda p: False)
    assert r1.name == "doc.restored-10.pdf"

    # 2. Collision on r1 -> r2 has -1
    def mock_exists(p: Path):
        return p.name == "doc.restored-10.pdf"

    r2 = build_restore_rename_path(original, entry_id=10, existing_check=mock_exists)
    assert r2.name == "doc.restored-10-1.pdf"


def test_streaming_hash_large_file(tmp_path: Path):
    """safe_quarantine_hash streams file content without memory blowout."""
    test_file = tmp_path / "large.bin"
    # Write 2MB in chunks
    chunk = b"X" * (1024 * 1024)
    with open(test_file, "wb") as f:
        f.write(chunk)
        f.write(chunk)

    h = safe_quarantine_hash(test_file)
    import hashlib
    expected = hashlib.sha256(chunk * 2).hexdigest()
    assert h == expected
