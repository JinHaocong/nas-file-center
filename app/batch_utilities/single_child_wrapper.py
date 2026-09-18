from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import stat

from app.batch_utilities.errors import (
    BatchUtilityCrossRootError,
    BatchUtilityInvalidConfigError,
    BatchUtilityLimitExceededError,
    BatchUtilityPreviewChangedError,
    BatchUtilityScopeNotFoundError,
    BatchUtilitySymlinkBlockedError,
)
from app.fs_ops import probe_existing_noreplace_capability_at


@dataclass(frozen=True)
class SingleChildWrapperDecision:
    candidate_id: str
    wrapper_path: str
    child_path: str | None
    target_path: str | None
    state: str
    wrapper_device: int
    wrapper_inode: int
    child_device: int | None = None
    child_inode: int | None = None
    child_object_type: str | None = None
    capability_reason: str | None = None

    @property
    def selectable(self) -> bool:
        return self.state == "READY"


def _candidate_id(
    *,
    wrapper_path: str,
    wrapper_device: int,
    wrapper_inode: int,
    child_path: str | None,
    child_device: int | None,
    child_inode: int | None,
    child_object_type: str | None,
    target_path: str | None,
    capability_reason: str | None,
) -> str:
    payload = {
        "wrapper_path": os.path.normpath(wrapper_path),
        "wrapper_device": wrapper_device,
        "wrapper_inode": wrapper_inode,
        "child_path": os.path.normpath(child_path) if child_path else None,
        "child_device": child_device,
        "child_inode": child_inode,
        "child_object_type": child_object_type,
        "target_path": os.path.normpath(target_path) if target_path else None,
        "capability_reason": capability_reason,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_scope_paths(scope_path: str, authoritative_root: str) -> tuple[str, str]:
    root = os.path.abspath(os.path.normpath(authoritative_root))
    scope = os.path.abspath(os.path.normpath(scope_path))

    try:
        if os.path.commonpath([root, scope]) != root:
            raise BatchUtilityCrossRootError(
                "Utility scope is outside authoritative Index Root",
                details={"scope_path": scope, "authoritative_root": root},
            )
    except ValueError as exc:
        raise BatchUtilityCrossRootError(
            "Utility scope is outside authoritative Index Root",
            details={"scope_path": scope, "authoritative_root": root},
        ) from exc

    return scope, root


def _directory_open_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise BatchUtilityInvalidConfigError(
            "Platform does not support required descriptor-bound no-follow directory traversal"
        )
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _raise_component_open_error(
    *,
    parent_fd: int,
    component: str,
    display_path: str,
    scope_path: str,
    authoritative_root: str,
    root_component: bool,
    original_error: OSError,
) -> None:
    try:
        st = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        if root_component:
            raise BatchUtilityScopeNotFoundError(
                "Authoritative Index Root not found",
                details={
                    "authoritative_root": authoritative_root,
                    "missing_path": display_path,
                },
            ) from exc
        raise BatchUtilityScopeNotFoundError(
            "Utility scope not found",
            details={"scope_path": scope_path, "missing_path": display_path},
        ) from exc
    except OSError as exc:
        raise BatchUtilityInvalidConfigError(
            f"Failed to inspect utility directory component '{display_path}': {exc}",
            details={
                "path": display_path,
                "scope_path": scope_path,
                "authoritative_root": authoritative_root,
                "errno": getattr(exc, "errno", None),
            },
        ) from exc

    if stat.S_ISLNK(st.st_mode):
        if root_component:
            raise BatchUtilitySymlinkBlockedError(
                "Authoritative Index Root traverses a symlink",
                details={
                    "authoritative_root": authoritative_root,
                    "symlink_path": display_path,
                },
            ) from original_error
        raise BatchUtilitySymlinkBlockedError(
            "Utility scope traverses a symlink",
            details={"scope_path": scope_path, "symlink_path": display_path},
        ) from original_error

    if not stat.S_ISDIR(st.st_mode):
        if root_component:
            raise BatchUtilityInvalidConfigError(
                "Authoritative Index Root component is not a directory",
                details={
                    "authoritative_root": authoritative_root,
                    "path": display_path,
                },
            ) from original_error
        raise BatchUtilityInvalidConfigError(
            "Utility scope component is not a directory",
            details={"scope_path": scope_path, "path": display_path},
        ) from original_error

    raise BatchUtilityInvalidConfigError(
        f"Failed to open utility directory component '{display_path}': {original_error}",
        details={
            "path": display_path,
            "scope_path": scope_path,
            "authoritative_root": authoritative_root,
            "errno": getattr(original_error, "errno", None),
        },
    ) from original_error


def _open_component_dir(
    *,
    parent_fd: int,
    component: str,
    display_path: str,
    scope_path: str,
    authoritative_root: str,
    root_component: bool,
) -> int:
    flags = _directory_open_flags()
    try:
        return os.open(component, flags, dir_fd=parent_fd)
    except OSError as exc:
        _raise_component_open_error(
            parent_fd=parent_fd,
            component=component,
            display_path=display_path,
            scope_path=scope_path,
            authoritative_root=authoritative_root,
            root_component=root_component,
            original_error=exc,
        )
        raise AssertionError("unreachable")


def _open_scope_fd(scope_path: str, authoritative_root: str) -> tuple[str, str, int, os.stat_result]:
    scope, root = _normalize_scope_paths(scope_path, authoritative_root)
    _directory_open_flags()

    current_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    current_display = "/"
    try:
        for part in Path(root).parts[1:]:
            next_display = os.path.join(current_display, part)
            next_fd = _open_component_dir(
                parent_fd=current_fd,
                component=part,
                display_path=next_display,
                scope_path=scope,
                authoritative_root=root,
                root_component=True,
            )
            os.close(current_fd)
            current_fd = next_fd
            current_display = next_display

        relative = os.path.relpath(scope, root)
        if relative != ".":
            for part in Path(relative).parts:
                next_display = os.path.join(current_display, part)
                next_fd = _open_component_dir(
                    parent_fd=current_fd,
                    component=part,
                    display_path=next_display,
                    scope_path=scope,
                    authoritative_root=root,
                    root_component=False,
                )
                os.close(current_fd)
                current_fd = next_fd
                current_display = next_display

        opened_st = os.fstat(current_fd)
        if not stat.S_ISDIR(opened_st.st_mode):
            raise BatchUtilityInvalidConfigError(
                "Utility scope is not a directory",
                details={"scope_path": scope},
            )
        return scope, root, current_fd, opened_st
    except BaseException:
        os.close(current_fd)
        raise


def _verify_scope_binding(
    *,
    scope_path: str,
    authoritative_root: str,
    expected_device: int,
    expected_inode: int,
) -> None:
    _scope, _root, verify_fd, verify_st = _open_scope_fd(scope_path, authoritative_root)
    try:
        if verify_st.st_dev != expected_device or verify_st.st_ino != expected_inode:
            raise BatchUtilityInvalidConfigError(
                "UTILITY_SCOPE_IDENTITY_CHANGED: Utility scope physical identity changed during discovery",
                details={
                    "error": "UTILITY_SCOPE_IDENTITY_CHANGED",
                    "scope_path": scope_path,
                    "authoritative_root": authoritative_root,
                    "expected_device": expected_device,
                    "expected_inode": expected_inode,
                    "current_device": verify_st.st_dev,
                    "current_inode": verify_st.st_ino,
                },
            )
    finally:
        os.close(verify_fd)


@contextmanager
def _acquire_scope_dir(scope_path: str, authoritative_root: str):
    scope, root, scope_fd, scope_st = _open_scope_fd(scope_path, authoritative_root)
    try:
        yield scope, root, scope_fd, scope_st
    except BaseException:
        raise
    else:
        _verify_scope_binding(
            scope_path=scope,
            authoritative_root=root,
            expected_device=scope_st.st_dev,
            expected_inode=scope_st.st_ino,
        )
    finally:
        os.close(scope_fd)


def _raise_wrapper_open_error(
    *,
    parent_fd: int,
    entry_name: str,
    wrapper_path: str,
    original_error: OSError,
) -> None:
    try:
        st = os.stat(entry_name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise BatchUtilityInvalidConfigError(
            f"Failed to reopen wrapper directory '{wrapper_path}': {original_error}",
            details={
                "wrapper_path": wrapper_path,
                "errno": getattr(original_error, "errno", None),
                "stage": "SINGLE_CHILD_DISCOVERY",
            },
        ) from exc

    if stat.S_ISLNK(st.st_mode):
        raise BatchUtilitySymlinkBlockedError(
            f"Wrapper path '{wrapper_path}' became a symlink during discovery",
            details={
                "wrapper_path": wrapper_path,
                "stage": "SINGLE_CHILD_DISCOVERY",
            },
        ) from original_error
    if not stat.S_ISDIR(st.st_mode):
        raise BatchUtilityInvalidConfigError(
            f"Wrapper path '{wrapper_path}' is no longer a directory",
            details={
                "wrapper_path": wrapper_path,
                "stage": "SINGLE_CHILD_DISCOVERY",
            },
        ) from original_error

    raise BatchUtilityInvalidConfigError(
        f"Failed to reopen wrapper directory '{wrapper_path}': {original_error}",
        details={
            "wrapper_path": wrapper_path,
            "errno": getattr(original_error, "errno", None),
            "stage": "SINGLE_CHILD_DISCOVERY",
        },
    ) from original_error


@contextmanager
def _acquire_wrapper_dir_at(
    *,
    scope_fd: int,
    entry_name: str,
    wrapper_path: str,
    expected_device: int,
    expected_inode: int,
):
    flags = _directory_open_flags()
    try:
        wrapper_fd = os.open(entry_name, flags, dir_fd=scope_fd)
    except OSError as exc:
        _raise_wrapper_open_error(
            parent_fd=scope_fd,
            entry_name=entry_name,
            wrapper_path=wrapper_path,
            original_error=exc,
        )
        raise AssertionError("unreachable")

    try:
        opened_st = os.fstat(wrapper_fd)
        if not stat.S_ISDIR(opened_st.st_mode):
            raise BatchUtilityInvalidConfigError(
                f"Wrapper path '{wrapper_path}' is not a directory",
                details={
                    "wrapper_path": wrapper_path,
                    "stage": "SINGLE_CHILD_DISCOVERY",
                },
            )
        if opened_st.st_dev != expected_device or opened_st.st_ino != expected_inode:
            raise BatchUtilityInvalidConfigError(
                f"WRAPPER_IDENTITY_CHANGED: Wrapper '{wrapper_path}' physical identity changed",
                details={
                    "wrapper_path": wrapper_path,
                    "error": "WRAPPER_IDENTITY_CHANGED",
                    "stage": "SINGLE_CHILD_DISCOVERY",
                    "expected_device": expected_device,
                    "expected_inode": expected_inode,
                    "current_device": opened_st.st_dev,
                    "current_inode": opened_st.st_ino,
                },
            )
        yield wrapper_fd, opened_st
    finally:
        os.close(wrapper_fd)


def _entry_exists_at(scope_fd: int, entry_name: str, target_path: str) -> bool:
    try:
        os.stat(entry_name, dir_fd=scope_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise BatchUtilityInvalidConfigError(
            f"Failed to inspect utility target '{target_path}': {exc}",
            details={
                "target_path": target_path,
                "errno": getattr(exc, "errno", None),
            },
        ) from exc


def _identity_row(name: str, st: os.stat_result) -> tuple[str, int, int, int]:
    return (name, int(st.st_dev), int(st.st_ino), stat.S_IFMT(st.st_mode))


def _snapshot_entries(
    entries: list[os.DirEntry[str]],
    *,
    display_parent: str,
) -> tuple[tuple[tuple[str, int, int, int], ...], dict[str, os.stat_result]]:
    rows: list[tuple[str, int, int, int]] = []
    stats_by_name: dict[str, os.stat_result] = {}
    for entry in entries:
        display_path = os.path.join(display_parent, entry.name)
        try:
            entry_st = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise BatchUtilityInvalidConfigError(
                f"Failed to stat utility entry '{display_path}': {exc}",
                details={"path": display_path, "errno": getattr(exc, "errno", None)},
            ) from exc
        rows.append(_identity_row(entry.name, entry_st))
        stats_by_name[entry.name] = entry_st
    rows.sort()
    return tuple(rows), stats_by_name


def _scan_identity_rows(dir_fd: int, *, display_parent: str) -> tuple[tuple[str, int, int, int], ...]:
    try:
        with os.scandir(dir_fd) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError as exc:
        raise BatchUtilityPreviewChangedError(
            "UTILITY_DISCOVERY_CHANGED: Utility directory membership changed during discovery",
            details={
                "error": "UTILITY_DISCOVERY_CHANGED",
                "path": display_parent,
                "errno": getattr(exc, "errno", None),
            },
        ) from exc

    try:
        rows, _stats_by_name = _snapshot_entries(entries, display_parent=display_parent)
    except BatchUtilityInvalidConfigError as exc:
        raise BatchUtilityPreviewChangedError(
            "UTILITY_DISCOVERY_CHANGED: Utility directory membership changed during discovery",
            details={
                "error": "UTILITY_DISCOVERY_CHANGED",
                "path": display_parent,
                "cause": exc.details,
            },
        ) from exc
    return rows


def _verify_discovery_snapshot(
    *,
    scope_path: str,
    authoritative_root: str,
    expected_scope_device: int,
    expected_scope_inode: int,
    expected_scope_rows: tuple[tuple[str, int, int, int], ...],
    wrapper_child_rows: dict[str, tuple[tuple[str, int, int, int], ...]],
) -> None:
    _scope, _root, verify_scope_fd, verify_scope_st = _open_scope_fd(scope_path, authoritative_root)
    try:
        if (
            int(verify_scope_st.st_dev) != int(expected_scope_device)
            or int(verify_scope_st.st_ino) != int(expected_scope_inode)
        ):
            raise BatchUtilityPreviewChangedError(
                "UTILITY_SCOPE_IDENTITY_CHANGED: Utility scope physical identity changed during discovery",
                details={
                    "error": "UTILITY_SCOPE_IDENTITY_CHANGED",
                    "scope_path": scope_path,
                    "expected_device": expected_scope_device,
                    "expected_inode": expected_scope_inode,
                    "current_device": int(verify_scope_st.st_dev),
                    "current_inode": int(verify_scope_st.st_ino),
                },
            )

        current_scope_rows = _scan_identity_rows(verify_scope_fd, display_parent=scope_path)
        if current_scope_rows != expected_scope_rows:
            expected_by_name = {row[0]: row for row in expected_scope_rows}
            current_by_name = {row[0]: row for row in current_scope_rows}
            changed_wrapper = next(
                (
                    name
                    for name in sorted(wrapper_child_rows)
                    if expected_by_name.get(name) != current_by_name.get(name)
                ),
                None,
            )
            if changed_wrapper is not None:
                raise BatchUtilityPreviewChangedError(
                    f"WRAPPER_IDENTITY_CHANGED: Wrapper '{os.path.join(scope_path, changed_wrapper)}' physical identity changed",
                    details={
                        "error": "WRAPPER_IDENTITY_CHANGED",
                        "wrapper_path": os.path.join(scope_path, changed_wrapper),
                        "expected_identity": expected_by_name.get(changed_wrapper),
                        "current_identity": current_by_name.get(changed_wrapper),
                    },
                )
            raise BatchUtilityPreviewChangedError(
                "UTILITY_SCOPE_MEMBERSHIP_CHANGED: Utility scope membership changed during discovery",
                details={
                    "error": "UTILITY_SCOPE_MEMBERSHIP_CHANGED",
                    "scope_path": scope_path,
                    "expected_rows": expected_scope_rows,
                    "current_rows": current_scope_rows,
                },
            )

        scope_identity_by_name = {row[0]: row for row in expected_scope_rows}
        flags = _directory_open_flags()
        for wrapper_name, expected_children in sorted(wrapper_child_rows.items()):
            wrapper_path = os.path.join(scope_path, wrapper_name)
            expected_wrapper = scope_identity_by_name.get(wrapper_name)
            try:
                verify_wrapper_fd = os.open(wrapper_name, flags, dir_fd=verify_scope_fd)
            except OSError as exc:
                raise BatchUtilityPreviewChangedError(
                    f"WRAPPER_IDENTITY_CHANGED: Wrapper '{wrapper_path}' binding changed during discovery",
                    details={
                        "error": "WRAPPER_IDENTITY_CHANGED",
                        "wrapper_path": wrapper_path,
                        "expected_identity": expected_wrapper,
                        "errno": getattr(exc, "errno", None),
                    },
                ) from exc

            try:
                verify_wrapper_st = os.fstat(verify_wrapper_fd)
                current_wrapper = _identity_row(wrapper_name, verify_wrapper_st)
                if expected_wrapper != current_wrapper:
                    raise BatchUtilityPreviewChangedError(
                        f"WRAPPER_IDENTITY_CHANGED: Wrapper '{wrapper_path}' physical identity changed",
                        details={
                            "error": "WRAPPER_IDENTITY_CHANGED",
                            "wrapper_path": wrapper_path,
                            "expected_identity": expected_wrapper,
                            "current_identity": current_wrapper,
                        },
                    )

                current_children = _scan_identity_rows(verify_wrapper_fd, display_parent=wrapper_path)
                if current_children != expected_children:
                    raise BatchUtilityPreviewChangedError(
                        f"CHILD_IDENTITY_CHANGED: Wrapper '{wrapper_path}' child membership changed",
                        details={
                            "error": "CHILD_IDENTITY_CHANGED",
                            "wrapper_path": wrapper_path,
                            "expected_rows": expected_children,
                            "current_rows": current_children,
                        },
                    )
            finally:
                os.close(verify_wrapper_fd)
    finally:
        os.close(verify_scope_fd)


def _decision(
    *,
    wrapper_path: str,
    wrapper_st: os.stat_result,
    state: str,
    child_path: str | None = None,
    child_st: os.stat_result | None = None,
    target_path: str | None = None,
    capability_reason: str | None = None,
) -> SingleChildWrapperDecision:
    child_device = child_st.st_dev if child_st is not None else None
    child_inode = child_st.st_ino if child_st is not None else None
    child_object_type: str | None = None
    if child_st is not None:
        if stat.S_ISREG(child_st.st_mode):
            child_object_type = "file"
        elif stat.S_ISDIR(child_st.st_mode):
            child_object_type = "directory"
        else:
            child_object_type = "special"
    return SingleChildWrapperDecision(
        candidate_id=_candidate_id(
            wrapper_path=wrapper_path,
            wrapper_device=wrapper_st.st_dev,
            wrapper_inode=wrapper_st.st_ino,
            child_path=child_path,
            child_device=child_device,
            child_inode=child_inode,
            child_object_type=child_object_type,
            target_path=target_path,
            capability_reason=capability_reason,
        ),
        wrapper_path=wrapper_path,
        child_path=child_path,
        target_path=target_path,
        state=state,
        wrapper_device=wrapper_st.st_dev,
        wrapper_inode=wrapper_st.st_ino,
        child_device=child_device,
        child_inode=child_inode,
        child_object_type=child_object_type,
        capability_reason=capability_reason,
    )


def discover_single_child_wrappers(
    scope_path: str,
    authoritative_root: str,
    *,
    limit: int = 50_000,
) -> list[SingleChildWrapperDecision]:
    """Read-only discovery for Gate6-B Single-Child Wrapper Collapse.

    The authoritative root and optional scope subpath are acquired component by
    component with descriptor-bound no-follow opens. Wrapper enumeration/open is
    then relative to the fixed scope descriptor, so parent-component ABA cannot
    redirect discovery outside the managed authority boundary. A final repeated
    lexical snapshot verification binds current scope/wrapper/child membership
    before the discovery result can become authoritative.
    """
    if limit <= 0:
        raise BatchUtilityInvalidConfigError("Discovery limit must be positive")

    decisions: list[SingleChildWrapperDecision] = []

    with _acquire_scope_dir(scope_path, authoritative_root) as (scope, root, scope_fd, scope_st):
        try:
            with os.scandir(scope_fd) as iterator:
                scope_entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise BatchUtilityInvalidConfigError(
                f"Failed to scan utility scope '{scope}': {exc}",
                details={"scope_path": scope, "errno": getattr(exc, "errno", None)},
            ) from exc

        scope_rows, scope_stats = _snapshot_entries(scope_entries, display_parent=scope)
        wrapper_child_rows: dict[str, tuple[tuple[str, int, int, int], ...]] = {}

        for entry in scope_entries:
            wrapper_path = os.path.join(scope, entry.name)
            wrapper_st = scope_stats[entry.name]

            if stat.S_ISLNK(wrapper_st.st_mode):
                decisions.append(
                    _decision(wrapper_path=wrapper_path, wrapper_st=wrapper_st, state="WRAPPER_SYMLINK")
                )
            elif not stat.S_ISDIR(wrapper_st.st_mode):
                # Scope-level regular/special files are not wrapper directories.
                continue
            else:
                with _acquire_wrapper_dir_at(
                    scope_fd=scope_fd,
                    entry_name=entry.name,
                    wrapper_path=wrapper_path,
                    expected_device=wrapper_st.st_dev,
                    expected_inode=wrapper_st.st_ino,
                ) as (wrapper_fd, opened_st):
                    try:
                        with os.scandir(wrapper_fd) as iterator:
                            children = sorted(iterator, key=lambda child: child.name)
                    except OSError as exc:
                        raise BatchUtilityInvalidConfigError(
                            f"Failed to scan wrapper directory '{wrapper_path}': {exc}",
                            details={"wrapper_path": wrapper_path, "errno": getattr(exc, "errno", None)},
                        ) from exc

                    child_rows, child_stats = _snapshot_entries(children, display_parent=wrapper_path)
                    wrapper_child_rows[entry.name] = child_rows

                    if len(children) != 1:
                        decisions.append(
                            _decision(
                                wrapper_path=wrapper_path,
                                wrapper_st=opened_st,
                                state="NOT_SINGLE_CHILD",
                            )
                        )
                    else:
                        child = children[0]
                        child_path = os.path.join(wrapper_path, child.name)
                        target_path = os.path.join(scope, child.name)
                        child_st = child_stats[child.name]
                        capability_reason: str | None = None

                        if stat.S_ISLNK(child_st.st_mode):
                            state = "CHILD_SYMLINK"
                        elif not (stat.S_ISREG(child_st.st_mode) or stat.S_ISDIR(child_st.st_mode)):
                            state = "UNSUPPORTED_CHILD"
                        elif _entry_exists_at(scope_fd, child.name, target_path):
                            state = "TARGET_EXISTS"
                        elif int(child_st.st_dev) != int(scope_st.st_dev):
                            state = "UNSUPPORTED_FILESYSTEM"
                            capability_reason = "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"
                        elif (
                            stat.S_ISDIR(child_st.st_mode)
                            and probe_existing_noreplace_capability_at(wrapper_fd, child.name) is not True
                        ):
                            # Directory MOVE has no compatibility fallback. Regular
                            # files may use the executor's hard-link no-clobber
                            # fallback when native RENAME_NOREPLACE is unavailable.
                            state = "UNSUPPORTED_FILESYSTEM"
                            capability_reason = "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"
                        else:
                            state = "READY"

                        decisions.append(
                            _decision(
                                wrapper_path=wrapper_path,
                                wrapper_st=opened_st,
                                state=state,
                                child_path=child_path,
                                child_st=child_st,
                                target_path=target_path,
                                capability_reason=capability_reason,
                            )
                        )

            if len(decisions) > limit:
                raise BatchUtilityLimitExceededError(
                    "Single-child wrapper discovery limit exceeded",
                    details={"limit": limit},
                )

        # A fixed descriptor can continue to see an object that has already
        # been renamed out of the current lexical tree. Reacquire the scope and
        # verify the complete direct scope/wrapper membership twice before the
        # discovery result is accepted. Persistent wrapper/child replacement or
        # detach therefore fails closed as PREVIEW_CHANGED.
        for _ in range(2):
            _verify_discovery_snapshot(
                scope_path=scope,
                authoritative_root=root,
                expected_scope_device=int(scope_st.st_dev),
                expected_scope_inode=int(scope_st.st_ino),
                expected_scope_rows=scope_rows,
                wrapper_child_rows=wrapper_child_rows,
            )

        ready_targets = Counter(
            os.path.normpath(d.target_path)
            for d in decisions
            if d.state == "READY" and d.target_path is not None
        )
        decisions = [
            replace(d, state="DUPLICATE_TARGET")
            if d.state == "READY" and d.target_path is not None and ready_targets[os.path.normpath(d.target_path)] > 1
            else d
            for d in decisions
        ]
        decisions.sort(key=lambda d: os.path.normpath(d.wrapper_path))
        return decisions
