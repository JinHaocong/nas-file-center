"""SEC-11 open races under explicit custody of disposable tmp_path fixtures.

The fixture proof is synthetic. It never claims NAS or production authority.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import stat

import pytest

from app.batch.media_organizer_custody import assert_exclusive_custody
from app.batch import media_organizer_publish as publishing
from app.batch import media_organizer_stage as staging
from app.batch.media_organizer_manifest import (
    build_frozen_preview_manifest, save_frozen_preview_manifest,
)
from app.batch.media_organizer_planner import preview_semantic_unit


class ScopedFixtureCustody:
    def __init__(self, root):
        self.root = root

    def assert_exclusive(self, parent):
        if not Path(parent).is_relative_to(self.root):
            raise ValueError("outside synthetic source-open fixture")


@contextmanager
def _frozen_fixture(tmp_path):
    unit = tmp_path / "media" / "unit"
    unit.mkdir(parents=True)
    (unit / "photo.jpg").write_bytes(b"ORIGINAL")
    preview = preview_semantic_unit(unit, allowed_roots=[unit.parent])
    manifest = build_frozen_preview_manifest(
        unit, preview_record=preview, allowed_roots=[unit.parent], job_id=401,
    )
    manifest.update(cleanup_policy="deferred", execution_mode="strict")
    frozen = tmp_path / "private" / "manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    parents = (unit, unit / manifest["stage_directory"])
    custody = ScopedFixtureCustody(tmp_path)

    def fence():
        assert_exclusive_custody(custody, parents)

    options = dict(frozen_manifest_path=frozen,
                   allowed_roots=[unit.parent], lease_fence=fence)
    yield manifest, frozen, options, custody


class _BlockingSourceOpen(RuntimeError):
    pass


@pytest.mark.parametrize("phase", ["stage", "publish"])
def test_fifo_swap_at_source_open_fails_without_waiting_for_a_writer(
    tmp_path, monkeypatch, phase,
):
    """A source-type swap must fail promptly without moving/removing any inode."""
    original_open = os.open
    detached = tmp_path / "verified-source-detached"
    swapped = []

    def alarm(_signum, _frame):
        raise _BlockingSourceOpen("source FIFO open blocked until the audit alarm")

    previous_handler = signal.signal(signal.SIGALRM, alarm)
    try:
        with _frozen_fixture(tmp_path) as (manifest, frozen, options, custody):
            row = manifest["moves"][0]
            source = Path(row["source"] if phase == "stage" else row["target"])
            frozen_before = frozen.read_bytes()
            if phase == "publish":
                staging.stage_frozen_sources(manifest, **options)

            def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
                if (dir_fd is not None and str(path) == source.name
                        and not flags & (os.O_DIRECTORY | os.O_CREAT) and not swapped):
                    source.rename(detached)
                    os.mkfifo(source, mode=0o600)
                    swapped.append(True)
                    signal.setitimer(signal.ITIMER_REAL, 0.5)
                    try:
                        return original_open(path, flags, mode, dir_fd=dir_fd)
                    finally:
                        signal.setitimer(signal.ITIMER_REAL, 0)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            monkeypatch.setattr(os, "open", swap_before_open)
            try:
                if phase == "stage":
                    staging.stage_frozen_sources(manifest, **options)
                else:
                    publishing.publish_frozen_stage(
                        manifest, **options, namespace_custody=custody, defer_directory_cleanup=True,
                    )
            except (staging.StagingConflict, publishing.PublishingConflict, _BlockingSourceOpen) as exc:
                error = exc
            else:
                error = None

            assert swapped, "the final source-open boundary was not exercised"
            assert stat.S_ISFIFO(source.lstat().st_mode), "foreign replacement was removed"
            assert detached.read_bytes() == b"ORIGINAL"
            assert detached.stat().st_ino == row["identity"][1]
            assert frozen.read_bytes() == frozen_before
            assert not Path(row["final"]).exists()
            if phase == "stage":
                assert not Path(row["target"]).exists()
            else:
                assert Path(row["source"]).read_bytes() == b"ORIGINAL"
            assert isinstance(error, (staging.StagingConflict, publishing.PublishingConflict)), repr(error)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def test_resume_fifo_witness_fails_without_waiting_for_a_writer(tmp_path):
    """Recovery must reject an untrusted witness before any blocking read."""
    with _frozen_fixture(tmp_path) as (manifest, frozen, options, _):
        staging.stage_frozen_sources(manifest, **options)
        row = manifest["moves"][0]
        stage = Path(row["target"]).parent
        marker = stage / ".nfc-stage-authority"
        original_witness = tmp_path / "detached-original-witness"
        marker.rename(original_witness)
        os.mkfifo(marker, mode=0o600)
        frozen_before = frozen.read_bytes()

        def alarm(_signum, _frame):
            raise _BlockingSourceOpen("stage witness FIFO open blocked until the audit alarm")

        previous_handler = signal.signal(signal.SIGALRM, alarm)
        try:
            signal.setitimer(signal.ITIMER_REAL, 0.5)
            try:
                staging.stage_frozen_sources(manifest, **options, resume=True)
            except (staging.StagingConflict, _BlockingSourceOpen) as exc:
                error = exc
            else:
                error = None
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
        finally:
            signal.signal(signal.SIGALRM, previous_handler)

        assert stat.S_ISFIFO(marker.lstat().st_mode)
        assert original_witness.read_bytes()
        assert Path(row["source"]).read_bytes() == b"ORIGINAL"
        assert Path(row["target"]).read_bytes() == b"ORIGINAL"
        assert not Path(row["final"]).exists()
        assert frozen.read_bytes() == frozen_before
        assert isinstance(error, staging.StagingConflict), repr(error)
