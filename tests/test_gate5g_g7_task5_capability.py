import os
import stat
from pathlib import Path
import pytest
from app.quarantine.capability import MutationCapability, resolve_mutation_capability


def test_probe_runs_on_target_directory_not_parent(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_bytes(b"HELLO")
    target_dir = tmp_path / "target_dir"
    target_dir.mkdir()
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir()
    allowed_roots = [tmp_path]

    probed_paths = []
    import app.quarantine.capability as cap_mod
    real_safe_open = cap_mod.safe_open_parent_fd

    def spy_safe_open(p, roots):
        probed_paths.append(Path(p))
        return real_safe_open(p, roots)

    monkeypatch.setattr(cap_mod, "safe_open_parent_fd", spy_safe_open)
    monkeypatch.setattr(cap_mod, "_probe_rename_noreplace_supported", lambda dir_fd: True)

    res = resolve_mutation_capability(source, target_dir, quarantine_root, allowed_roots)
    assert res == MutationCapability.NATIVE_ATOMIC_NOREPLACE
    assert len(probed_paths) == 1
    assert probed_paths[0].parent == target_dir


def test_resolve_device_mismatch_fails_closed(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_bytes(b"HELLO")
    target_dir = tmp_path / "target_dir"
    target_dir.mkdir()
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir()
    allowed_roots = [tmp_path]

    import app.quarantine.capability as cap_mod
    monkeypatch.setattr(cap_mod, "_probe_rename_noreplace_supported", lambda dir_fd: False)

    orig_stat = os.stat
    def mock_stat(path, *args, **kwargs):
        st = orig_stat(path, *args, **kwargs)
        if Path(path) == quarantine_root:
            class FakeStat:
                st_mode = st.st_mode
                st_dev = st.st_dev + 9999
                st_ino = st.st_ino
                st_size = st.st_size
            return FakeStat()
        return st

    monkeypatch.setattr(os, "stat", mock_stat)

    res = resolve_mutation_capability(source, target_dir, quarantine_root, allowed_roots)
    assert res == MutationCapability.UNSUPPORTED


def test_resolve_native_regular_file(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_bytes(b"HELLO")
    target_dir = tmp_path / "target_dir"
    target_dir.mkdir()
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir()
    allowed_roots = [tmp_path]

    import app.quarantine.capability as cap_mod
    monkeypatch.setattr(cap_mod, "_probe_rename_noreplace_supported", lambda dir_fd: True)

    res = resolve_mutation_capability(source, target_dir, quarantine_root, allowed_roots)
    assert res == MutationCapability.NATIVE_ATOMIC_NOREPLACE


def test_resolve_compat_regular_file(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_bytes(b"HELLO")
    target_dir = tmp_path / "target_dir"
    target_dir.mkdir()
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir()
    allowed_roots = [tmp_path]

    import app.quarantine.capability as cap_mod
    monkeypatch.setattr(cap_mod, "_probe_rename_noreplace_supported", lambda dir_fd: False)

    res = resolve_mutation_capability(source, target_dir, quarantine_root, allowed_roots)
    assert res == MutationCapability.COMPAT_TRANSACTIONAL


def test_resolve_compat_non_regular_file(tmp_path, monkeypatch):
    source = tmp_path / "source_symlink"
    real_target = tmp_path / "real.txt"
    real_target.write_bytes(b"REAL")
    os.symlink(real_target, source)

    target_dir = tmp_path / "target_dir"
    target_dir.mkdir()
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir()
    allowed_roots = [tmp_path]

    import app.quarantine.capability as cap_mod
    monkeypatch.setattr(cap_mod, "_probe_rename_noreplace_supported", lambda dir_fd: False)

    res = resolve_mutation_capability(source, target_dir, quarantine_root, allowed_roots)
    assert res == MutationCapability.UNSUPPORTED
