"""#400 actual disposable cleanup and canonical zero-rescan contract.

All file mutations in this suite are on synthetic tmp_path media. These tests
do NOT grant production namespace exclusivity; live API/Worker remains blocked.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch.media_organizer_deferred_cleanup import record_deferred_cleanup_evidence
from app.batch.media_organizer_cleanup_plan import save_cleanup_plan, cleanup_plan_path
from app.batch.media_organizer_finalize import (
    CleanupExecutionBlocked, cleanup_confirmation, finish_deferred_cleanup,
)
from tests.test_media_organizer_deferred_cleanup import prepare, execute_deferred
from tests.test_media_organizer_pending_group_race import _grouped


class ExclusiveSyntheticCustody:
    """Only a test fixture's private tmp tree: NOT a real-NAS custody proof."""
    def __init__(self, root):
        self.root = root

    def assert_exclusive(self, parent):
        assert Path(parent).is_relative_to(self.root)


def _flat(tmp_path, *, wrapper=True):
    unit, manifest, frozen = prepare(tmp_path, old_wrapper=wrapper)
    execute_deferred(tmp_path, manifest, frozen)
    record_deferred_cleanup_evidence(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    plan = save_cleanup_plan(cleanup_plan_path(frozen), manifest)
    return unit, manifest, frozen, plan


def _finish(tmp_path, manifest, frozen, plan, **kwargs):
    return finish_deferred_cleanup(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        custody=ExclusiveSyntheticCustody(tmp_path),
        confirmation=cleanup_confirmation(manifest["job_id"], manifest["unit"],
                                          plan["plan_sha256"]),
        **kwargs,
    )


def _bytes(plan):
    return {str(row["published_path"]): hashlib.sha256(
        Path(row["published_path"]).read_bytes()).hexdigest()
        for row in plan["original_links"]}


def test_default_cleanup_refuses_before_mutating_any_file(tmp_path):
    unit, manifest, frozen, plan = _flat(tmp_path)
    before = {row["path"]: Path(row["path"]).read_bytes()
              for row in plan["original_links"]}
    with pytest.raises(CleanupExecutionBlocked, match="custody|exclusive"):
        finish_deferred_cleanup(
            manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
            confirmation=cleanup_confirmation(
                manifest["job_id"], manifest["unit"], plan["plan_sha256"],
            ),
        )
    assert all(Path(path).read_bytes() == value for path, value in before.items())
    assert not (unit / "001.jpg").is_symlink()


def test_flat_p1_original_and_stage_cleanup_reaches_second_scan_zero(tmp_path):
    unit, manifest, frozen, plan = _flat(tmp_path)
    expected = _bytes(plan)
    result = _finish(tmp_path, manifest, frozen, plan)
    assert result["finalized"] is True
    assert result["already_organized"] is True
    assert result["needed_moves"] == 0
    assert result["renamed_count"] == 0
    assert result["originals_removed"] == len(manifest["moves"]) == 2
    assert result["old_wrappers_removed"] == 1
    assert not (unit / "P1").exists()
    assert not (unit / manifest["stage_directory"]).exists()
    assert all(not Path(row["path"]).exists() for row in plan["original_links"])
    assert expected == _bytes(plan)
    second = preview_semantic_unit(unit, allowed_roots=[tmp_path])
    assert second["status"] == "already_organized"
    assert second["needed_moves"] == 0
    assert second["renamed_count"] == 0


def test_mixed_PV_group_direct_publication_can_finish_canonical_rescan(
    tmp_path, monkeypatch,
):
    from app.batch import media_organizer_deferred_cleanup as deferred
    from app.batch.media_organizer_stage import stage_frozen_sources
    from app.batch.media_organizer_publish import publish_frozen_stage

    unit, manifest, frozen = _grouped(tmp_path)
    proof = ExclusiveSyntheticCustody(tmp_path)
    stage_frozen_sources(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None,
    )
    publish_frozen_stage(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None, defer_directory_cleanup=True,
        namespace_custody=proof,
    )
    record_deferred_cleanup_evidence(
        manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
        lease_fence=lambda: None, namespace_custody=proof,
    )
    plan = save_cleanup_plan(cleanup_plan_path(frozen), manifest)
    expected = _bytes(plan)
    result = _finish(tmp_path, manifest, frozen, plan)
    assert result["finalized"] is True
    assert result["groups_verified"] == 2
    assert expected == _bytes(plan)
    assert all(not (unit / grp["name"] / ".nfc-publish-owner").exists()
               for grp in manifest["groups"])
    assert all(not (unit / grp["name"] / ".nfc-publish-complete").exists()
               for grp in manifest["groups"])
    assert not (unit / manifest["stage_directory"]).exists()
    assert preview_semantic_unit(unit, allowed_roots=[tmp_path])["status"] == "already_organized"


def test_wrong_separate_cleanup_confirmation_must_not_unlink(tmp_path):
    unit, manifest, frozen, plan = _flat(tmp_path)
    before = _bytes(plan)
    with pytest.raises(CleanupExecutionBlocked, match="confirm|approval"):
        finish_deferred_cleanup(
            manifest, frozen_manifest_path=frozen, allowed_roots=[tmp_path],
            custody=ExclusiveSyntheticCustody(tmp_path),
            confirmation="EXECUTE_MEDIA_ORGANIZER_WRONG_TOKEN",
        )
    assert before == _bytes(plan)
    assert all(Path(row["path"]).exists() for row in plan["original_links"])


def test_unexpected_source_swap_is_rejected_without_deleting_foreign(tmp_path):
    unit, manifest, frozen, plan = _flat(tmp_path)
    source = Path(manifest["moves"][0]["source"])
    safe_detached = source.with_name("owned-detached-for-audit.jpg")
    source.rename(safe_detached)
    source.write_bytes(b"foreign-no-delete")
    with pytest.raises(CleanupExecutionBlocked, match="source|identity|frozen|changed"):
        _finish(tmp_path, manifest, frozen, plan)
    assert source.read_bytes() == b"foreign-no-delete"
    assert safe_detached.is_file()
    assert all(Path(row["published_path"]).exists() for row in plan["original_links"])


def test_foreign_wrapper_child_blocks_all_cleanup(tmp_path):
    unit, manifest, frozen, plan = _flat(tmp_path)
    foreign = unit / "P1" / "foreign.txt"
    foreign.write_bytes(b"preserve-this")
    with pytest.raises(CleanupExecutionBlocked):
        _finish(tmp_path, manifest, frozen, plan)
    assert foreign.read_bytes() == b"preserve-this"
    assert all(Path(row["path"]).exists() for row in plan["original_links"])


def test_interrupted_cleanup_can_reconcile_durable_pending_step(tmp_path):
    unit, manifest, frozen, plan = _flat(tmp_path)
    expected = _bytes(plan)
    injected = []

    def after_mutation(index):
        if not injected and index == 0:
            injected.append(True)
            raise RuntimeError("synthetic crash after first source unlink")

    with pytest.raises(RuntimeError, match="synthetic crash"):
        _finish(tmp_path, manifest, frozen, plan, after_mutation=after_mutation)
    assert injected
    assert not Path(plan["original_links"][0]["path"]).exists()
    assert Path(plan["original_links"][1]["path"]).exists()
    assert expected == _bytes(plan)
    outcome = _finish(tmp_path, manifest, frozen, plan)
    assert outcome["finalized"] is True
    assert outcome["needed_moves"] == 0
    assert expected == _bytes(plan)
    assert preview_semantic_unit(unit, allowed_roots=[tmp_path])["status"] == "already_organized"

def test_cleanup_rechecks_custody_after_last_source_check_before_unlink(
    tmp_path, monkeypatch,
):
    """A source-name swap after the inode check must not reach unlink."""
    import os
    from app.batch import media_organizer_finalize as finalizer

    unit, manifest, frozen, plan = _flat(tmp_path)
    op = next(item for item in finalizer._operations(manifest, plan)
              if item["kind"] == "original")
    source = Path(op["path"])
    detached = source.with_name("owned-source-detached-for-audit" + source.suffix)
    original_bytes = source.read_bytes()
    final = Path(op["published"])
    staged = Path(op["stage_path"]) if "stage_path" in op else None

    class RevocableCustody:
        allowed = True

        def assert_exclusive(self, parent):
            if not self.allowed:
                raise CleanupExecutionBlocked("custody revoked at mutation boundary")

    proof = RevocableCustody()
    original_entry = finalizer._entry
    parent_stat = source.parent.stat()
    source_checks = 0

    def swap_after_final_source_check(parent_fd, name):
        nonlocal source_checks
        info = original_entry(parent_fd, name)
        opened_parent = os.fstat(parent_fd)
        if ((opened_parent.st_dev, opened_parent.st_ino) ==
                (parent_stat.st_dev, parent_stat.st_ino) and name == source.name):
            source_checks += 1
            if source_checks == 2:
                source.rename(detached)
                source.write_bytes(b"foreign-source-must-survive")
                proof.allowed = False
        return info

    monkeypatch.setattr(finalizer, "_entry", swap_after_final_source_check)
    with pytest.raises(CleanupExecutionBlocked, match="custody revoked"):
        finalizer._mutate_one(
            op, previously_begun=False, custody=proof, witness=b"unused",
            manifest=manifest, receipts={},
        )

    assert source_checks == 2
    assert detached.read_bytes() == original_bytes
    assert source.read_bytes() == b"foreign-source-must-survive"
    assert final.is_file() and final.read_bytes() == original_bytes
    assert staged is None or staged.is_file()


def test_cleanup_rechecks_custody_after_last_wrapper_check_before_rmdir(
    tmp_path, monkeypatch,
):
    """An empty foreign replacement must not be removed after a stale check."""
    import os
    from app.batch import media_organizer_finalize as finalizer

    unit, manifest, frozen, plan = _flat(tmp_path, wrapper=True)
    op = next(item for item in finalizer._operations(manifest, plan)
              if item["kind"] == "wrapper")
    wrapper = Path(op["path"])
    source = next(Path(row["source"]) for row in manifest["moves"]
                  if Path(row["source"]).parent == wrapper)
    original_bytes = source.read_bytes()
    final = next(Path(row["final"]) for row in manifest["moves"]
                 if Path(row["source"]) == source)
    staged = next(Path(row["target"]) for row in manifest["moves"]
                  if Path(row["source"]) == source)
    # Simulate the already-completed child-file operation. The original inode
    # remains safely available through its final and staged hardlinks.
    source.unlink()
    detached = wrapper.with_name("owned-wrapper-detached-for-audit")

    class RevocableCustody:
        allowed = True

        def assert_exclusive(self, parent):
            if not self.allowed:
                raise CleanupExecutionBlocked("custody revoked at mutation boundary")

    proof = RevocableCustody()
    original_entry = finalizer._entry
    parent_stat = wrapper.parent.stat()
    wrapper_checks = 0

    def swap_after_final_wrapper_check(parent_fd, name):
        nonlocal wrapper_checks
        info = original_entry(parent_fd, name)
        opened_parent = os.fstat(parent_fd)
        if ((opened_parent.st_dev, opened_parent.st_ino) ==
                (parent_stat.st_dev, parent_stat.st_ino) and name == wrapper.name):
            wrapper_checks += 1
            if wrapper_checks == 2:
                wrapper.rename(detached)
                wrapper.mkdir()
                proof.allowed = False
        return info

    monkeypatch.setattr(finalizer, "_entry", swap_after_final_wrapper_check)
    with pytest.raises(CleanupExecutionBlocked, match="custody revoked"):
        finalizer._mutate_one(
            op, previously_begun=False, custody=proof, witness=b"unused",
            manifest=manifest, receipts={},
        )

    assert wrapper_checks == 2
    assert detached.is_dir()
    assert wrapper.is_dir()
    assert list(wrapper.iterdir()) == []
    assert final.read_bytes() == staged.read_bytes() == original_bytes
