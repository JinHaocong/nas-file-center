"""Dispatch strict custody and explicitly scoped maintenance-window operations."""
from __future__ import annotations

import os
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

from app.batch import media_organizer_custody as strict
from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_manifest import _checksum


class MaintenanceWindowUnavailable(ValueError):
    """A maintenance-window prerequisite changed or cannot be verified."""


def execution_mode(settings) -> str:
    mode = getattr(settings, "media_organizer_execution_mode", "strict")
    if mode not in ("strict", "maintenance_window"):
        raise ValueError("invalid MEDIA_ORGANIZER_EXECUTION_MODE")
    return mode


def _scope_path(unit: Path, path: Path) -> None:
    if (not isinstance(path, Path) or path.anchor != "/" or ".." in path.parts
            or not path.is_relative_to(unit)):
        raise MaintenanceWindowUnavailable("noncanonical or out-of-scope maintenance parent")


def _validate_selection(settings, unit: Path) -> None:
    from app.batch.media_organizer_jobs import _validate_selection as validate_selection

    if not all(getattr(settings, flag, False) is True for flag in (
            "media_organizer_execution_enabled", "allow_mutation", "allow_delete")):
        raise MaintenanceWindowUnavailable("maintenance execution flags are disabled")
    _scope_path(unit, unit)
    validate_selection(str(unit), settings)


@contextmanager
def _strict_proof(settings, unit, parents):
    proof = strict.verified_namespace_custody(settings, unit)
    try:
        strict.assert_exclusive_custody(proof, parents)
        yield proof
    finally:
        release = getattr(proof, "close", None) or getattr(proof, "release", None)
        if callable(release):
            release()


def check_api_eligibility(settings, unit: Path, parents=()) -> None:
    if execution_mode(settings) == "strict":
        with _strict_proof(settings, unit, tuple(parents) or (unit,)):
            return
    _validate_selection(settings, unit)
    for parent in parents:
        _scope_path(unit, parent)
    # The API can have a read-only bind and cannot traverse private Worker stages.
    os.close(_open_directory_nofollow(unit))


def _evidence_exists(path: Path) -> bool:
    """A missing future evidence folder is valid. Inaccessibility or a symlink is not."""
    try:
        fd = _open_directory_nofollow(path.parent)
        try:
            os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        finally:
            os.close(fd)
    except FileNotFoundError:
        return False
    return True


class MaintenanceWindowSession:
    """Pinned directory bindings and cooperative serialization for one Worker operation."""

    def __init__(self, settings, unit, parents, manifest, resources):
        self._worker_pid = os.getpid()
        self._worker_uid = os.geteuid()
        self._settings = settings
        self._unit = unit
        self._scope = frozenset(parents) | {unit}
        self._manifest = manifest
        self._manifest_digest = _checksum(manifest) if manifest is not None else None
        self._resources = resources
        self._bindings = {}
        self._expected = {}
        self._future = set()
        self._retired = set()
        self._frozen = None
        self._open = True
        resources.callback(self._invalidate)
        for path in self._scope:
            _scope_path(unit, path)
        if manifest is not None:
            self._bind_manifest(manifest)
        self.assert_mutation_allowed(self._scope)

    def _invalidate(self):
        self._open = False

    def _bind_manifest(self, manifest):
        from app.batch.media_organizer_cleanup_plan import _read_existing, cleanup_plan_path
        from app.batch.media_organizer_execute_jobs import _manifest_file
        from app.batch.media_organizer_finalize import (
            _journal_path, _operations, journal_directory_retirements,
        )
        from app.batch.media_organizer_publish import (
            _group_receipt_path, _read_group_receipt, _validate_shape,
        )

        unit = self._unit
        job_id = manifest.get("job_id")
        if (type(job_id) is not int or job_id <= 0 or manifest.get("unit") != str(unit)
                or manifest.get("execution_mode") != "maintenance_window"
                or manifest.get("cleanup_policy") != "deferred"
                or manifest.get("stage_directory") != f".nfc-media-organizer-stage-{job_id}"):
            raise MaintenanceWindowUnavailable("maintenance scope differs from frozen operation")
        rows, groups = _validate_shape(manifest, unit)
        self._expected = {Path(path): tuple(identity)
                          for path, identity in manifest["wrapper_identities"].items()}
        self._expected[unit] = (manifest["unit_dev"], manifest["unit_ino"])
        stage = unit / manifest["stage_directory"]
        allowed = set(self._expected) | {stage} | {unit / name for name in groups}
        for row in rows:
            allowed.add(Path(row["source"]).parent)
        for path in tuple(allowed):
            _scope_path(unit, path)
            allowed.update(p for p in path.parents if p.is_relative_to(unit))
        if not self._scope <= allowed:
            raise MaintenanceWindowUnavailable("requested parent outside frozen operation scope")

        self._frozen = _manifest_file(self._settings, job_id)
        plan_path = cleanup_plan_path(self._frozen)
        plan_exists = _evidence_exists(plan_path)
        if plan_exists:
            plan = _read_existing(plan_path)
            _operations(manifest, plan)
            self._expected[stage] = tuple(plan["stage"]["identity"])
        else:
            self._future.add(stage)
        for ordinal, name in enumerate(groups, 1):
            group = unit / name
            receipt = _group_receipt_path(self._frozen, ordinal)
            if plan_exists or _evidence_exists(receipt):
                identity = _read_group_receipt(receipt, manifest, name, ordinal)
                if self._expected.get(group, identity) != identity:
                    raise MaintenanceWindowUnavailable("frozen wrapper and public group receipt differ")
                self._expected[group] = identity
            elif group not in self._expected:
                self._future.add(group)
        if _evidence_exists(_journal_path(self._frozen)):
            self._retired, _ = journal_directory_retirements(manifest, self._frozen)

    def _assert_missing(self, path):
        if path == self._unit:
            raise MaintenanceWindowUnavailable("maintenance unit disappeared")
        if path in self._retired or path in self._future:
            return
        if self._frozen is not None:
            from app.batch.media_organizer_finalize import _journal_path, journal_directory_retirements

            if _evidence_exists(_journal_path(self._frozen)):
                completed, pending = journal_directory_retirements(self._manifest, self._frozen)
                self._retired.update(completed)
                if path in completed or path == pending:
                    self._retired.add(path)
                    return
        raise MaintenanceWindowUnavailable("maintenance parent missing without journaled retirement")

    def _check_parent(self, path):
        try:
            fd = _open_directory_nofollow(path)
        except FileNotFoundError:
            self._assert_missing(path)
            return
        try:
            info = os.fstat(fd)
            identity = (info.st_dev, info.st_ino)
            if (path in self._retired or identity != self._expected.get(path, identity)
                    or info.st_dev != self._expected.get(self._unit, identity)[0]):
                raise MaintenanceWindowUnavailable("maintenance parent inode binding changed")
            if (os.fstatvfs(fd).f_flag & os.ST_RDONLY
                    or not os.access(".", os.W_OK | os.X_OK, dir_fd=fd, effective_ids=True)):
                raise MaintenanceWindowUnavailable("maintenance parent is not writable by the Worker")
            if path not in self._bindings:
                self._expected[path] = identity
                self._bindings[path] = fd
                self._resources.callback(os.close, fd)
                fd = None
            self._future.discard(path)
        finally:
            if fd is not None:
                os.close(fd)

    def assert_mutation_allowed(self, parents, *, manifest=None) -> None:
        from app.tasks.media_mutation_lock import assert_media_mutation_lock

        if (not self._open or os.getpid() != self._worker_pid
                or os.geteuid() != self._worker_uid or self._worker_uid == 0):
            raise MaintenanceWindowUnavailable("maintenance session is closed or Worker identity changed")
        if manifest is not None and self._manifest_digest != _checksum(manifest):
            raise MaintenanceWindowUnavailable("maintenance session belongs to different frozen evidence")
        assert_media_mutation_lock(self._settings)
        paths = {self._unit}
        for path in parents:
            _scope_path(self._unit, path)
            if path not in self._scope:
                raise MaintenanceWindowUnavailable("parent is outside the acquired maintenance scope")
            paths.add(path)
            paths.update(p for p in path.parents if p.is_relative_to(self._unit))
        for path in sorted(paths, key=lambda p: (len(p.parts), p)):
            self._check_parent(path)


@contextmanager
def acquire_operation_authority(settings, unit: Path, parents, *, manifest=None):
    parents = tuple(parents)
    if execution_mode(settings) == "strict":
        with _strict_proof(settings, unit, parents or (unit,)) as proof:
            yield proof
        return
    from app.tasks.media_mutation_lock import media_mutation_lock

    if not hasattr(os, "geteuid") or os.geteuid() == 0:
        raise PermissionError("maintenance execution requires a non-root Worker")
    with media_mutation_lock(settings), ExitStack() as resources:
        _validate_selection(settings, unit)
        yield MaintenanceWindowSession(settings, unit, parents, manifest, resources)


@dataclass(frozen=True)
class _FencedAuthority:
    authority: object
    callback: Callable[[], None]


OperationAuthority = strict.ScopedNamespaceCustody | MaintenanceWindowSession | _FencedAuthority


def fence_operation_authority(authority: OperationAuthority, callback) -> _FencedAuthority:
    if not callable(callback):
        raise ValueError("a Worker lease fence is required")
    return _FencedAuthority(authority, callback)


def is_maintenance_session(authority) -> bool:
    while type(authority) is _FencedAuthority:
        authority = authority.authority
    return type(authority) is MaintenanceWindowSession


def assert_operation_authorized(authority, parents, *, manifest=None) -> None:
    while type(authority) is _FencedAuthority:
        authority.callback()
        authority = authority.authority
    if type(authority) is MaintenanceWindowSession:
        authority.assert_mutation_allowed(parents, manifest=manifest)
    else:
        if manifest is not None and manifest.get("execution_mode") == "maintenance_window":
            raise MaintenanceWindowUnavailable("frozen maintenance operation requires a live maintenance session")
        strict.assert_exclusive_custody(authority, parents)


def publication_parents(manifest: dict) -> tuple[Path, ...]:
    parents = {Path(manifest["unit"])}
    for row in manifest["moves"]:
        parents.update(Path(row[key]).parent for key in ("source", "target", "final"))
    return tuple(sorted(parents))


def publication_fence(manifest: dict, authority, lease_fence: Callable[[], None]) -> Callable[[], None]:
    """Keep the scoped session live through every nested maintenance mutation."""
    if manifest.get("execution_mode", "strict") != "maintenance_window":
        return lease_fence
    parents = publication_parents(manifest)
    assert_operation_authorized(authority, parents, manifest=manifest)
    fenced = fence_operation_authority(authority, lease_fence)
    return partial(assert_operation_authorized, fenced, parents)
