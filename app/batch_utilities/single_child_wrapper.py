from __future__ import annotations

from collections import Counter
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
from app.batch_utilities.flatten import acquire_wrapper_dir


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


def _validate_scope(scope_path: str, authoritative_root: str) -> tuple[str, str]:
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

    try:
        root_st = os.lstat(root)
    except FileNotFoundError as exc:
        raise BatchUtilityScopeNotFoundError(
            "Authoritative Index Root not found",
            details={"authoritative_root": root},
        ) from exc
    if stat.S_ISLNK(root_st.st_mode):
        raise BatchUtilitySymlinkBlockedError(
            "Authoritative Index Root is a symlink",
            details={"authoritative_root": root},
        )
    if not stat.S_ISDIR(root_st.st_mode):
        raise BatchUtilityInvalidConfigError(
            "Authoritative Index Root is not a directory",
            details={"authoritative_root": root},
        )

    current = Path(root)
    relative = os.path.relpath(scope, root)
    if relative != ".":
        for part in Path(relative).parts:
            current = current / part
            try:
                st = os.lstat(current)
            except FileNotFoundError as exc:
                raise BatchUtilityScopeNotFoundError(
                    "Utility scope not found",
                    details={"scope_path": scope, "missing_path": str(current)},
                ) from exc
            if stat.S_ISLNK(st.st_mode):
                raise BatchUtilitySymlinkBlockedError(
                    "Utility scope traverses a symlink",
                    details={"scope_path": scope, "symlink_path": str(current)},
                )
            if not stat.S_ISDIR(st.st_mode):
                raise BatchUtilityInvalidConfigError(
                    "Utility scope component is not a directory",
                    details={"scope_path": scope, "path": str(current)},
                )

    return scope, root


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

    Only direct children of ``scope_path`` are examined as wrappers. The function
    never follows wrapper/child symlinks and never mutates the filesystem.
    """
    if limit <= 0:
        raise BatchUtilityInvalidConfigError("Discovery limit must be positive")

    scope, _root = _validate_scope(scope_path, authoritative_root)
    decisions: list[SingleChildWrapperDecision] = []

    try:
        scope_entries = sorted(os.scandir(scope), key=lambda entry: entry.name)
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
            with acquire_wrapper_dir(
                wrapper_path,
                expected_device=wrapper_st.st_dev,
                expected_inode=wrapper_st.st_ino,
                stage="SINGLE_CHILD_DISCOVERY",
            ) as (dir_handle, opened_st):
                try:
                    children = sorted(os.scandir(dir_handle), key=lambda child: child.name)
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
                    elif os.path.lexists(target_path):
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
