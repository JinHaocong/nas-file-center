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
    BatchUtilityScopeNotFoundError,
    BatchUtilitySymlinkBlockedError,
)


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
    target_path: str | None,
) -> str:
    payload = {
        "wrapper_path": os.path.normpath(wrapper_path),
        "wrapper_device": wrapper_device,
        "wrapper_inode": wrapper_inode,
        "child_path": os.path.normpath(child_path) if child_path else None,
        "child_device": child_device,
        "child_inode": child_inode,
        "target_path": os.path.normpath(target_path) if target_path else None,
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


def _decision(
    *,
    wrapper_path: str,
    wrapper_st: os.stat_result,
    state: str,
    child_path: str | None = None,
    child_st: os.stat_result | None = None,
    target_path: str | None = None,
) -> SingleChildWrapperDecision:
    child_device = child_st.st_dev if child_st is not None else None
    child_inode = child_st.st_ino if child_st is not None else None
    return SingleChildWrapperDecision(
        candidate_id=_candidate_id(
            wrapper_path=wrapper_path,
            wrapper_device=wrapper_st.st_dev,
            wrapper_inode=wrapper_st.st_ino,
            child_path=child_path,
            child_device=child_device,
            child_inode=child_inode,
            target_path=target_path,
        ),
        wrapper_path=wrapper_path,
        child_path=child_path,
        target_path=target_path,
        state=state,
        wrapper_device=wrapper_st.st_dev,
        wrapper_inode=wrapper_st.st_ino,
        child_device=child_device,
        child_inode=child_inode,
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
    redirect discovery outside the managed authority boundary.
    """
    if limit <= 0:
        raise BatchUtilityInvalidConfigError("Discovery limit must be positive")

    decisions: list[SingleChildWrapperDecision] = []

    with _acquire_scope_dir(scope_path, authoritative_root) as (scope, _root, scope_fd, _scope_st):
        try:
            with os.scandir(scope_fd) as iterator:
                scope_entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise BatchUtilityInvalidConfigError(
                f"Failed to scan utility scope '{scope}': {exc}",
                details={"scope_path": scope, "errno": getattr(exc, "errno", None)},
            ) from exc

        for entry in scope_entries:
            wrapper_path = os.path.join(scope, entry.name)
            try:
                wrapper_st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise BatchUtilityInvalidConfigError(
                    f"Failed to stat utility scope entry '{wrapper_path}': {exc}",
                    details={"path": wrapper_path, "errno": getattr(exc, "errno", None)},
                ) from exc

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
                        try:
                            child_st = child.stat(follow_symlinks=False)
                        except OSError as exc:
                            raise BatchUtilityInvalidConfigError(
                                f"Failed to stat wrapper child '{child_path}': {exc}",
                                details={"child_path": child_path, "errno": getattr(exc, "errno", None)},
                            ) from exc

                        if stat.S_ISLNK(child_st.st_mode):
                            state = "CHILD_SYMLINK"
                        elif stat.S_ISREG(child_st.st_mode):
                            state = "CHILD_NOT_DIRECTORY"
                        elif not stat.S_ISDIR(child_st.st_mode):
                            state = "UNSUPPORTED_CHILD"
                        elif _entry_exists_at(scope_fd, child.name, target_path):
                            state = "TARGET_EXISTS"
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
                            )
                        )

            if len(decisions) > limit:
                raise BatchUtilityLimitExceededError(
                    "Single-child wrapper discovery limit exceeded",
                    details={"limit": limit},
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
