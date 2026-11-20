"""Regression evidence for the independent probe-cleanup review findings."""
from contextlib import ExitStack
import os
import signal
import stat

import pytest

from app.batch.media_organizer_custody import NamespaceCustodyUnavailable
from app.storage_optimization import capability
from tests.storage_probe_custody import scoped_probe_namespace


@pytest.mark.parametrize("operation", ["hardlink", "reflink"])
def test_live_probe_issuer_refuses_before_any_scratch_write(tmp_path, operation):
    source, destination = tmp_path / "keep", tmp_path / "replace"
    source.mkdir()
    destination.mkdir()
    before = (source.stat().st_ctime_ns, destination.stat().st_ctime_ns)
    result = getattr(capability, f"probe_{operation}_between")(
        source, destination, [tmp_path],
    )
    assert result.capability is capability.StorageOptimizationCapability.UNKNOWN
    assert "custody" in result.reason
    assert list(source.iterdir()) == list(destination.iterdir()) == []
    assert (source.stat().st_ctime_ns, destination.stat().st_ctime_ns) == before


def test_hardlink_collision_never_unlinks_foreign_destination(
    tmp_path, monkeypatch, scoped_probe_namespace,
):
    token = b"C" * 10
    monkeypatch.setattr(capability.os, "urandom", lambda _: token)
    foreign = tmp_path / f".__nfc_hardlink_probe_{token.hex()}.dst"
    foreign.write_bytes(b"preexisting foreign file")
    before = foreign.stat()
    result = capability.probe_hardlink_capability(tmp_path, [tmp_path])
    assert foreign.exists(), "failed link never acquired ownership of its destination"
    assert foreign.read_bytes() == b"preexisting foreign file"
    assert foreign.stat().st_ino == before.st_ino
    assert result.capability is capability.StorageOptimizationCapability.UNKNOWN
    assert set(tmp_path.iterdir()) == {foreign}


def test_hardlink_probe_reads_only_its_small_bounded_payload(
    tmp_path, monkeypatch, scoped_probe_namespace,
):
    real_probe, real_read = capability._probe_file, os.read
    read_count = [0]

    def enlarge(*args, **kwargs):
        fd = real_probe(*args, **kwargs)
        os.write(fd, b"x" * (256 * 1024))
        return fd

    def observe(fd, count):
        data = real_read(fd, count)
        read_count[0] += len(data)
        return data

    monkeypatch.setattr(capability, "_probe_file", enlarge)
    monkeypatch.setattr(capability.os, "read", observe)
    result = capability.probe_hardlink_capability(tmp_path, [tmp_path])
    assert result.capability is capability.StorageOptimizationCapability.UNKNOWN
    assert read_count[0] <= 64, "probe consumed an unbounded file through a fresh name"


@pytest.mark.parametrize("replacement", ["fifo", "regular"])
def test_hardlink_probe_rejects_replaced_read_name_without_read_or_cleanup(
    tmp_path, monkeypatch, scoped_probe_namespace, replacement,
):
    real_open, real_read = os.open, os.read
    foreign_inode = [None]
    foreign_reads = []
    injected = [False]
    replaced = []

    def replace_before_open(name, flags, *args, **kwargs):
        if str(name).endswith(".dst") and not flags & os.O_CREAT:
            path = tmp_path / str(name)
            path.rename(path.with_suffix(".detached"))
            if replacement == "fifo":
                os.mkfifo(path, 0o600)
            else:
                path.write_bytes(b"foreign payload must not be read")
            foreign_inode[0] = path.stat().st_ino
            replaced.append(path)
            injected[0] = True
        return real_open(name, flags, *args, **kwargs)

    def observe_read(fd, count):
        if os.fstat(fd).st_ino == foreign_inode[0]:
            foreign_reads.append(count)
        return real_read(fd, count)

    def timeout(*_):
        raise AssertionError("probe blocked opening a substituted FIFO")

    monkeypatch.setattr(capability.os, "open", replace_before_open)
    monkeypatch.setattr(capability.os, "read", observe_read)
    previous = signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, 1)
    try:
        result = capability.probe_hardlink_capability(tmp_path, [tmp_path])
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    assert injected[0]
    assert result.capability is capability.StorageOptimizationCapability.UNKNOWN
    assert foreign_reads == []
    assert replaced[0].stat().st_ino == foreign_inode[0]
    if replacement == "fifo":
        assert stat.S_ISFIFO(replaced[0].stat().st_mode)
    else:
        assert replaced[0].read_bytes() == b"foreign payload must not be read"


def test_revoked_probe_custody_retains_created_evidence_and_releases_proof(
    tmp_path, monkeypatch, scoped_probe_namespace,
):
    real_create = capability._probe_file

    def revoke(*args, **kwargs):
        fd = real_create(*args, **kwargs)
        scoped_probe_namespace["allowed"] = False
        return fd

    monkeypatch.setattr(capability, "_probe_file", revoke)
    with pytest.raises(NamespaceCustodyUnavailable, match="revoked"):
        capability.probe_hardlink_capability(tmp_path, [tmp_path])
    residues = list(tmp_path.iterdir())
    assert len(residues) == 1 and residues[0].suffix == ".src"
    assert residues[0].read_bytes() == b"nas-file-center-hardlink-probe"
    assert all(proof.closed for proof in scoped_probe_namespace["proofs"])


def test_probe_releases_scoped_resource_after_success(tmp_path, scoped_probe_namespace):
    result = capability.probe_hardlink_capability(tmp_path, [tmp_path])
    assert result.supported
    assert len(scoped_probe_namespace["proofs"]) == 1
    assert scoped_probe_namespace["proofs"][0].closed
    assert list(tmp_path.iterdir()) == []


def test_duplicate_parent_names_cannot_discard_a_pinned_inode(
    tmp_path, scoped_probe_namespace,
):
    parent = tmp_path / "selected"
    parent.mkdir()
    with ExitStack() as stack:
        old_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, old_fd)
        parent.rename(tmp_path / "detached")
        parent.mkdir()
        new_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, new_fd)
        assert os.fstat(old_fd).st_ino != os.fstat(new_fd).st_ino
        with pytest.raises(NamespaceCustodyUnavailable, match="identity"):
            capability._hold_probe_custody(stack, (
                (parent, os.fstat(old_fd)), (parent, os.fstat(new_fd)),
            ), None)
    assert scoped_probe_namespace["proofs"] == []
