"""Exercise operator-confirmed maintenance sessions and the real cooperative lock.

These tests do not inject strict namespace custody. They exercise the weaker
maintenance-window contract on disposable tmp_path media.
"""
import os
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.batch import media_organizer_authority as authority
from app.batch.media_organizer_custody import (
    NamespaceCustodyUnavailable, assert_exclusive_custody,
)
from app.batch.media_organizer_cleanup_plan import cleanup_plan_path, save_cleanup_plan
from app.batch.media_organizer_deferred_cleanup import (
    record_deferred_cleanup_evidence, validate_deferred_publication,
)
from app.batch.media_organizer_finalize import (
    CleanupExecutionBlocked, cleanup_confirmation, finish_deferred_cleanup,
)
from app.batch.media_organizer_manifest import build_frozen_preview_manifest, save_frozen_preview_manifest
from app.batch.media_organizer_planner import preview_semantic_unit
from app.batch.media_organizer_publish import PublishingConflict, publish_frozen_stage
from app.batch.media_organizer_stage import stage_frozen_sources


def acquire_operation_authority(settings, unit, parents, *, manifest=None):
    return authority.acquire_operation_authority(
        settings, unit, parents, manifest=manifest,
        maintenance_window_confirmed=True,
    )



@pytest.fixture
def site(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("requires real non-root ownership for private stage and journal")
    config = tmp_path / "config"
    config.mkdir(mode=0o700)
    unit = tmp_path / "media" / "unit"
    unit.mkdir(parents=True)
    settings = SimpleNamespace(
        config_dir=config, reports_dir=config / "reports", allowed_roots=[unit.parent],
        quarantine_root=unit.parent / "trash", media_organizer_execution_mode="maintenance_window",
        allow_mutation=True, allow_delete=True, media_organizer_execution_enabled=True,
        media_organizer_namespace_quiescence_ack=True,
    )
    return settings, unit


def grouped(site):
    settings, unit = site
    old = unit / "P1"
    old.mkdir()
    (old / "image.jpg").write_bytes(b"photo")
    (unit / "video.mp4").write_bytes(b"video")
    preview = preview_semantic_unit(unit, allowed_roots=settings.allowed_roots)
    manifest = build_frozen_preview_manifest(unit, preview_record=preview,
                                              allowed_roots=settings.allowed_roots, job_id=9)
    manifest.update(cleanup_policy="deferred", execution_mode=authority.execution_mode(settings))
    frozen = settings.reports_dir / "media_organizer-executions/9/manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    parents = {unit, old, unit / manifest["stage_directory"],
               *(Path(group["destination"]) for group in manifest["groups"])}
    return manifest, frozen, parents


def test_mode_or_legacy_ack_alone_cannot_issue_authority(site):
    settings, unit = site
    del settings.media_organizer_execution_mode
    assert authority.execution_mode(settings) == "strict"
    with pytest.raises(NamespaceCustodyUnavailable):
        authority.check_api_eligibility(settings, unit)
    settings.media_organizer_execution_mode = "unknown"
    with pytest.raises(ValueError):
        authority.check_api_eligibility(settings, unit)
    settings.media_organizer_execution_mode = "maintenance_window"
    settings.allow_delete = False
    with pytest.raises((ValueError, PermissionError)):
        with acquire_operation_authority(settings, unit, (unit,)):
            pytest.fail("disabled deletion granted an operation session")


def test_api_checks_only_the_canonical_unit(site):
    settings, unit = site
    protected_stage = unit / "private-stage"
    protected_stage.symlink_to("/missing")
    authority.check_api_eligibility(settings, unit, (unit, protected_stage))
    assert list(settings.config_dir.iterdir()) == []
    alias = unit.parent / "alias"
    alias.symlink_to(unit)
    for bad in (alias, unit / ".." / "unit", unit.parent.parent):
        with pytest.raises((OSError, ValueError)):
            authority.check_api_eligibility(settings, bad)


def test_live_scope_fencing_and_resource_release(site):
    settings, unit = site
    old = unit / "old"
    old.mkdir()
    before = set(os.listdir("/proc/self/fd"))
    with pytest.raises(RuntimeError, match="interruption"):
        with acquire_operation_authority(settings, unit, (unit, old)) as session:
            for value in (session, authority.fence_operation_authority(session, lambda: None)):
                with pytest.raises(NamespaceCustodyUnavailable):
                    assert_exclusive_custody(value, (unit,))
            calls = []
            fenced = authority.fence_operation_authority(session, lambda: calls.append(1))
            authority.assert_operation_authorized(fenced, (unit,))
            authority.assert_operation_authorized(fenced, (old,))
            assert calls == [1, 1]
            for outside in (unit.parent, unit / "unselected"):
                with pytest.raises((OSError, ValueError)):
                    authority.assert_operation_authorized(session, (outside,))
            old.rename(unit / "moved")
            old.mkdir()
            with pytest.raises((OSError, ValueError)):
                authority.assert_operation_authorized(session, (old,))
            raise RuntimeError("interruption")
    with pytest.raises((OSError, ValueError)):
        authority.assert_operation_authorized(session, (unit,))
    assert set(os.listdir("/proc/self/fd")) == before
    with acquire_operation_authority(settings, unit, (unit, old)) as new:
        authority.assert_operation_authorized(new, (old,))


def test_nonroot_and_nofollow_required(site, monkeypatch):
    settings, unit = site
    alias = unit / "alias"
    alias.symlink_to(unit)
    for bad in (alias, unit / "missing", unit / ".." / "unit"):
        with pytest.raises((OSError, ValueError)):
            with acquire_operation_authority(settings, unit, (unit, bad)):
                pytest.fail("unsafe parent accepted")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with pytest.raises(PermissionError):
        with acquire_operation_authority(settings, unit, (unit,)):
            pytest.fail("root Worker accepted")


def test_maintenance_worker_refuses_real_readonly_mount(site):
    """Observe real mount metadata without issuing custody for any host path."""
    for mount in (Path("/sys"), Path("/opt"), Path("/etc")):
        if mount.is_dir() and os.statvfs(mount).f_flag & os.ST_RDONLY:
            # No session is constructed or granted. The real parent validator
            # must refuse this mount before retaining any directory binding.
            unissued = SimpleNamespace(
                _unit=mount, _expected={}, _retired=set(), _bindings={},
            )
            with pytest.raises(authority.MaintenanceWindowUnavailable, match="writable"):
                authority.MaintenanceWindowSession._check_parent(unissued, mount)
            assert unissued._bindings == {}
            return
    pytest.skip("no read-only directory mount at /sys, /opt or /etc")


def publish(authority, settings, unit, manifest, frozen, parents):
    with acquire_operation_authority(settings, unit, parents, manifest=manifest) as session:
        def fence():
            authority.assert_operation_authorized(session, parents)
        validate_deferred_publication(manifest, namespace_custody=session)
        args = dict(frozen_manifest_path=frozen, allowed_roots=settings.allowed_roots, lease_fence=fence)
        stage_frozen_sources(manifest, **args)
        publish_frozen_stage(manifest, **args, namespace_custody=session, defer_directory_cleanup=True)
        record_deferred_cleanup_evidence(manifest, **args, namespace_custody=session)
        return save_cleanup_plan(cleanup_plan_path(frozen), manifest)


def test_maintenance_group_accepts_shared_writable_unit_and_untrusted_ancestor(site):
    """A real session permits ordinary mixed-owner NAS layouts in maintenance.

    The Worker must still have actual write access, valid frozen evidence,
    the cooperative lock and an active checked session. Strict stays private.
    """
    import stat
    settings, unit = site
    ancestor = unit.parent
    original_mode = stat.S_IMODE(ancestor.stat().st_mode)
    try:
        ancestor.chmod(0o777)
        unit.chmod(0o770)
        manifest, frozen, parents = grouped(site)
        plan = publish(authority, settings, unit, manifest, frozen, parents)
        assert plan["plan_sha256"]
        assert (unit / "P1" / "image.jpg").read_bytes() == b"photo"
        assert (unit / "video.mp4").read_bytes() == b"video"
        assert any(Path(row["final"]).exists() for row in manifest["moves"])
    finally:
        ancestor.chmod(original_mode)


def test_maintenance_group_cannot_claim_weak_policy_without_live_session(site):
    settings, unit = site
    manifest, frozen, parents = grouped(site)
    from app.batch import media_organizer_publish as publishing
    fd = os.open(unit, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with pytest.raises(PublishingConflict, match="live maintenance session"):
            publishing._verify_group_parent_posix_permissions(
                fd, manifest, namespace_custody=None,
            )
    finally:
        os.close(fd)


def test_maintenance_group_still_rejects_unwritable_bound_unit(site):
    settings, unit = site
    manifest, frozen, parents = grouped(site)
    unit.chmod(0o500)
    try:
        with pytest.raises(authority.MaintenanceWindowUnavailable, match="writable"):
            with acquire_operation_authority(
                settings, unit, parents, manifest=manifest,
            ):
                pytest.fail("non-writable selected unit gained authority")
    finally:
        unit.chmod(0o700)


def test_only_planned_future_parents_and_no_overwrite(site):
    settings, unit = site
    manifest, frozen, parents = grouped(site)
    with pytest.raises((ValueError, OSError)):
        with acquire_operation_authority(settings, unit, parents | {unit / "P [foreign]"},
                                                   manifest=manifest):
            pytest.fail("unplanned missing parent accepted")
    with acquire_operation_authority(settings, unit, parents, manifest=manifest) as session:
        fence = lambda: authority.assert_operation_authorized(session, parents)
        validate_deferred_publication(manifest, namespace_custody=session)
        stage_frozen_sources(manifest, frozen_manifest_path=frozen, allowed_roots=settings.allowed_roots,
                             lease_fence=fence)
        occupied = Path(manifest["groups"][0]["destination"])
        occupied.mkdir()
        intruder = occupied / "foreign"
        intruder.write_bytes(b"keep")
        with pytest.raises(PublishingConflict):
            publish_frozen_stage(manifest, frozen_manifest_path=frozen, allowed_roots=settings.allowed_roots,
                                 lease_fence=fence, namespace_custody=session, defer_directory_cleanup=True)
        assert intruder.read_bytes() == b"keep"


def test_only_journal_begun_retirement_allows_missing_parents(site):
    settings, unit = site
    manifest, frozen, parents = grouped(site)
    plan = publish(authority, settings, unit, manifest, frozen, parents)
    for bound in (unit / manifest["stage_directory"], Path(manifest["groups"][0]["destination"])):
        detached = unit / "detached"
        bound.rename(detached)
        bound.mkdir()
        try:
            with pytest.raises((OSError, ValueError)):
                with acquire_operation_authority(settings, unit, parents, manifest=manifest):
                    pytest.fail("existing cleanup-plan directory inode was replaced")
        finally:
            bound.rmdir()
            detached.rename(bound)
    old = unit / "P1"
    old.rename(unit / "detached")
    with pytest.raises((OSError, ValueError)):
        with acquire_operation_authority(settings, unit, parents, manifest=manifest):
            pytest.fail("absent old source directory accepted without its private journal")
    (unit / "detached").rename(old)
    options = dict(frozen_manifest_path=frozen, allowed_roots=settings.allowed_roots,
                   confirmation=cleanup_confirmation(9, str(unit), plan["plan_sha256"]))
    unknown = old / "unknown"
    unknown.write_bytes(b"preserve")
    with acquire_operation_authority(settings, unit, parents, manifest=manifest) as session:
        with pytest.raises(CleanupExecutionBlocked):
            finish_deferred_cleanup(manifest, custody=session, **options)
    assert unknown.read_bytes() == b"preserve"
    unknown.unlink()

    def crash_after_wrapper_removal(_):
        if not old.exists():
            raise RuntimeError("power loss after rmdir")

    with pytest.raises(RuntimeError, match="power loss"):
        with acquire_operation_authority(settings, unit, parents, manifest=manifest) as session:
            finish_deferred_cleanup(manifest, custody=session, after_mutation=crash_after_wrapper_removal,
                                    **options)
    assert not old.exists()
    with acquire_operation_authority(settings, unit, parents, manifest=manifest) as resumed:
        result = finish_deferred_cleanup(manifest, custody=resumed, **options)
    assert result["assurance_level"] == "maintenance_window"
    assert result["namespace_exclusive_custody_proven"] is False
    assert result["needed_moves"] == result["renamed_count"] == 0
    with acquire_operation_authority(settings, unit, parents, manifest=manifest) as completed:
        authority.assert_operation_authorized(completed, parents)
        old.mkdir()
        with pytest.raises((ValueError, OSError)):
            authority.assert_operation_authorized(completed, (old,))


def test_maintenance_session_is_bound_to_the_frozen_evidence(site):
    settings, unit = site
    manifest, _, parents = grouped(site)
    with acquire_operation_authority(settings, unit, parents, manifest=manifest) as session:
        changed = {**manifest, "input_fingerprint": "a different preview snapshot"}
        with pytest.raises(ValueError):
            validate_deferred_publication(changed, namespace_custody=session)


def test_child_cannot_reuse_a_parent_session_after_lock_takeover(site):
    from app.tasks.media_mutation_lock import media_mutation_lock

    settings, unit = site
    read_fd, write_fd = os.pipe()
    try:
        with acquire_operation_authority(settings, unit, (unit,)) as session:
            pid = os.fork()
            if pid == 0:
                os.close(write_fd)
                os.read(read_fd, 1)
                try:
                    with media_mutation_lock(settings):
                        try:
                            authority.assert_operation_authorized(session, (unit,))
                        except (ValueError, PermissionError):
                            os._exit(0)
                except BaseException:
                    os._exit(2)
                os._exit(1)
        os.write(write_fd, b"1")
        assert os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]) == 0
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_untrusted_report_parent_cannot_turn_existing_evidence_into_future_paths(site):
    settings, unit = site
    manifest, frozen, parents = grouped(site)
    old_folder = frozen.parent
    old_folder.rename(old_folder.with_name("detached"))
    foreign_folder = settings.config_dir / "unrelated"
    foreign_folder.mkdir()
    old_folder.symlink_to(foreign_folder, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        with acquire_operation_authority(settings, unit, parents, manifest=manifest):
            pytest.fail("symlinked report directory hid private lifecycle evidence")


def flat_stage(site, *, path_roles=False):
    from app.batch.media_organizer_path_roles import POLICY

    settings, unit = site
    (unit / "photo.jpg").write_bytes(b"photo")
    preview = preview_semantic_unit(unit, allowed_roots=settings.allowed_roots)
    manifest = build_frozen_preview_manifest(
        unit, preview_record=preview, allowed_roots=settings.allowed_roots, job_id=9,
    )
    assert manifest["groups"] == []
    manifest.update(cleanup_policy="deferred", execution_mode=authority.execution_mode(settings))
    if path_roles:
        manifest["path_role_policy"] = POLICY
    frozen = settings.reports_dir / "media_organizer-executions/9/manifest.json"
    save_frozen_preview_manifest(frozen, manifest)
    parents = (unit, unit / manifest["stage_directory"])
    options = dict(frozen_manifest_path=frozen, allowed_roots=settings.allowed_roots)
    with acquire_operation_authority(settings, unit, parents, manifest=manifest) as session:
        stage_frozen_sources(manifest, **options,
                             lease_fence=lambda: authority.assert_operation_authorized(session, parents))
    return manifest, parents, options


@pytest.mark.parametrize("invalid", ["omitted", "boolean", "closed"])
def test_flat_maintenance_refuses_publication_without_live_session(site, invalid):
    settings, unit = site
    manifest, parents, options = flat_stage(site)
    supplied = {}
    if invalid == "closed":
        with acquire_operation_authority(settings, unit, parents, manifest=manifest) as session:
            supplied = {"namespace_custody": session}
    elif invalid == "boolean":
        supplied = {"namespace_custody": True}
    with pytest.raises(ValueError):
        validate_deferred_publication(manifest, **supplied)
    with pytest.raises(PublishingConflict):
        publish_frozen_stage(manifest, **options, lease_fence=lambda: None,
                             defer_directory_cleanup=True, **supplied)
    assert not Path(manifest["moves"][0]["final"]).exists()
    assert (unit / "photo.jpg").read_bytes() == b"photo"


@pytest.mark.parametrize("path_roles", [False, True])
def test_flat_maintenance_refences_session_at_public_link(site, monkeypatch, path_roles):
    from app.batch import media_organizer_publish as publishing

    settings, unit = site
    manifest, parents, options = flat_stage(site, path_roles=path_roles)
    real_link = publishing._link_one
    with ExitStack() as stack:
        session = stack.enter_context(acquire_operation_authority(
            settings, unit, parents, manifest=manifest,
        ))

        def close_session_before_link(*args, **kwargs):
            stack.close()
            return real_link(*args, **kwargs)

        monkeypatch.setattr(publishing, "_link_one", close_session_before_link)
        with pytest.raises(PublishingConflict, match="closed"):
            publish_frozen_stage(manifest, **options, namespace_custody=session,
                                 defer_directory_cleanup=True, lease_fence=lambda: None)
    assert not Path(manifest["moves"][0]["final"]).exists()


def test_flat_maintenance_refences_session_before_handoff_report(site):
    from app.batch.media_organizer_deferred_cleanup import DeferredCleanupConflict

    settings, unit = site
    manifest, parents, options = flat_stage(site)
    with ExitStack() as stack:
        session = stack.enter_context(acquire_operation_authority(
            settings, unit, parents, manifest=manifest,
        ))
        publish_frozen_stage(manifest, **options, namespace_custody=session,
                             defer_directory_cleanup=True, lease_fence=lambda: None)
        with pytest.raises(DeferredCleanupConflict, match="closed"):
            record_deferred_cleanup_evidence(manifest, **options, namespace_custody=session,
                                             lease_fence=stack.close)
    assert not list(options["frozen_manifest_path"].parent.glob("*.manual-cleanup.json"))
